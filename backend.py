"""Local-only API. One business store; later endpoints can use this same API."""
import base64
import io
import json
import os
import hmac
import hashlib
import logging
import math
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from fastapi import FastAPI, HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field
from fastapi import Request, Query
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from concurrent.futures import ThreadPoolExecutor
import threading
import time
import shutil
from functools import wraps
from collections import deque
from fastapi.responses import Response

from algorithms.enhancement import enhance as light_enhance
from algorithms.dehazing import enhance as dehaze

ROOT = Path(__file__).resolve().parent
STORE = Path(os.environ.get("HAIXUN_DATA_DIR", ROOT / "data"))
STORE.mkdir(parents=True, exist_ok=True)
app = FastAPI(title="海寻统一业务 API", version="0.4.0")
logger=logging.getLogger('seaseek')
API_MODE=os.environ.get('SEASEEK_API_MODE','local')
API_TOKEN=os.environ.get('HAIXUN_API_TOKEN','')
RESET_TOKEN=os.environ.get('HAIXUN_RESET_TOKEN','')
_quota_lock=threading.Lock()
_quota={}
_image_lock=threading.Lock()
if API_MODE=='remote' and not API_TOKEN:
    raise RuntimeError('Remote API requires HAIXUN_API_TOKEN.')

@app.middleware('http')
async def service_access(request,call_next):
    if API_TOKEN and request.url.path!='/health':
        supplied=request.headers.get('Authorization','')
        if not hmac.compare_digest(supplied.encode(),('Bearer '+API_TOKEN).encode()):
            return JSONResponse(status_code=401,content={'detail':'服务访问未授权'})
    if request.method in ('POST','PATCH'):
        try:
            length=int(request.headers.get('content-length','0') or 0)
            if length<0:raise ValueError()
        except ValueError:
            return JSONResponse(status_code=400,content={'detail':'上传长度无效'})
        if length>17_000_000:
            return JSONResponse(status_code=413,content={'detail':'上传超过演示环境限制'})
        # Expensive inference and ordinary writes have independent budgets.
        path=request.url.path
        expensive=request.method=='POST' and (path in ('/analyses','/analyses/upload','/videos') or (path.startswith('/analyses/') and path.endswith('/detect')))
        session=request.headers.get('X-Seaseek-Session','')[:64] or (request.client.host if request.client else 'unknown')
        tick=time.monotonic()
        with _quota_lock:
            for key in list(_quota):
                while _quota[key] and _quota[key][0]<tick-3600:_quota[key].popleft()
                if not _quota[key]:del _quota[key]
            keys=[('global',240),('compute-'+session,60)] if expensive else [('write-global',1200),('write-'+session,300)]
            if path.startswith('/admin/') or path=='/demo/reset':keys=[]
            if request.url.path in ('/analyses','/analyses/upload'):keys += [('image-global',100),('image-'+session,20)]
            blocked=[key for key,limit in keys if len(_quota.get(key,()))>=limit]
            if blocked:
                retry=max(1,math.ceil(max(_quota[key][0]+3600-tick for key in blocked)))
                return JSONResponse(status_code=429,content={'detail':f"{'分析' if expensive else '普通操作'}额度已达上限，约 {math.ceil(retry/60)} 分钟后可重试；分析额度不影响反馈与报告"},headers={'Retry-After':str(retry)})
            for key,_ in keys:_quota.setdefault(key,deque()).append(tick)
    return await call_next(request)
STATUSES = ["待核实", "待分派", "处理中", "已完成", "已排除"]

def now():
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")

