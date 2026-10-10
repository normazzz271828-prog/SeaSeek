import importlib
import os
import unittest
from unittest.mock import patch,Mock


class CloudContracts(unittest.TestCase):
    def test_root_entry_hosted_binding_has_no_local_api_fallback(self):
        import runtime
        for address,cloud in [(None,True),('0.0.0.0',True),('127.0.0.1',False)]:
            with patch.dict(os.environ,{},clear=True),patch.object(runtime.st,'secrets',{}),patch.object(runtime.st,'get_option',return_value=address):
                importlib.reload(runtime)
                self.assertEqual(runtime.CLOUD,cloud)
                self.assertEqual(runtime.API,'' if cloud else 'http://127.0.0.1:8765')
        importlib.reload(runtime)

    def test_cloud_has_no_local_api_fallback(self):
        import runtime
        with patch.dict(os.environ,{'SEASEEK_RUNTIME':'cloud'},clear=True),patch.object(runtime.st,'secrets',{}):
            importlib.reload(runtime)
            self.assertEqual(runtime.API,'')
            self.assertTrue(runtime.CLOUD)
        importlib.reload(runtime)

    def test_secrets_and_env_precedence(self):
        import runtime
        with patch.dict(os.environ,{'SEASEEK_RUNTIME':'cloud','HAIXUN_API_URL':'https://env.example/'},clear=True),patch.object(runtime.st,'secrets',{'HAIXUN_API_URL':'https://secret.example','HAIXUN_API_TOKEN':'secret-token'}):
            importlib.reload(runtime)
            self.assertEqual(runtime.API,'https://env.example')
            self.assertEqual(runtime.API_TOKEN,'secret-token')
        importlib.reload(runtime)

    def test_binary_request_keeps_service_token_on_server(self):
        import ui
        response=Mock(content=b'video-bytes',is_redirect=False)
        with patch.object(ui,'API','https://api.example'),patch.object(ui,'API_TOKEN','test-token'),patch.object(ui.requests,'request',return_value=response) as request:
            self.assertEqual(ui.api('GET','/videos/id/media/result',binary=True),b'video-bytes')
            self.assertEqual(request.call_args.kwargs['headers']['Authorization'],'Bearer test-token')
            self.assertFalse(request.call_args.kwargs['allow_redirects'])
            self.assertNotIn('test-token',request.call_args.args[1])

    def test_backend_service_token_gates_business_and_media(self):
        import backend
        from fastapi.testclient import TestClient
        with patch.object(backend,'API_TOKEN','test-token'):
            client=TestClient(backend.app)
            self.assertEqual(client.get('/health').status_code,200)
            self.assertEqual(client.get('/tasks').status_code,401)
            self.assertEqual(client.get('/videos/id/media/result').status_code,401)
            self.assertEqual(client.get('/tasks',headers={'Authorization':'Bearer wrong'}).status_code,401)
            self.assertEqual(client.get('/tasks',headers={'Authorization':'Bearer test-token'}).status_code,200)
