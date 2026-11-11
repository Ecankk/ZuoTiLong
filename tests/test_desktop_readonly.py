from contextlib import contextmanager
import io,json,os,re,socket,sqlite3,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import desktop_fixture as fixture
from app.desktop.config import settings
from app.desktop.prepare import prepare
from app.desktop.protocol import Protocol


@contextmanager
def deny_writes(directory):
    # Only this test-owned TEMP directory; restore the explicit deny on exit.
    identity=subprocess.check_output(['whoami','/user','/fo','csv','/nh'],encoding='utf8',errors='replace')
    sid=re.search(r'S-1-\d+(?:-\d+)+',identity)[0]
    # Generic W also denies SYNCHRONIZE on Windows, which can block reads.
    result=subprocess.run(['icacls',str(directory),'/deny','*'+sid+':(OI)(CI)(WD,AD,WEA,WA,DC)'],capture_output=True)
    if result.returncode:raise unittest.SkipTest('Cannot set test directory ACL')
    try:yield
    finally:
        result=subprocess.run(['icacls',str(directory),'/remove:d','*'+sid,'/t','/c'],capture_output=True)
        if result.returncode:raise RuntimeError('Could not restore test-owned directory ACL')


@unittest.skipUnless(os.name=='nt','Windows ACL test')
class ReadOnlyDesktopTests(unittest.TestCase):
    def test_actual_deny_write_resources_pdf_scanned_ocr_and_image_codecs_offline(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);root=fixture.resources(base);args=fixture.arguments(base,root)
            with patch.dict(os.environ,dict(MATHLENS_DATA_DIR=str(base/'decoy-data'),MATHLENS_LIBRARY_DIR=str(base/'decoy-library'))):
                with deny_writes(root):
                    with self.assertRaises(PermissionError):(root/'forbidden').write_text('bad')
                    config=settings(args);prepare(config,Protocol('prepare',args.launch_nonce,io.StringIO()))
                    from app.agent.methods import body
                    self.assertIn('Synthetic method',body(config.root,'paper-diagnosis'))
                    from app.agent.tools import execute
                    result=json.loads(execute(config.root,config.data,'read_skill',{'name':'paper-diagnosis'})[0]['text'])
                    self.assertEqual(result['report_contract'],'Synthetic document')
                    result=json.loads(execute(config.root,config.data,'read_skill',{'name':'bank-search'})[0]['text'])
                    self.assertEqual(result['source_catalog']['text'],'Synthetic document')
                    self.assertEqual(result['source_interface']['text'],'Synthetic document')
                    from fastapi.testclient import TestClient
                    from app.main import create_app
                    with TestClient(create_app(config,agent_factory=None),base_url='http://127.0.0.1') as http:
                        import pymupdf
                        with pymupdf.open() as pdf:
                            page=pdf.new_page();page.insert_text((40,80),'1. Compute one plus one.',fontsize=20)
                            digital=pdf.tobytes();png=page.get_pixmap(matrix=pymupdf.Matrix(2,2)).tobytes('png')
                        with pymupdf.open() as pdf:
                            page=pdf.new_page();page.insert_image(page.rect,stream=png);scanned=pdf.tobytes()
                        # Load the bundled local model while all socket connects fail.
                        from app.documents.pdf import extract_pdf
                        with patch.object(socket.socket,'connect',side_effect=AssertionError('OCR must stay offline')):
                            scan=config.data/'synthetic-scan.pdf';scan.write_bytes(scanned)
                            value=extract_pdf(scan,cache_root=config.data/'ocr-cache')
                        self.assertEqual(value['pages'][0]['engine'],'rapidocr_onnxruntime',value['pages'][0]['warning'])
                        self.assertTrue(value['pages'][0]['text'])
                        upload=http.post('/api/papers/import',files={'file':('digital.pdf',digital,'application/pdf')})
                        self.assertEqual(upload.status_code,201,upload.text);self.assertFalse(upload.json()['agent_queued'])
                        qid=http.get('/api/papers/'+upload.json()['paper']['id']+'/questions').json()['items'][0]['id']
                        self.assertEqual(http.get('/api/questions/'+qid+'/evidence').status_code,200)
                        self.assertEqual(http.get('/api/bank?limit=20').status_code,200)
                        from PIL import Image
                        for fmt in ('JPEG','PNG','WEBP'):
                            stream=io.BytesIO();Image.new('RGB',(5,5),'blue').save(stream,format=fmt)
                            with Image.open(io.BytesIO(stream.getvalue())) as image:self.assertEqual(image.size,(5,5))
                    self.assertTrue(list((config.data/'ocr-cache').rglob('*.json')))
                self.assertFalse((base/'decoy-data').exists());self.assertFalse((base/'decoy-library').exists())

    def test_explicit_cache_is_required_before_any_writes(self):
        from app.documents.pdf import extract_pdf
        with self.assertRaises(TypeError):extract_pdf(Path('missing.pdf'))
        with self.assertRaises(ValueError):extract_pdf(Path('missing.pdf'),cache_root=Path('relative'))