@contextmanager
def db():
    con = sqlite3.connect(STORE / "haixun.sqlite", timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

with db() as con:
    con.executescript("""
    CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,name TEXT,area TEXT,owner TEXT,description TEXT,status TEXT,created TEXT);
    CREATE TABLE IF NOT EXISTS analyses(id TEXT PRIMARY KEY,task_id TEXT REFERENCES tasks(id),name TEXT,method TEXT,selected TEXT,original BLOB,result BLOB,width INTEGER,height INTEGER,created TEXT);
    CREATE TABLE IF NOT EXISTS clues(id TEXT PRIMARY KEY,task_id TEXT REFERENCES tasks(id),analysis_id TEXT REFERENCES analyses(id),title TEXT,status TEXT,assignee TEXT,notes TEXT,lat REAL,lon REAL,created TEXT);
    CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,task_id TEXT REFERENCES tasks(id),message TEXT,created TEXT);
    CREATE TABLE IF NOT EXISTS detections(analysis_id TEXT PRIMARY KEY REFERENCES analyses(id),image BLOB,predictions TEXT,confidence REAL,source TEXT,created TEXT);
    CREATE TABLE IF NOT EXISTS videos(id TEXT PRIMARY KEY,task_id TEXT REFERENCES tasks(id),name TEXT,status TEXT,progress REAL,error TEXT,confidence REAL,sample_fps REAL,created TEXT);
    CREATE TABLE IF NOT EXISTS video_clues(clue_id TEXT PRIMARY KEY REFERENCES clues(id),video_id TEXT REFERENCES videos(id),frame_index INTEGER,time REAL);
    CREATE TABLE IF NOT EXISTS reviews(analysis_id TEXT PRIMARY KEY REFERENCES analyses(id),decision TEXT,created TEXT);
    CREATE TABLE IF NOT EXISTS feedback_requests(clue_id TEXT REFERENCES clues(id) ON DELETE CASCADE,request_id TEXT,payload TEXT,PRIMARY KEY(clue_id,request_id));
    """)
    con.execute("UPDATE videos SET status='failed',error='服务重启中断了处理，请重新提交' WHERE status IN ('queued','running')")

def require(con, table, item_id):
    row = con.execute(f"SELECT * FROM {table} WHERE id=?", (item_id,)).fetchone()
    if not row:
        raise HTTPException(404, "记录不存在")
    return row

def event(con, task, message):
    con.execute("INSERT INTO events(task_id,message,created) VALUES(?,?,?)", (task, message, now()))

class Task(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    area: str = Field(min_length=1, max_length=100)
    owner: str = Field(min_length=1, max_length=50)
    description: str = Field(default="", max_length=2000)

class Analysis(BaseModel):
    task_id: str
    name: str = Field(max_length=200)
    image: str = Field(max_length=17_000_000)
    method: str

class Clue(BaseModel):
    task_id: str
    analysis_id: str | None = None
    title: str = Field(min_length=1, max_length=100)
    notes: str = Field(default="", max_length=3000)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)

class Update(BaseModel):
    status: str
    assignee: str = Field(default="", max_length=50)
    feedback: str = Field(default="", max_length=2000)
    request_id: str | None = Field(default=None,min_length=1,max_length=64)

@app.get("/health")
def health():
    return {"status": "ok", "mode": "shared backend" if API_MODE=='remote' else "local prototype", "version": "0.4.0"}

def require_management(request):
    supplied=request.headers.get('X-Seaseek-Reset','')
    if API_MODE=='remote' or RESET_TOKEN:
        if not RESET_TOKEN or not hmac.compare_digest(supplied.encode(),RESET_TOKEN.encode()):
            raise HTTPException(403,'此操作需要演示管理口令')

def ensure_storage(incoming=0):
    # Keep space for SQLite transactions, output frames and the shared host.
    if shutil.disk_usage(STORE).free < 512*1024*1024+incoming:
        raise HTTPException(507,'可用磁盘空间不足，请在任务总览的演示管理中预览并清理资源')

@app.get("/tasks")
def tasks():
    with db() as con:
        return [dict(r) for r in con.execute("SELECT * FROM tasks ORDER BY created DESC,rowid DESC")]

@app.get('/overview')
def overview_snapshot():
    # One network round trip regardless of task count; never include media BLOBs.
    with db() as con:
        return {
            'tasks':[dict(r) for r in con.execute('SELECT * FROM tasks ORDER BY created DESC,rowid DESC')],
            'clues':[dict(r) for r in con.execute('SELECT task_id,status FROM clues')],
            'events':[dict(r) for r in con.execute('SELECT * FROM events ORDER BY created DESC,id DESC LIMIT 7')],
        }

@app.post("/tasks")
def create_task(item: Task):
    ident = uuid.uuid4().hex
    if not all(v.strip() for v in (item.name, item.area, item.owner)):
        raise HTTPException(422, "请填写任务名称、海域和负责人")
    with db() as con:
        con.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?)", (ident,item.name.strip(),item.area.strip(),item.owner.strip(),item.description,"进行中",now()))
        event(con, ident, f"创建任务 · {item.name}")
    return {"id": ident}

@app.post("/demo")
def demo():
    with db() as con:
        if con.execute("SELECT 1 FROM tasks WHERE id='demo-coastal'").fetchone():
            return {"id": "demo-coastal"}
        con.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?)", ("demo-coastal","近海联合搜救 · 演示任务","青岛近海（虚构演示）","演示负责人","所有位置与线索均为演示数据，不代表真实搜救事件。","进行中",now()))
        for i, (title,status,person,lat,lon) in enumerate([
            ("疑似船舶，待影像核实","待核实","",36.02,120.44),
            ("近海船舶联络线索","处理中","演示处置员",36.04,120.48),
            ("无坐标影像线索","待分派","",None,None)]):
            con.execute("INSERT INTO clues VALUES(?,?,?,?,?,?,?,?,?,?)", (f"demo-{i}","demo-coastal",None,title,status,person,"虚构演示线索；位置为人工预置。",lat,lon,now()))
        event(con,"demo-coastal","载入演示任务与三条虚构线索")
    return {"id": "demo-coastal"}

