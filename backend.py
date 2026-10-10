"""Local-only API. One business store; later endpoints can use this same API."""
import base64
import io
import json
import os
import hmac
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

from algorithms.enhancement import enhance as light_enhance
from algorithms.dehazing import enhance as dehaze

ROOT = Path(__file__).resolve().parent
STORE = Path(os.environ.get("HAIXUN_DATA_DIR", ROOT / "data"))
STORE.mkdir(parents=True, exist_ok=True)
app = FastAPI(title="海寻本地业务 API", version="0.2.0")
API_MODE=os.environ.get('SEASEEK_API_MODE','local')
API_TOKEN=os.environ.get('HAIXUN_API_TOKEN','')
if API_MODE=='remote' and not API_TOKEN:
    raise RuntimeError('Remote API requires HAIXUN_API_TOKEN.')

@app.middleware('http')
async def service_access(request,call_next):
    if API_TOKEN and request.url.path!='/health':
        supplied=request.headers.get('Authorization','')
        if not hmac.compare_digest(supplied.encode(),('Bearer '+API_TOKEN).encode()):
            return JSONResponse(status_code=401,content={'detail':'服务访问未授权'})
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

@app.get("/health")
def health():
    return {"status": "ok", "mode": "shared backend" if API_MODE=='remote' else "local prototype", "version": "0.2.0"}

@app.get("/tasks")
def tasks():
    with db() as con:
        return [dict(r) for r in con.execute("SELECT * FROM tasks ORDER BY created DESC,rowid DESC")]

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

def png(image):
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()

@app.post("/analyses")
def analyze(item: Analysis):
    methods = {"original","adaptive","gamma_light","gamma_dark","clahe","dehaze_mild","dehaze_mix","dehaze_adaptive"}
    if item.method not in methods:
        raise HTTPException(422,"不支持的增强方法")
    with db() as con:
        require(con,"tasks",item.task_id)
    try:
        raw = base64.b64decode(item.image, validate=True)
        if len(raw)>12*1024*1024:
            raise ValueError("文件超过 12 MB")
        with Image.open(io.BytesIO(raw)) as source:
            if source.width*source.height>24_000_000:
                raise ValueError("图片像素超过 2400 万")
            image = ImageOps.exif_transpose(source).convert("RGB")
        image.thumbnail((1600,1600))
    except (ValueError,UnidentifiedImageError,OSError,Image.DecompressionBombError) as exc:
        raise HTTPException(422, "图片无法读取或尺寸超过限制") from exc
    rgb = np.asarray(image)
    output, info = (dehaze if item.method.startswith("dehaze") else light_enhance)(rgb,item.method)
    ident = uuid.uuid4().hex
    with db() as con:
        con.execute("INSERT INTO analyses VALUES(?,?,?,?,?,?,?,?,?,?)", (ident,item.task_id,item.name,item.method,info["selected"],png(image),png(Image.fromarray(output)),image.width,image.height,now()))
        event(con,item.task_id,f"完成影像分析 · {item.name}")
    return {"id":ident,"selected":info["selected"],"width":image.width,"height":image.height}

@app.get("/analyses")
def analyses(task_id: str):
    with db() as con:
        return [dict(r) for r in con.execute("SELECT id,name,method,selected,width,height,created FROM analyses WHERE task_id=? ORDER BY rowid DESC",(task_id,))]

@app.get("/analyses/{ident}")
def analysis(ident: str):
    with db() as con:
        row = dict(require(con,"analyses",ident))
        detection=con.execute("SELECT * FROM detections WHERE analysis_id=?",(ident,)).fetchone()
    row['detection']=None
    if detection:
        row['detection']={"image":base64.b64encode(detection['image']).decode(),"predictions":json.loads(detection['predictions']),"confidence":detection['confidence'],"source":detection['source'],"created":detection['created']}
    for field in ("original","result"):
        row[field] = base64.b64encode(row[field]).decode()
    return row

