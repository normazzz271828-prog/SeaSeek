"""Contracts for media size, old records, demo isolation and public-demo limits."""
import base64
import io
import unittest
import tempfile
import os
from unittest.mock import patch
from PIL import Image
from fastapi.testclient import TestClient
# Running this file alone must never import the backend against the real store.
TEMP=tempfile.TemporaryDirectory()
os.environ['HAIXUN_DATA_DIR']=TEMP.name
import backend


class DemoV2(unittest.TestCase):
    def setUp(self):
        backend._quota.clear()
        self.client=TestClient(backend.app)
        self.task=self.client.post('/tasks',json=dict(name='二版验证',area='模拟海域',owner='测试员')).json()['id']

    def image(self,task=None):
        buf=io.BytesIO()
        Image.effect_noise((1600,1000),40).convert('RGB').save(buf,format='JPEG',quality=85)
        response=self.client.post('/analyses',json=dict(task_id=task or self.task,name='phone.jpg',method='original',image=base64.b64encode(buf.getvalue()).decode()))
        self.assertEqual(response.status_code,200,response.text)
        return response.json()['id']

    def test_metadata_small_media_and_original_alias(self):
        ident=self.image()
        metadata=self.client.get('/analyses/'+ident)
        self.assertLess(len(metadata.content),2000)
        self.assertNotIn('original',metadata.json())
        self.assertTrue(metadata.json()['result_is_original'])
        with backend.db() as con:
            row=backend.require(con,'analyses',ident)
            self.assertIsNone(row['result'])
            # Legacy rows with independently stored results must remain readable.
            con.execute('UPDATE analyses SET result=original WHERE id=?',(ident,))
        preview=self.client.get(f'/analyses/{ident}/media/result')
        self.assertEqual(preview.headers['content-type'],'image/jpeg')
        self.assertLess(len(preview.content),600_000)
        self.assertEqual(Image.open(io.BytesIO(preview.content)).width,1280)
        self.assertEqual(self.client.get(f'/analyses/{ident}/media/result?size=full').content,self.client.get(f'/analyses/{ident}/media/original?size=full').content)
        self.assertEqual(self.client.get(f'/analyses/{ident}/media/bad').status_code,404)

    def test_review_persists_and_validates(self):
        ident=self.image()
        self.assertEqual(self.client.post(f'/analyses/{ident}/review',json={'decision':'ignored'}).status_code,200)
        self.assertEqual(TestClient(backend.app).get('/analyses/'+ident).json()['review']['decision'],'ignored')
        self.assertEqual(self.client.post(f'/analyses/{ident}/review',json={'decision':'bad'}).status_code,422)
        self.assertEqual(self.client.post('/clues',json=dict(task_id=self.task,analysis_id=ident,title='已忽略')).status_code,409)

    def test_binary_upload_and_size_limit(self):
        buf=io.BytesIO();Image.new('RGB',(120,80),(10,20,30)).save(buf,format='JPEG')
        response=self.client.post('/analyses/upload',params=dict(task_id=self.task,name='camera.jpg',method='original'),content=buf.getvalue())
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['width'],120)
        self.assertEqual(self.client.post('/analyses/upload',params=dict(task_id=self.task,name='too-large.jpg'),content=b'x'*(12*1024*1024+1)).status_code,413)

    def test_reset_is_scoped_and_requires_remote_management_code(self):
        self.client.post('/demo')
        ident=self.image('demo-coastal')
        preserved=self.image()
        self.client.post('/clues',json=dict(task_id='demo-coastal',analysis_id=ident,title='测试线索'))
        with patch.object(backend,'API_MODE','remote'),patch.object(backend,'RESET_TOKEN','private-code'):
            self.assertEqual(self.client.post('/demo/reset').status_code,403)
            reset=self.client.post('/demo/reset',headers={'X-Seaseek-Reset':'private-code'})
            self.assertEqual(reset.status_code,200,reset.text)
        self.assertEqual(self.client.get('/analyses/'+ident).status_code,404)
        self.assertEqual(self.client.get('/analyses/'+preserved).status_code,200)
        self.assertEqual(len(self.client.get('/clues',params={'task_id':'demo-coastal'}).json()),3)

    def test_quota_and_busy_image_do_not_run(self):
        with patch.object(backend,'_quota',{'image-global':backend.deque([backend.time.monotonic()]*100)}):
            self.assertEqual(self.client.post('/analyses',json={}).status_code,429)
        backend._image_lock.acquire()
        try:
            response=self.client.post('/analyses',json=dict(task_id=self.task,name='bad',image='bad',method='original'))
            self.assertEqual(response.status_code,429)
        finally:backend._image_lock.release()


if __name__=='__main__':unittest.main()