@app.post('/demo/reset')
def reset_demo(request: Request):
    require_management(request)
    with _video_submit_lock, _image_lock:
        with db() as con:
            if con.execute("SELECT 1 FROM videos WHERE task_id='demo-coastal' AND status IN ('queued','running')").fetchone():
                raise HTTPException(409,'请等待演示视频处理结束后再重置')
            video_ids=[r[0] for r in con.execute("SELECT id FROM videos WHERE task_id='demo-coastal'")]
            if any(ident in _video_jobs and not _video_jobs[ident].done() for ident in video_ids):
                raise HTTPException(409,'视频取消正在完成，请稍后再重置')
            con.execute("DELETE FROM video_clues WHERE clue_id IN (SELECT id FROM clues WHERE task_id='demo-coastal')")
            con.execute("DELETE FROM clues WHERE task_id='demo-coastal'")
            for table in ('detections','reviews'):
                con.execute(f"DELETE FROM {table} WHERE analysis_id IN (SELECT id FROM analyses WHERE task_id='demo-coastal')")
            for table in ('analyses','videos','events','tasks'):
                con.execute(f"DELETE FROM {table} WHERE {'id' if table=='tasks' else 'task_id'}='demo-coastal'")
        for ident in video_ids:
            directory=video_dir(ident).resolve()
            if directory.parent==(STORE/'videos').resolve():shutil.rmtree(directory,ignore_errors=True)
        return demo()

def png(image):
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()

def jpeg(image,quality=90):
    buf=io.BytesIO()
    image.convert('RGB').save(buf,format='JPEG',quality=quality,optimize=True)
    return buf.getvalue()

def image_work(func):
    @wraps(func)
    def guarded(*args,**kwargs):
        with _video_submit_lock:
            if not _image_lock.acquire(blocking=False):raise HTTPException(429,'正在处理另一张影像，请完成后重试')
        try:
            with db() as con:
                if con.execute("SELECT 1 FROM videos WHERE status IN ('queued','running')").fetchone():
                    raise HTTPException(409,'视频正在排队或检测，请完成后再分析图片')
            return func(*args,**kwargs)
        finally:_image_lock.release()
    return guarded

def image_bytes(row,kind):
    return row['original'] if kind=='result' and row['result'] is None else row[kind]

@app.post("/analyses")
def analyze(item: Analysis):
    try:raw=base64.b64decode(item.image,validate=True)
    except ValueError as exc:raise HTTPException(422,'图片无法读取或尺寸超过限制') from exc
    return analyze_bytes(item.task_id,item.name,item.method,raw)

@image_work
def analyze_bytes(task_id,name,method,raw):
    from types import SimpleNamespace
    item=SimpleNamespace(task_id=task_id,name=name,method=method)
    methods = {"original","adaptive","gamma_light","gamma_dark","clahe","dehaze_mild","dehaze_mix","dehaze_adaptive"}
    if item.method not in methods:
        raise HTTPException(422,"不支持的增强方法")
    with db() as con:
        require(con,"tasks",item.task_id)
    try:
        if len(raw)>12*1024*1024:
            raise ValueError("文件超过 12 MB")
        with Image.open(io.BytesIO(raw)) as source:
            if source.width*source.height>24_000_000:
                raise ValueError("图片像素超过 2400 万")
            image = ImageOps.exif_transpose(source).convert("RGB")
        image.thumbnail((1600,1600))
    except (ValueError,UnidentifiedImageError,OSError,Image.DecompressionBombError) as exc:
        raise HTTPException(422, "图片无法读取或尺寸超过限制") from exc
    ensure_storage(32*1024*1024)
    rgb = np.asarray(image)
    output, info = (dehaze if item.method.startswith("dehaze") else light_enhance)(rgb,item.method)
    ident = uuid.uuid4().hex
    original=png(image)
    result=None if np.array_equal(rgb,output) else png(Image.fromarray(output))
    with db() as con:
        if con.execute('SELECT COUNT(*) FROM analyses').fetchone()[0]>=500:
            raise HTTPException(429,'演示影像存储已满，请在任务总览的演示管理中预览并清理资源')
        if storage_summary()['image_bytes']+len(original)+len(result or b'')>512*1024*1024:
            raise HTTPException(507,'影像容量已达上限，请在演示管理中预览并清理')
        con.execute("INSERT INTO analyses VALUES(?,?,?,?,?,?,?,?,?,?)", (ident,item.task_id,item.name,item.method,info["selected"],original,result,image.width,image.height,now()))
        event(con,item.task_id,f"完成影像分析 · {item.name}")
    return {"id":ident,"selected":info["selected"],"width":image.width,"height":image.height}

