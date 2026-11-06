from contextlib import closing
import hashlib
from http.client import HTTPConnection
from io import BytesIO
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import threading
import unittest
from PIL import Image
from app.bank import source_records as records
from scripts import review_sheet as sheet
import test_source_import as imports
import test_question_annotations as annotated


class ReviewSheetTests(unittest.TestCase):
    def setUp(self):
        self.f=imports.SourceImportTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.output=self.f.root/'private'
        raw=BytesIO();Image.new('RGB',(25,20),'white').save(raw,'PNG');self.image=raw.getvalue()
        asset=self.f.root/'figure.png';asset.write_bytes(self.image)
        part=dict(path=asset.name,sha256=hashlib.sha256(self.image).hexdigest(),media_type='image/png')
        self.f.batch[0]['stem']['images']=[part]
        self.f.batch[0]['options'][0]['content']['images']=[part]
        self.f.batch[0]['analysis']['images']=[part]
        self.f.save();self.f.apply()
        self.library=self.f.config.library_dir;self.bid=records.bank_id(self.f.batch[0])

    def generate(self,notes=None):return sheet.generate(self.library,'zhenti',[self.bid],self.output,notes)

    def test_offline_export_original_images_options_notes_and_frontend_math(self):
        before=hashlib.sha256((self.library/'library.db').read_bytes()).hexdigest()
        notes=self.f.root/'decisions.json';notes.write_text(json.dumps([dict(bank_id=self.bid,checks=['Check synthetic formula'],errata=[dict(find='x',replace='y')])]),encoding='utf8')
        cards=self.generate(notes);card=cards[0]
        self.assertEqual(card['resources']['question']['text'],'Invented fixture $x+1$')
        self.assertEqual([o['label'] for o in card['options']],['A','B'])
        self.assertEqual(len(card['resources']['question']['images']),1)
        for role in ('question','analysis'):
            self.assertEqual((self.output/card['resources'][role]['images'][0]).read_bytes(),self.image)
        self.assertEqual(card['notes']['checks'],['Check synthetic formula'])
        self.assertEqual(before,hashlib.sha256((self.library/'library.db').read_bytes()).hexdigest())
        self.assertTrue((self.output/'vendor/katex/fonts/KaTeX_Main-Regular.woff2').is_file())
        self.assertTrue((self.output/'vendor/math.js').is_file())
        js=r"const fs=require('fs'),vm=require('vm');const c={};vm.createContext(c);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),c);process.stdout.write(JSON.stringify(c.mathParts('$x$ and \\(y\\) and $$z$$').filter(p=>p.kind==='math').map(p=>p.text)));"
        result=subprocess.run(['node','-e',js,str(self.output/'vendor/math.js')],capture_output=True,text=True,check=True)
        self.assertEqual(json.loads(result.stdout),['x','y','z'])
        html=(self.output/'index.html').read_text(encoding='utf8')
        script=html.rsplit('<script>',1)[1].split('</script>',1)[0]
        path=self.f.root/'check.js';path.write_text(script,encoding='utf8')
        subprocess.run(['node','--check',str(path)],capture_output=True,check=True)

    def test_feedback_autosave_photos_reload_and_boundary_guards(self):
        cards=self.generate();http=sheet.make_server(self.output,cards)
        thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        self.addCleanup(lambda:(http.shutdown(),thread.join(),http.server_close()))
        origin='http://127.0.0.1:'+str(http.server_port)
        def request(method,path,body=None,foreign=False):
            with closing(HTTPConnection('127.0.0.1',http.server_port,timeout=4)) as client:
                headers={'Origin':'http://elsewhere.invalid' if foreign else origin}
                client.request(method,path,body,headers);r=client.getresponse();return r.status,r.read()
        payload=dict(bank_id=self.bid,material_sha256=cards[0]['material_sha256'],verdict='error',note='Original says $x=2$.')
        status,raw=request('POST','/feedback',json.dumps(payload));self.assertEqual(status,200,raw)
        saved=json.loads((self.output/'feedback.json').read_text(encoding='utf8'))
        self.assertEqual(saved[0]['verdict'],'error');self.assertEqual(saved[0]['note'],payload['note'])
        path=f'/photos?bank_id={self.bid}&material_sha256={payload["material_sha256"]}'
        status,raw=request('POST',path,self.image);self.assertEqual(status,200,raw)
        photo=json.loads(raw)['photos'][0];self.assertTrue((self.output/photo).is_file())
        self.assertEqual(request('GET','/'+photo)[0],200)
        self.assertEqual(json.loads(request('GET','/state')[1])[0]['photos'],[photo])
        self.assertEqual(request('POST','/feedback',json.dumps(dict(payload,material_sha256='bad')))[0],400)
        self.assertEqual(request('POST','/feedback',json.dumps(payload),foreign=True)[0],403)
        self.assertEqual(request('GET','/%2e%2e/library/library.db')[0],404)
        self.assertEqual(request('POST',path,b'not an image')[0],400)
        self.assertEqual(self.generate()[0]['material_sha256'],payload['material_sha256'])
        with self.assertRaises(ValueError):sheet.generate(self.library,'other',[self.bid],self.output)
        with self.assertRaises(ValueError):sheet.generate(self.library,'zhenti',[self.bid],self.library/'output')
        with self.assertRaises(ValueError):sheet.generate(self.library,'zhenti',['missing'],self.output)

    def test_explicit_environment_required_and_id_file(self):
        path=self.f.root/'ids.txt';path.write_text(self.bid+'\n'+self.bid,encoding='utf8')
        self.assertEqual(sheet.bank_ids(str(path)),[self.bid])
        env=dict(os.environ);env.pop('MATHLENS_LIBRARY_DIR',None)
        result=subprocess.run([os.sys.executable,'-X','utf8',str(Path(sheet.__file__)),'--collection','zhenti','--bank-ids',self.bid,'--output',str(self.output)],env=env,capture_output=True,text=True,encoding='utf8')
        self.assertEqual(result.returncode,2);self.assertIn('MATHLENS_LIBRARY_DIR',result.stderr)
        self.assertFalse(self.output.exists())


class ReviewSheetAnnotationTests(unittest.TestCase):
    def test_current_annotation_topics_and_review_note_without_personal_database(self):
        f=annotated.QuestionPreparationTests();f.setUp();self.addCleanup(f.tearDown)
        ids=f.save_annotation()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);library=root/'library';library.mkdir();output=root/'private';output.mkdir()
            with closing(sqlite3.connect(library/'library.db')) as destination:
                f.conn.backup(destination,name='library')
            cards=sheet.read_cards(library,'other',ids,output,{})
            self.assertEqual(cards[0]['status'],'ready')
            self.assertEqual(cards[0]['topics'][0]['role'],'primary')
            self.assertTrue(cards[0]['topics'][0]['path'])
            self.assertEqual(cards[0]['review_note'],'独立推导与参考导数相同。')
            self.assertFalse((root/'learning.db').exists())
