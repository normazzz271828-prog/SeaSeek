import importlib
import os
import tempfile
import unittest
from unittest.mock import patch,Mock

# Single-file test runs must not initialize or update the user's real database.
TEMP=tempfile.TemporaryDirectory()
os.environ['HAIXUN_DATA_DIR']=TEMP.name


class CloudContracts(unittest.TestCase):
    def test_internal_tasks_hidden_without_changing_source_records(self):
        import ui
        internal=next(iter(ui.INTERNAL_TASK_IDS))
        records=[dict(id=internal,name='独立域名上线验收'),dict(id='demo-coastal',name='演示任务',area='虚构',owner='演示负责人',description='演示'),dict(id='user-task',name='用户任务')]
        visible=ui.public_tasks(records)
        self.assertEqual([r['id'] for r in visible],['demo-coastal','user-task'])
        self.assertIn('示例任务',visible[0]['name'])
        self.assertEqual(records[1]['name'],'演示任务')
        self.assertEqual(visible[1]['name'],'用户任务')
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
        with patch.object(ui,'connection_settings',return_value=('https://api.example','test-token')),patch.object(ui.requests,'request',return_value=response) as request:
            self.assertEqual(ui.api('GET','/videos/id/media/result',binary=True),b'video-bytes')
            self.assertEqual(request.call_args.kwargs['headers']['Authorization'],'Bearer test-token')
            self.assertFalse(request.call_args.kwargs['allow_redirects'])
            self.assertNotIn('test-token',request.call_args.args[1])

    def test_secrets_updates_apply_without_reimporting_modules(self):
        import runtime,ui
        secrets={}
        response=Mock(is_redirect=False)
        response.json.return_value=[]
        with patch.dict(os.environ,{},clear=True),patch.object(runtime,'CLOUD',True),patch.object(runtime.st,'secrets',secrets),patch.object(ui.requests,'request',return_value=response) as request:
            self.assertEqual(runtime.connection_settings(),('',''))
            secrets.update(HAIXUN_API_URL='https://first.example/',HAIXUN_API_TOKEN='first-token')
            ui.api('GET','/tasks')
            self.assertEqual(request.call_args.args[1],'https://first.example/tasks')
            secrets.update(HAIXUN_API_URL='https://second.example',HAIXUN_API_TOKEN='rotated-token')
            ui.api('GET','/tasks')
            self.assertEqual(request.call_args.args[1],'https://second.example/tasks')
            self.assertEqual(request.call_args.kwargs['headers']['Authorization'],'Bearer rotated-token')

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