@app.get("/analyses")
def analyses(task_id: str):
    with db() as con:
        return [dict(r) for r in con.execute("SELECT id,name,method,selected,width,height,created FROM analyses WHERE task_id=? ORDER BY rowid DESC",(task_id,))]

@app.post('/analyses/upload')
async def upload_analysis(request: Request,task_id: str,name: str=Query(max_length=200),method: str='original'):
    raw=bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw)>12*1024*1024:raise HTTPException(413,'图片超过 12 MB')
    # Both upload formats share validation without making another base64 copy.
    from starlette.concurrency import run_in_threadpool
    return await run_in_threadpool(analyze_bytes,task_id,name,method,raw)

@app.get("/analyses/{ident}")
def analysis(ident: str):
    with db() as con:
        row=con.execute('SELECT id,task_id,name,method,selected,width,height,created,result IS NULL AS result_is_original FROM analyses WHERE id=?',(ident,)).fetchone()
        if not row:raise HTTPException(404,'记录不存在')
        row=dict(row)
        detection=con.execute("SELECT predictions,confidence,source,created FROM detections WHERE analysis_id=?",(ident,)).fetchone()
        review=con.execute('SELECT decision,created FROM reviews WHERE analysis_id=?',(ident,)).fetchone()
    row['detection']=None
    if detection:
        row['detection']=dict(detection)
        row['detection']['predictions']=json.loads(detection['predictions'])
    row['review']=dict(review) if review else None
    return row

@app.get('/analyses/{ident}/media/{kind}')
def analysis_media(ident: str,kind: str,size: str='preview'):
    if kind not in ('original','result','detection') or size not in ('preview','thumb','full'):
        raise HTTPException(404,'图片不存在')
    with db() as con:
        row=require(con,'analyses',ident)
        if kind=='detection':
            found=con.execute('SELECT image FROM detections WHERE analysis_id=?',(ident,)).fetchone()
            if not found:raise HTTPException(404,'暂无标注图')
            raw=found['image']
        else:raw=image_bytes(row,kind)
    if size=='full':return Response(raw,media_type='image/png',headers={'Cache-Control':'private, max-age=300'})
    with Image.open(io.BytesIO(raw)) as image:
        image.thumbnail((480,480) if size=='thumb' else (1280,1280))
        content=jpeg(image,80 if size=='thumb' else 84)
    return Response(content,media_type='image/jpeg',headers={'Cache-Control':'private, max-age=300'})

class Review(BaseModel):
    decision: str

@app.post('/analyses/{ident}/review')
def review_analysis(ident: str,item: Review):
    if item.decision not in ('confirmed','ignored'):raise HTTPException(422,'核实结果无效')
    with db() as con:
        row=require(con,'analyses',ident)
        con.execute('INSERT OR REPLACE INTO reviews VALUES(?,?,?)',(ident,item.decision,now()))
        event(con,row['task_id'],'人工核实影像 · '+('确认目标' if item.decision=='confirmed' else '忽略结果'))
    return {'decision':item.decision}

class DetectSettings(BaseModel):
    confidence: float = Field(default=.25,ge=.05,le=.95)
    source: str = 'original'

@app.post('/analyses/{ident}/detect')
@image_work
def detect_image(ident: str,settings: DetectSettings):
    if settings.source not in ('original','result'):
        raise HTTPException(422,'检测输入无效')
    with db() as con:
        row=dict(require(con,'analyses',ident))
    from algorithms.detector import detect
    try:
        image=Image.open(io.BytesIO(image_bytes(row,settings.source))).convert('RGB')
        annotated,predictions=detect(np.asarray(image),settings.confidence)
    except Exception as exc:
        logger.exception('Ship detection failed for %s',ident)
        raise HTTPException(503,'船舶检测暂时失败，请重试；持续失败时请联系维护者') from exc
    ensure_storage(16*1024*1024)
    annotated_bytes=png(annotated)
    with db() as con:
        previous=con.execute('SELECT LENGTH(image) FROM detections WHERE analysis_id=?',(ident,)).fetchone()
    if storage_summary()['image_bytes']-(previous[0] if previous else 0)+len(annotated_bytes)>512*1024*1024:
        raise HTTPException(507,'影像容量已达上限，请在演示管理中预览并清理')
    with db() as con:
        con.execute('INSERT OR REPLACE INTO detections VALUES(?,?,?,?,?,?)',(ident,annotated_bytes,json.dumps(predictions,ensure_ascii=False),settings.confidence,settings.source,now()))
        con.execute('DELETE FROM reviews WHERE analysis_id=?',(ident,))
        event(con,row['task_id'],f"船舶检测 · {row['name']} · {len(predictions)} 个目标 · {'原图' if settings.source=='original' else '增强图'}")
    return {'count':len(predictions),'predictions':predictions}

