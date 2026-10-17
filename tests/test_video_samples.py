import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import os

TEMP=tempfile.TemporaryDirectory()
os.environ['HAIXUN_DATA_DIR']=TEMP.name
import backend
from fastapi.testclient import TestClient


class VideoSamples(unittest.TestCase):
    def test_catalog_and_media_are_protected_and_do_not_leak_paths(self):
        with tempfile.TemporaryDirectory() as store,patch.object(backend,'STORE',Path(store)),patch.object(backend,'API_TOKEN','test-token'):
            directory=Path(store)/'demo-videos';directory.mkdir()
            (directory/'clip.mp4').write_bytes(b'mp4-test-fixture')
            item=dict(id='small-boat',file='clip.mp4',label='小船',purpose='测试',seconds=8,width=960,height=540,bytes=16,source='用户素材.mp4',provenance='用户提供',sha256='fixture')
            (directory/'manifest.json').write_text(json.dumps([item]),encoding='utf-8')
            client=TestClient(backend.app)
            self.assertEqual(client.get('/video-samples').status_code,401)
            self.assertEqual(client.get('/video-samples/small-boat/media').status_code,401)
            headers={'Authorization':'Bearer test-token'}
            listing=client.get('/video-samples',headers=headers)
            self.assertEqual(listing.status_code,200)
            self.assertNotIn('file',listing.json()[0])
            self.assertNotIn(store,listing.text)
            self.assertEqual(client.get('/video-samples/small-boat/media',headers=headers).content,b'mp4-test-fixture')
            self.assertEqual(client.get('/video-samples/missing/media',headers=headers).status_code,404)
            (directory/'clip.mp4').unlink()
            self.assertEqual(client.get('/video-samples',headers=headers).json(),[])

    def test_uninstalled_samples_have_empty_catalog(self):
        with tempfile.TemporaryDirectory() as store,patch.object(backend,'STORE',Path(store)),patch.object(backend,'API_TOKEN',''):
            self.assertEqual(TestClient(backend.app).get('/video-samples').json(),[])
