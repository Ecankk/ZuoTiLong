import tempfile,unittest
from pathlib import Path
from app.agent.bridge import CodexBridge,BridgeConflict
from test_execution_v2 import FakeServer

FakeCodex=FakeServer
ROOT=Path(__file__).resolve().parents[1]

class CodexBridgeTests(unittest.TestCase):
    def test_model_catalog_uses_app_server_without_starting_a_thread(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as folder:
            b=CodexBridge(ROOT,Path(folder),FakeCodex)
            try:
                value=b.models()
                self.assertEqual(value['status'],'available')
                self.assertEqual(value['items'][0]['efforts'],['high','xhigh'])
                self.assertFalse(any(m=='thread/start' for m,_ in b.transport.calls))
                with self.assertRaises(BridgeConflict):b.submit('chat','request')
            finally:b.close()

    def test_not_logged_in_is_reported_without_starting_a_thread(self):
        class LoggedOut(FakeCodex):
            def request(self,method,params):
                if method=='account/read':return {'account':None}
                return super().request(method,params)
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as folder:
            b=CodexBridge(ROOT,Path(folder),LoggedOut)
            try:
                value=b.models()
                self.assertEqual(value['reason'],'not_logged_in');self.assertEqual(value['items'],[])
            finally:b.close()