_video_executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='haixun-video')
_video_submit_lock=threading.Lock()
_video_jobs={}

def video_dir(ident):
    return STORE/'videos'/ident

def remove_video_files(ident):
    path=video_dir(ident)
    if path.resolve().parent!=(STORE/'videos').resolve():
        raise RuntimeError('Video path outside storage')
    if path.exists():shutil.rmtree(path)

def storage_summary():
    with db() as con:
        count,image_bytes=con.execute('SELECT COUNT(*),COALESCE(SUM(LENGTH(original)+COALESCE(LENGTH(result),0)),0) FROM analyses').fetchone()
        image_bytes+=con.execute('SELECT COALESCE(SUM(LENGTH(image)),0) FROM detections').fetchone()[0]
        reusable=con.execute('PRAGMA freelist_count').fetchone()[0]*con.execute('PRAGMA page_size').fetchone()[0]
    return dict(analyses=count,analysis_limit=500,image_bytes=image_bytes,image_limit=512*1024*1024,disk_free=shutil.disk_usage(STORE).free,database_bytes=(STORE/'haixun.sqlite').stat().st_size,reusable_bytes=reusable)

class CleanupSelection(BaseModel):
    task_id: str
    include_linked: bool = False
    confirmation: str = ''

def cleanup_plan(con,item):
    require(con,'tasks',item.task_id)
    images=[dict(row) for row in con.execute('SELECT id,name,LENGTH(original)+COALESCE(LENGTH(result),0)+COALESCE((SELECT LENGTH(image) FROM detections d WHERE d.analysis_id=a.id),0) AS bytes,(SELECT COUNT(*) FROM clues c WHERE c.analysis_id=a.id) AS linked FROM analyses a WHERE task_id=? ORDER BY id',(item.task_id,))]
    images=[row for row in images if item.include_linked or not row['linked']]
    videos=[dict(row) for row in con.execute("SELECT id,name,status FROM videos v WHERE task_id=? AND status IN ('failed','cancelled') AND NOT EXISTS(SELECT 1 FROM video_clues c WHERE c.video_id=v.id) ORDER BY id",(item.task_id,)) if row['id'] not in _video_jobs or _video_jobs[row['id']].done()]
    signature=hashlib.sha256(json.dumps(dict(task=item.task_id,linked=item.include_linked,images=images,videos=videos),sort_keys=True).encode()).hexdigest()
    return dict(images=images,videos=videos,linked_clues=sum(row['linked'] for row in images),reclaimable_image_bytes=sum(row['bytes'] for row in images),confirmation=signature)

@app.get('/admin/storage')
def admin_storage(request: Request):
    require_management(request)
    return storage_summary()

@app.post('/admin/cleanup/preview')
def preview_cleanup(request: Request,item: CleanupSelection):
    require_management(request)
    with db() as con:return cleanup_plan(con,item)

@app.post('/admin/cleanup')
def execute_cleanup(request: Request,item: CleanupSelection):
    require_management(request)
    with _video_submit_lock,_image_lock:
        with db() as con:
            con.execute('BEGIN IMMEDIATE')
            plan=cleanup_plan(con,item)
            if not hmac.compare_digest(item.confirmation,plan['confirmation']):raise HTTPException(409,'清理范围已变化，请重新预览后确认')
            for row in plan['images']:
                con.execute("UPDATE clues SET analysis_id=NULL,notes=notes||? WHERE analysis_id=?",('\n关联影像已由管理者清理，原影像编号：'+row['id'],row['id']))
                for table in ('detections','reviews'):con.execute(f'DELETE FROM {table} WHERE analysis_id=?',(row['id'],))
                con.execute('DELETE FROM analyses WHERE id=?',(row['id'],))
            for row in plan['videos']:
                # Reclaim files before deleting the only directory reference.
                remove_video_files(row['id'])
                con.execute('DELETE FROM videos WHERE id=?',(row['id'],))
            event(con,item.task_id,f"管理清理 · {len(plan['images'])} 张影像、{len(plan['videos'])} 条失效视频；保留任务与线索")
    return dict(images_deleted=len(plan['images']),videos_deleted=len(plan['videos']),storage=storage_summary())