class DetectSettings(BaseModel):
    confidence: float = Field(default=.25,ge=.05,le=.95)
    source: str = 'original'

@app.post('/analyses/{ident}/detect')
def detect_image(ident: str,settings: DetectSettings):
    if settings.source not in ('original','result'):
        raise HTTPException(422,'检测输入无效')
    with db() as con:
        row=dict(require(con,'analyses',ident))
    from algorithms.detector import detect
    try:
        image=Image.open(io.BytesIO(row[settings.source])).convert('RGB')
        annotated,predictions=detect(np.asarray(image),settings.confidence)
    except Exception as exc:
        raise HTTPException(503,f'检测失败：{exc}') from exc
    with db() as con:
        con.execute('INSERT OR REPLACE INTO detections VALUES(?,?,?,?,?,?)',(ident,png(annotated),json.dumps(predictions,ensure_ascii=False),settings.confidence,settings.source,now()))
        event(con,row['task_id'],f"船舶检测 · {row['name']} · {len(predictions)} 个目标 · {'原图' if settings.source=='original' else '增强图'}")
    return {'count':len(predictions),'predictions':predictions}

_video_executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='haixun-video')
_video_submit_lock=threading.Lock()

def video_dir(ident):
    return STORE/'videos'/ident

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
    except Exception as exc:
        with db() as con:
            con.execute("UPDATE videos SET status='failed',error=? WHERE id=? AND status!='cancelled'",(str(exc)[:500],ident))
    finally:
        if capture is not None:capture.release()
        if writer is not None:writer.release()

@app.post('/videos')
async def submit_video(request: Request,task_id: str,name: str=Query(max_length=200),confidence: float=Query(.25,ge=.05,le=.95),sample_fps: float=Query(1,ge=.5,le=2)):
    with db() as con:require(con,'tasks',task_id)
    content=bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content)>12*1024*1024:raise HTTPException(413,'视频超过 12 MB')
    if not content:raise HTTPException(422,'视频不能为空')
    with _video_submit_lock:
        with db() as con:
            pending=con.execute("SELECT COUNT(*) FROM videos WHERE status IN ('queued','running')").fetchone()[0]
            if pending>=3:raise HTTPException(429,'队列已满，请等待现有任务完成')
            ident=uuid.uuid4().hex
            directory=video_dir(ident);directory.mkdir(parents=True)
            (directory/'input.mp4').write_bytes(content)
            con.execute('INSERT INTO videos VALUES(?,?,?,?,?,?,?,?,?)',(ident,task_id,name,'queued',0,'',confidence,sample_fps,now()))
            event(con,task_id,f'提交视频检测 · {name}')
        _video_executor.submit(video_worker,ident)
    return {'id':ident}

@app.get('/videos')
def list_videos(task_id: str):
    with db() as con:
        return [dict(r) for r in con.execute('SELECT * FROM videos WHERE task_id=? ORDER BY rowid DESC',(task_id,))]

@app.get('/videos/{ident}')
def get_video(ident: str):
    with db() as con:row=dict(require(con,'videos',ident))
    if row['status']=='completed':
        row['results']=json.loads((video_dir(ident)/'records.json').read_text(encoding='utf-8'))
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
    return FileResponse(video_dir(ident)/names[kind],media_type='application/json' if kind=='records' else 'video/mp4',filename=names[kind] if download else None)

@app.get('/videos/{ident}/frames/{index}')
def video_frame(ident: str,index: int):
    row=get_video(ident)
    frames=row.get('results',{}).get('frames',[])
    if index<0 or index>=len(frames):raise HTTPException(404,'关键帧不存在')
    return FileResponse(video_dir(ident)/frames[index]['keyframe'],media_type='image/jpeg')

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
        row=require(con,"clues",ident)
        notes=row["notes"]+(f"\n{now()} · {item.feedback}" if item.feedback else "")
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
