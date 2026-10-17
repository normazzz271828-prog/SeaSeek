import base64
import io
import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from fastapi.testclient import TestClient

TEMP=tempfile.TemporaryDirectory()
os.environ['HAIXUN_DATA_DIR']=TEMP.name
import backend


class Stability(unittest.TestCase):
    def setUp(self):
        backend._quota.clear()
        self.client=TestClient(backend.app)
        self.task=self.client.post('/tasks',json=dict(name='稳定性回归',area='模拟',owner='测试')).json()['id']

    def image(self):
        buf=io.BytesIO();Image.new('RGB',(80,60),'navy').save(buf,format='JPEG')
        r=self.client.post('/analyses/upload',params=dict(task_id=self.task,name='sample.jpg'),content=buf.getvalue())
        self.assertEqual(r.status_code,200,r.text)
        return r.json()['id']

    def test_analysis_exhaustion_does_not_block_feedback_and_expires(self):
        clue=self.client.post('/clues',json=dict(task_id=self.task,title='线索')).json()['id']
        tick=backend.time.monotonic()
        with patch.object(backend,'_quota',{'global':backend.deque([tick]*240)}):
            r=self.client.post('/analyses',json={})
            self.assertEqual(r.status_code,429)
            self.assertIn('Retry-After',r.headers)
            self.assertEqual(self.client.patch('/clues/'+clue,json=dict(status='已完成',feedback='完成')).status_code,200)
            self.assertEqual(self.client.get('/report/'+self.task).status_code,200)
        with patch.object(backend,'_quota',{'global':backend.deque([tick-3601]*240)}):
            self.image()

    def test_bad_lengths_and_disk_reserve(self):
        for length in ('abc','-1'):
            self.assertEqual(self.client.post('/tasks',headers={'Content-Length':length},json={}).status_code,400)
        with patch.object(backend.shutil,'disk_usage',return_value=type('Disk',(),{'free':1})()):
            r=self.client.post('/videos',params=dict(task_id=self.task,name='clip.mp4'),content=b'x')
            self.assertEqual(r.status_code,507)

    def test_cleanup_preview_scope_and_linked_record_preservation(self):
        ident=self.image()
        clue=self.client.post('/clues',json=dict(task_id=self.task,title='保留线索',analysis_id=ident)).json()['id']
        other=self.client.post('/tasks',json=dict(name='其他任务',area='模拟',owner='测试')).json()['id']
        selection=dict(task_id=self.task)
        with patch.object(backend,'API_MODE','remote'),patch.object(backend,'RESET_TOKEN','code'):
            self.assertEqual(self.client.post('/admin/cleanup/preview',json=selection).status_code,403)
            headers={'X-Seaseek-Reset':'code'}
            plan=self.client.post('/admin/cleanup/preview',json=selection,headers=headers).json()
            self.assertEqual(plan['images'],[])
            selection['include_linked']=True
            plan=self.client.post('/admin/cleanup/preview',json=selection,headers=headers).json()
            self.assertEqual(plan['linked_clues'],1)
            self.assertEqual(self.client.post('/admin/cleanup',json=dict(**selection,confirmation='stale'),headers=headers).status_code,409)
            r=self.client.post('/admin/cleanup',json=dict(**selection,confirmation=plan['confirmation']),headers=headers)
            self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.client.get('/analyses/'+ident).status_code,404)
        row=next(r for r in self.client.get('/clues',params=dict(task_id=self.task)).json() if r['id']==clue)
        self.assertIsNone(row['analysis_id'])
        self.assertIn('关联影像已由管理者清理',row['notes'])
        self.assertEqual(self.client.get('/report/'+other).status_code,200)

    def test_cleanup_releases_full_global_row_limit(self):
        with backend.db() as con:
            count=con.execute('SELECT COUNT(*) FROM analyses').fetchone()[0]
            for index in range(500-count):
                con.execute('INSERT INTO analyses VALUES(?,?,?,?,?,?,?,?,?,?)',(uuid.uuid4().hex,self.task,'filler','original','original',b'x',None,1,1,backend.now()))
        r=self.client.post('/analyses',json=dict(task_id=self.task,name='full',method='original',image=base64.b64encode(self._png()).decode()))
        self.assertEqual(r.status_code,429)
        plan=self.client.post('/admin/cleanup/preview',json=dict(task_id=self.task)).json()
        self.assertEqual(self.client.post('/admin/cleanup',json=dict(task_id=self.task,confirmation=plan['confirmation'])).status_code,200)
        self.image()

    def _png(self):
        b=io.BytesIO();Image.new('RGB',(8,8)).save(b,format='PNG');return b.getvalue()

    def test_feedback_is_idempotent_and_payload_conflicts_rejected(self):
        ident=self.client.post('/clues',json=dict(task_id=self.task,title='反馈')).json()['id']
        payload=dict(status='已完成',feedback='船舶已联系',request_id='first')
        for _ in range(3):self.assertEqual(self.client.patch('/clues/'+ident,json=payload).status_code,200)
        row=next(r for r in self.client.get('/clues',params=dict(task_id=self.task)).json() if r['id']==ident)
        self.assertEqual(row['notes'].count('船舶已联系'),1)
        self.assertEqual(self.client.patch('/clues/'+ident,json=dict(payload,feedback='不同内容')).status_code,409)

    def test_missing_video_files_and_empty_names(self):
        self.assertEqual(self.client.post('/videos',params=dict(task_id=self.task,name=''),content=b'x').status_code,422)
        ident=uuid.uuid4().hex
        with backend.db() as con:con.execute('INSERT INTO videos VALUES(?,?,?,?,?,?,?,?,?)',(ident,self.task,'missing','completed',1,'',.25,.5,backend.now()))
        self.assertEqual(self.client.get('/videos/'+ident+'/media/result').status_code,410)
        r=self.client.get('/videos/'+ident)
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.json()['status'],'failed')

    def test_failed_video_worker_reclaims_files_and_hides_details(self):
        ident=uuid.uuid4().hex
        directory=backend.video_dir(ident);directory.mkdir(parents=True)
        (directory/'input.mp4').write_bytes(b'not a video')
        with backend.db() as con:con.execute('INSERT INTO videos VALUES(?,?,?,?,?,?,?,?,?)',(ident,self.task,'bad','queued',0,'',.25,.5,backend.now()))
        backend.video_worker(ident)
        self.assertFalse(directory.exists())
        row=self.client.get('/videos/'+ident).json()
        self.assertEqual(row['status'],'failed')
        self.assertNotIn(str(backend.STORE),row['error'])