def demo_video_samples():
    directory=STORE/'demo-videos'
    manifest=directory/'manifest.json'
    if not manifest.is_file():return []
    items=json.loads(manifest.read_text(encoding='utf-8'))
    return [item for item in items if Path(item['file']).name==item['file'] and (directory/item['file']).is_file()]

@app.get('/video-samples')
def video_samples():
    fields=('id','label','purpose','seconds','width','height','bytes','source','provenance','sha256')
    return [{key:item[key] for key in fields} for item in demo_video_samples()]

@app.get('/video-samples/{ident}/media')
def video_sample_media(ident: str):
    item=next((item for item in demo_video_samples() if item['id']==ident),None)
    if item is None:raise HTTPException(404,'演示素材不存在')
    return FileResponse(STORE/'demo-videos'/item['file'],media_type='video/mp4')

def video_worker(ident):
    import cv2
    import math
    import subprocess
    import imageio_ffmpeg
    from algorithms.detector import detect
    directory=video_dir(ident)
    capture=None
    writer=None
    try:
        with db() as con:
            row=dict(require(con,'videos',ident))
            if row['status']=='cancelled':return
            con.execute("UPDATE videos SET status='running' WHERE id=?",(ident,))
        capture=cv2.VideoCapture(str(directory/'input.mp4'))
        fps=capture.get(cv2.CAP_PROP_FPS)
        frames=capture.get(cv2.CAP_PROP_FRAME_COUNT)
        width=capture.get(cv2.CAP_PROP_FRAME_WIDTH)
        height=capture.get(cv2.CAP_PROP_FRAME_HEIGHT)
        if not capture.isOpened() or not all(math.isfinite(v) and v>0 for v in (fps,frames,width,height)):
            raise ValueError('视频无法解码或时长信息无效')
        duration=frames/fps
        if duration>30.1 or width*height>1920*1080:
            raise ValueError('仅支持 30 秒以内、最高 1920×1080 的短视频')
        scale=min(1.,960/max(width,height))
        w=max(2,int(width*scale)//2*2);h=max(2,int(height*scale)//2*2)
        rate=min(fps,row['sample_fps'])
        count=max(1,math.ceil(duration*rate))
        writer=cv2.VideoWriter(str(directory/'sampled.mp4'),cv2.VideoWriter_fourcc(*'mp4v'),rate,(w,h))
        if not writer.isOpened():raise ValueError('无法创建输出视频')
        records=[]
        for i in range(count):
            with db() as con:
                if require(con,'videos',ident)['status']=='cancelled':return
            timestamp=i/rate
            capture.set(cv2.CAP_PROP_POS_MSEC,timestamp*1000)
            ok,frame=capture.read()
            if not ok:break
            frame=cv2.resize(frame,(w,h))
            annotated,predictions=detect(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB),row['confidence'])
            writer.write(cv2.cvtColor(np.asarray(annotated),cv2.COLOR_RGB2BGR))
            keyframe=f'frame-{i:04d}.jpg'
            annotated.save(directory/keyframe,quality=90)
            records.append(dict(index=i,time=round(timestamp,3),predictions=predictions,keyframe=keyframe))
            with db() as con:
                con.execute('UPDATE videos SET progress=? WHERE id=?',(.9*(i+1)/count,ident))
        writer.release();writer=None
        if not records:raise ValueError('没有可读取的视频帧')
        # H.264/yuv420p with faststart for browser playback. Sampled result intentionally has no audio.
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-y','-i',str(directory/'sampled.mp4'),'-an','-c:v','libx264','-pix_fmt','yuv420p','-movflags','+faststart',str(directory/'result.mp4')],check=True,capture_output=True,timeout=60)
        (directory/'records.json').write_text(json.dumps(dict(duration=duration,sample_fps=rate,width=w,height=h,frames=records,tracking=False),ensure_ascii=False),encoding='utf-8')
        with db() as con:
            if require(con,'videos',ident)['status']=='cancelled':return
            con.execute("UPDATE videos SET status='completed',progress=1 WHERE id=?",(ident,))
            event(con,row['task_id'],f"视频检测完成 · {row['name']} · {len(records)} 个抽样帧")
    except Exception:
        logger.exception('Video processing failed for %s',ident)
        with db() as con:
            con.execute("UPDATE videos SET status='failed',error=? WHERE id=? AND status!='cancelled'",('视频处理失败，请检查片长、格式后重新提交',ident))
    finally:
        if capture is not None:capture.release()
        if writer is not None:writer.release()
        with db() as con:
            row=con.execute('SELECT status FROM videos WHERE id=?',(ident,)).fetchone()
        if row and row['status'] in ('failed','cancelled'):
            remove_video_files(ident)
        elif row and row['status']=='completed':
            (directory/'sampled.mp4').unlink(missing_ok=True)

