import base64
import io
import os
import tempfile
import unittest
import time
from unittest.mock import patch
from pathlib import Path

TEMP = tempfile.TemporaryDirectory()
os.environ['HAIXUN_DATA_DIR'] = TEMP.name
from fastapi.testclient import TestClient
from PIL import Image
from backend import app

class LocalFlow(unittest.TestCase):
    def test_detection_persistence_and_validation(self):
        client=TestClient(app)
        task=client.post('/tasks',json=dict(name='检测验证',area='近海',owner='测试员')).json()['id']
        buf=io.BytesIO();Image.new('RGB',(80,50),(20,40,60)).save(buf,format='PNG')
        ident=client.post('/analyses',json=dict(task_id=task,name='test.png',method='gamma_light',image=base64.b64encode(buf.getvalue()).decode())).json()['id']
        expected=[dict(class_id=3,category='渔船',score=.8,points=[[10,10],[30,10],[30,20],[10,20]])]
        def fake_detect(rgb,confidence):
            self.assertEqual(tuple(rgb[0,0]),(20,40,60))
            return Image.fromarray(rgb),expected
        with patch('algorithms.detector.detect',side_effect=fake_detect):
            response=client.post(f'/analyses/{ident}/detect',json={'confidence':.25})
        self.assertEqual(response.status_code,200,response.text)
        stored=TestClient(app).get(f'/analyses/{ident}').json()['detection']
        self.assertEqual(stored['predictions'],expected)
        self.assertEqual(stored['source'],'original')
        self.assertEqual(client.post(f'/analyses/{ident}/detect',json={'confidence':0}).status_code,422)
        self.assertEqual(client.post(f'/analyses/{ident}/detect',json={'source':'invalid'}).status_code,422)

    def test_video_results_and_lineage(self):
        client=TestClient(app)
        task=client.post('/tasks',json=dict(name='视频验证',area='近海',owner='测试员')).json()['id']
        content=(Path(__file__).resolve().parents[1]/'assets/demo_ships.mp4').read_bytes()
        with patch('algorithms.detector.detect',side_effect=lambda rgb,confidence:(Image.fromarray(rgb),[])):
            response=client.post('/videos',params=dict(task_id=task,name='demo.mp4',sample_fps=.5),content=content)
            self.assertEqual(response.status_code,200,response.text)
            ident=response.json()['id']
            for _ in range(100):
                result=client.get('/videos/'+ident).json()
                if result['status'] not in ('queued','running'):break
                time.sleep(.05)
        self.assertEqual(result['status'],'completed',result)
        self.assertEqual(len(result['results']['frames']),4)
        self.assertEqual(client.get(f'/videos/{ident}/media/result').status_code,200)
        self.assertEqual(client.get(f'/videos/{ident}/frames/99').status_code,404)
        clue=client.post(f'/videos/{ident}/clues',json=dict(frame_index=1,title='视频线索')).json()['id']
        stored=client.get('/clues',params={'task_id':task}).json()[0]
        self.assertEqual(stored['id'],clue)
        self.assertEqual(stored['video_id'],ident)
        self.assertEqual(stored['video_time'],2)
        self.assertEqual(client.post(f'/videos/{ident}/clues',json=dict(frame_index=99,title='错误')).status_code,422)
        self.assertEqual(client.post('/videos',params=dict(task_id=task,name='empty.mp4'),content=b'').status_code,422)

    def test_task_image_clue_and_report(self):
        client=TestClient(app)
        task=client.post('/tasks',json=dict(name='验证任务',area='近海',owner='测试员')).json()['id']
        buf=io.BytesIO();Image.new('RGB',(100,60),(70,110,130)).save(buf,format='PNG')
        response=client.post('/analyses',json=dict(task_id=task,name='test.png',method='dehaze_mix',image=base64.b64encode(buf.getvalue()).decode()))
        self.assertEqual(response.status_code,200,response.text)
        analysis=response.json()['id']
        self.assertEqual(client.get('/analyses/'+analysis).json()['width'],100)
        clue=client.post('/clues',json=dict(task_id=task,analysis_id=analysis,title='人工船舶线索')).json()['id']
        self.assertEqual(client.patch('/clues/'+clue,json=dict(status='处理中',assignee='')).status_code,422)
        self.assertEqual(client.patch('/clues/'+clue,json=dict(status='已完成',assignee='处置员',feedback='已核实')).status_code,200)
        report=TestClient(app).get('/report/'+task).json()
        self.assertEqual(report['clues'][0]['status'],'已完成')
        self.assertIn('已核实',report['clues'][0]['notes'])
        self.assertEqual(len(report['events']),4)
        other=client.post('/tasks',json=dict(name='其他任务',area='其他',owner='其他')).json()['id']
        self.assertEqual(client.post('/clues',json=dict(task_id=other,analysis_id=analysis,title='跨任务')).status_code,422)
        self.assertEqual(client.post('/clues',json=dict(task_id=task,title='错误坐标',lat=20)).status_code,422)
        self.assertEqual(client.post('/analyses',json=dict(task_id=task,name='bad',method='adaptive',image='broken')).status_code,422)

    def test_demo_idempotent(self):
        client=TestClient(app)
        client.post('/demo');client.post('/demo')
        self.assertEqual(len(client.get('/clues',params={'task_id':'demo-coastal'}).json()),3)

if __name__=='__main__':
    unittest.main()
