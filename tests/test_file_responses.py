from pathlib import Path
from unittest.mock import patch
import unittest
import test_fastapi_app as fixture
from app.services.resources import Resource


class FileResponseTests(unittest.TestCase):
    def test_disguised_upload_and_actual_file_routes_never_return_active_html(self):
        f=fixture.FastAPIAppTests();f.setUp();self.addCleanup(f.tearDown)
        html=b'<html><script>window.__unsafe=true</script></html>'
        path=f.data/'disguised.html';path.write_bytes(html)
        with f.client(agent_factory=None) as http:
            rt=http.app.state.runtime
            upload=http.post('/api/answer-images',files={'files':('photo.png',html,'image/png')})
            self.assertEqual(upload.status_code,400,upload.text);self.assertNotIn('text/html',upload.headers['content-type'])
            with patch.object(rt.resources,'bank',return_value=Resource(path,'text/html')):
                response=http.get('/api/bank/synthetic/question?view=library')
                self.assertEqual(response.content,html);self.assertEqual(response.headers['content-type'],'application/octet-stream')
                self.assertEqual(response.headers['x-content-type-options'],'nosniff');self.assertEqual(response.headers['content-disposition'],'attachment')
            with patch.object(rt.free_practice,'image',return_value=path):
                response=http.get('/api/bank/synthetic/practice/attempts/a/materials/question')
                self.assertEqual(response.headers['content-type'],'application/octet-stream');self.assertEqual(response.headers['x-content-type-options'],'nosniff')
            with patch.object(rt.profile_practice,'image',return_value=path):
                response=http.get('/api/practices/p/materials/question')
                self.assertEqual(response.headers['content-type'],'application/octet-stream');self.assertEqual(response.headers['x-content-type-options'],'nosniff')
            for name,url,media in [('paper','/api/papers/p/file','application/pdf'),('evidence','/api/questions/q/evidence','image/png')]:
                with patch.object(rt.resources,name,return_value=Resource(html,media)):
                    response=http.get(url);self.assertEqual(response.headers['content-type'],media);self.assertEqual(response.headers['x-content-type-options'],'nosniff')
            for service,url,method in [(rt.knowledge_catalog,'/api/knowledge/packages/export','export_package'),(rt.question_index,'/api/knowledge/question-index/export','export')]:
                with patch.object(service,method,return_value={'sha256':'a'*64}):
                    response=http.get(url);self.assertEqual(response.status_code,200,response.text)
                    self.assertEqual(response.headers['x-content-type-options'],'nosniff');self.assertIn('attachment',response.headers['content-disposition'])