@app.post('/videos')
async def submit_video(request: Request,task_id: str,name: str=Query(min_length=1,max_length=200),confidence: float=Query(.25,ge=.05,le=.95),sample_fps: float=Query(1,ge=.5,le=2)):
    if not name.strip():raise HTTPException(422,'视频名称不能为空')
    ensure_storage(64*1024*1024)
    with db() as con:require(con,'tasks',task_id)
    content=bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content)>12*1024*1024:raise HTTPException(413,'视频超过 12 MB')
    if not content:raise HTTPException(422,'视频不能为空')
    with _video_submit_lock:
        if _image_lock.locked():raise HTTPException(409,'图片正在分析，请完成后再提交视频')
        with db() as con:
            pending=con.execute("SELECT COUNT(*) FROM videos WHERE status IN ('queued','running')").fetchone()[0]
            if pending>=3:raise HTTPException(429,'队列已满，请等待现有任务完成')
            ident=uuid.uuid4().hex
            directory=video_dir(ident);directory.mkdir(parents=True)
            (directory/'input.mp4').write_bytes(content)
            con.execute('INSERT INTO videos VALUES(?,?,?,?,?,?,?,?,?)',(ident,task_id,name,'queued',0,'',confidence,sample_fps,now()))
            event(con,task_id,f'提交视频检测 · {name}')
        for finished in list(_video_jobs):
            if _video_jobs[finished].done():del _video_jobs[finished]
        _video_jobs[ident]=_video_executor.submit(video_worker,ident)
    return {'id':ident}

@app.get('/videos')
def list_videos(task_id: str):
    with db() as con:
        return [dict(r) for r in con.execute('SELECT * FROM videos WHERE task_id=? ORDER BY rowid DESC',(task_id,))]

@app.get('/videos/{ident}')
def get_video(ident: str):
    with db() as con:
        row=dict(require(con,'videos',ident))
        if row['status']=='queued':
            pending=[r[0] for r in con.execute("SELECT id FROM videos WHERE status IN ('queued','running') ORDER BY rowid")]
            row['ahead']=pending.index(ident) if ident in pending else 0
    if row['status']=='completed':
        try:
            row['results']=json.loads((video_dir(ident)/'records.json').read_text(encoding='utf-8'))
            if not isinstance(row['results'],dict) or not isinstance(row['results'].get('frames'),list) or not row['results']['frames']:
                raise ValueError('Invalid video records')
        except (OSError,ValueError):
            with db() as con:
                con.execute("UPDATE videos SET status='failed',error=? WHERE id=?",('检测结果文件缺失或损坏，请重新提交视频',ident))
            row.update(status='failed',error='检测结果文件缺失或损坏，请重新提交视频')
    return row

@app.post('/videos/{ident}/cancel')
def cancel_video(ident: str):
    with db() as con:
        row=require(con,'videos',ident)
        if row['status'] in ('queued','running'):
            con.execute("UPDATE videos SET status='cancelled' WHERE id=?",(ident,))
            event(con,row['task_id'],f"取消视频检测 · {row['name']}")
    return {'status':'ok'}

@app.get('/videos/{ident}/media/{kind}')
def video_media(ident: str,kind: str,download: bool=False):
    with db() as con:row=require(con,'videos',ident)
    if row['status']!='completed':raise HTTPException(409,'结果尚未完成')
    names={'result':'result.mp4','original':'input.mp4','records':'records.json'}
    if kind not in names:raise HTTPException(404,'文件不存在')
    path=video_dir(ident)/names[kind]
    if not path.is_file():raise HTTPException(410,'视频文件已不存在，请重新提交')
    return FileResponse(path,media_type='application/json' if kind=='records' else 'video/mp4',filename=names[kind] if download else None)

@app.get('/videos/{ident}/frames/{index}')
def video_frame(ident: str,index: int):
    row=get_video(ident)
    frames=row.get('results',{}).get('frames',[])
    if index<0 or index>=len(frames):raise HTTPException(404,'关键帧不存在')
    path=video_dir(ident)/frames[index]['keyframe']
    if not path.is_file():raise HTTPException(410,'关键帧文件已不存在，请重新提交')
    return FileResponse(path,media_type='image/jpeg')

class VideoClue(BaseModel):
    frame_index: int = Field(ge=0)
    title: str = Field(min_length=1,max_length=100)
    notes: str = Field(default='',max_length=2000)

@app.post('/videos/{ident}/clues')
def add_video_clue(ident: str,item: VideoClue):
    row=get_video(ident)
    frames=row.get('results',{}).get('frames',[])
    if item.frame_index>=len(frames) or not item.title.strip():
        raise HTTPException(422,'关键帧不存在或标题为空')
    ident_clue=uuid.uuid4().hex
    frame=frames[item.frame_index]
    notes=f"视频：{row['name']}；时间点：{frame['time']:.1f}s；模型预测待人工核实。\n{item.notes}"
    with db() as con:
        con.execute('INSERT INTO clues VALUES(?,?,?,?,?,?,?,?,?,?)',(ident_clue,row['task_id'],None,item.title.strip(),'待核实','',notes,None,None,now()))
        con.execute('INSERT INTO video_clues VALUES(?,?,?,?)',(ident_clue,ident,item.frame_index,frame['time']))
        event(con,row['task_id'],f'提交视频线索 · {item.title}')
    return {'id':ident_clue}

@app.get("/clues")
def clues(task_id: str):
    with db() as con:
        return [dict(r) for r in con.execute("SELECT c.*,v.video_id,v.frame_index,v.time AS video_time FROM clues c LEFT JOIN video_clues v ON c.id=v.clue_id WHERE c.task_id=? ORDER BY c.rowid DESC",(task_id,))]

@app.post("/clues")
def add_clue(item: Clue):
    if not item.title.strip() or ((item.lat is None)!=(item.lon is None)):
        raise HTTPException(422,"标题必填，经纬度需同时提供")
    ident=uuid.uuid4().hex
    with db() as con:
        require(con,"tasks",item.task_id)
        if item.analysis_id and require(con,"analyses",item.analysis_id)["task_id"]!=item.task_id:
            raise HTTPException(422,"影像不属于当前任务")
        if item.analysis_id:
            review=con.execute('SELECT decision FROM reviews WHERE analysis_id=?',(item.analysis_id,)).fetchone()
            if review and review['decision']=='ignored':raise HTTPException(409,'该影像结果已忽略，请先重新确认目标')
        con.execute("INSERT INTO clues VALUES(?,?,?,?,?,?,?,?,?,?)",(ident,item.task_id,item.analysis_id,item.title.strip(),"待核实","",item.notes,item.lat,item.lon,now()))
        event(con,item.task_id,f"提交线索 · {item.title}")
    return {"id":ident}

@app.patch("/clues/{ident}")
def update_clue(ident: str,item: Update):
    if item.status not in STATUSES:
        raise HTTPException(422,"状态无效")
    if item.status=="处理中" and not item.assignee.strip():
        raise HTTPException(422,"处理中线索需要负责人")
    with db() as con:
        con.execute('BEGIN IMMEDIATE')
        row=require(con,"clues",ident)
        payload=json.dumps(dict(status=item.status,assignee=item.assignee.strip(),feedback=item.feedback),sort_keys=True,ensure_ascii=False)
        if item.request_id:
            previous=con.execute('SELECT payload FROM feedback_requests WHERE clue_id=? AND request_id=?',(ident,item.request_id)).fetchone()
            if previous:
                if previous['payload']!=payload:raise HTTPException(409,'重复提交标识与内容不一致，请刷新后重试')
                return {'status':'ok','duplicate':True}
        suffix=f' · {item.feedback}'
        if row['status']==item.status and row['assignee']==item.assignee.strip() and (not item.feedback or row['notes'].split('\n')[-1].endswith(suffix)):
            if item.request_id:con.execute('INSERT INTO feedback_requests VALUES(?,?,?)',(ident,item.request_id,payload))
            return {'status':'ok','duplicate':True}
        notes=row["notes"]+(f"\n{now()} · {item.feedback}" if item.feedback else "")
        if len(notes)>20000:raise HTTPException(422,'历史备注已达容量上限，请先导出报告并新建线索')
        if item.request_id:con.execute('INSERT INTO feedback_requests VALUES(?,?,?)',(ident,item.request_id,payload))
        con.execute("UPDATE clues SET status=?,assignee=?,notes=? WHERE id=?",(item.status,item.assignee.strip(),notes,ident))
        event(con,row["task_id"],f"{row['title']} → {item.status} · {item.assignee or '未分派'} · {item.feedback}")
    return {"status":"ok"}

@app.get("/report/{task_id}")
def report(task_id: str):
    with db() as con:
        task=dict(require(con,"tasks",task_id))
        items=[dict(r) for r in con.execute("SELECT c.*,v.video_id,v.frame_index,v.time AS video_time FROM clues c LEFT JOIN video_clues v ON c.id=v.clue_id WHERE c.task_id=?",(task_id,))]
        events=[dict(r) for r in con.execute("SELECT * FROM events WHERE task_id=? ORDER BY id DESC",(task_id,))]
    return {"task":task,"clues":items,"events":events,"exported":now()}
