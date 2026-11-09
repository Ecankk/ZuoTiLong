import json
import unittest
import uuid
from io import BytesIO
from PIL import Image
import test_f5_backend as fixtures


class QuestionRegionTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.F5BackendTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.f.f.apply()
        self.app,self.http=self.f.client();self.conn=self.f.f.conn
        self.qid=self.conn.execute("SELECT id FROM questions WHERE number='1'").fetchone()[0]
        self.url=f'/api/papers/paper-test/questions/{self.qid}/regions'
        self.body=dict(confirmed=True,request_id=str(uuid.uuid4()),regions=[dict(page=1,top=100,bottom=200)])

    def test_history_unchanged_current_crop_updates_and_request_is_idempotent(self):
        before=dict(self.conn.execute('SELECT * FROM questions WHERE id=?',(self.qid,)).fetchone())
        diagnosis=self.conn.execute('SELECT diagnosis_json FROM question_diagnoses WHERE question_id=?',(self.qid,)).fetchone()[0]
        probes=[tuple(r) for r in self.conn.execute('SELECT * FROM diagnostic_probes')]
        old_url=self.http.get('/api/questions/'+self.qid).json()['evidence_urls'][0]
        response=self.http.post(self.url,json=self.body)
        self.assertEqual(response.status_code,200,response.text)
        current=dict(self.conn.execute('SELECT * FROM questions WHERE id=?',(self.qid,)).fetchone())
        for key in before:
            if key not in ('regions_json','page_start','page_end','bbox_json'):self.assertEqual(current[key],before[key],key)
        self.assertEqual(self.conn.execute('SELECT diagnosis_json FROM question_diagnoses WHERE question_id=?',(self.qid,)).fetchone()[0],diagnosis)
        self.assertEqual([tuple(r) for r in self.conn.execute('SELECT * FROM diagnostic_probes')],probes)
        detail=self.http.get('/api/questions/'+self.qid).json()
        self.assertEqual(detail['question']['regions'][0]['bbox'],[0,100,595,200])
        new_url=detail['evidence_urls'][0];self.assertNotEqual(old_url,new_url)
        crop=self.http.get(new_url);self.assertEqual(crop.headers['cache-control'],'no-store')
        with Image.open(BytesIO(crop.content)) as image:self.assertEqual(image.size,(1190,200))
        self.assertTrue(self.http.post(self.url,json=self.body).json()['reused'])
        changed=dict(self.body,regions=[dict(page=1,top=110,bottom=210)])
        self.assertEqual(self.http.post(self.url,json=changed).status_code,409)
        rows=list(self.conn.execute("SELECT * FROM record_versions WHERE kind='question_regions'"))
        self.assertEqual(len(rows),1)
        snapshot=json.loads(rows[0]['payload']);self.assertEqual(snapshot['old']['regions_json'],before['regions_json'])
        self.assertEqual(snapshot['source_sha256'],self.f.f.digest)

    def test_invalid_and_busy_requests_never_change_regions(self):
        for regions in ([],[dict(page=0,top=1,bottom=2)],[dict(page=2,top=1,bottom=2)],
                        [dict(page=1,top=100,bottom=50)],[dict(page=1,top=-1,bottom=50)],
                        [dict(page=1,top=0,bottom=9999)],[dict(page=1,top=1,bottom=2)]*5):
            self.assertEqual(self.http.post(self.url,json=dict(self.body,regions=regions)).status_code,400)
        self.assertEqual(self.http.post(self.url,json=dict(self.body,request_id='bad')).status_code,400)
        self.conn.execute("UPDATE papers SET archived_at='now' WHERE id='paper-test'");self.conn.commit()
        self.assertEqual(self.http.post(self.url,json=self.body).status_code,409)
        self.conn.execute("UPDATE papers SET archived_at=NULL WHERE id='paper-test'")
        from app.learning.workflows import enqueue
        enqueue(self.conn,self.f.config.root,self.f.config.data,kind='analyze_paper',paper_id='paper-test',request_id=str(uuid.uuid4()));self.conn.commit()
        self.assertEqual(self.http.post(self.url,json=self.body).status_code,409)
        self.conn.execute('DELETE FROM workflow_jobs');self.conn.commit()
        self.f.f.pdf.unlink()
        self.assertEqual(self.http.post(self.url,json=self.body).status_code,400)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM record_versions WHERE kind='question_regions'").fetchone()[0],0)

    def test_cross_page_segments_sorted_and_full_width(self):
        import pymupdf
        # Replace only the synthetic PDF; historical hash remains immutable.
        with pymupdf.open() as doc:
            doc.new_page(width=400,height=600);doc.new_page(width=500,height=700)
            doc.save(self.f.f.pdf)
        body=dict(self.body,regions=[dict(page=2,top=20,bottom=300),dict(page=1,top=250,bottom=500),dict(page=1,top=10,bottom=100)])
        response=self.http.post(self.url,json=body)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual([r['bbox'] for r in response.json()['regions']],[[0,10,400,100],[0,250,400,500],[0,20,500,300]])

    def test_page_list_matches_png_and_rounded_bottom_is_accepted(self):
        import pymupdf
        with pymupdf.open() as doc:
            doc.new_page(width=595.3,height=841.2);doc.new_page(width=400,height=600)
            doc.save(self.f.f.pdf)
        with pymupdf.open(self.f.f.pdf) as doc:heights=[p.rect.height for p in doc]
        response=self.http.get('/api/papers/paper-test/pages')
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.headers['cache-control'],'no-store')
        items=response.json()['items'];self.assertEqual([i['page'] for i in items],[1,2])
        self.assertGreater(items[0]['image_height']/items[0]['scale'],heights[0])
        for item in items:
            self.assertEqual(item['scale'],2)
            self.assertEqual(item['image_url'],f'/api/papers/paper-test/pages/{item["page"]}')
            image=self.http.get(item['image_url']);self.assertEqual(image.status_code,200,image.text[:100] if image.status_code!=200 else '')
            self.assertEqual(image.headers['content-type'],'image/png')
            self.assertEqual(image.headers['cache-control'],'no-store')
            with Image.open(BytesIO(image.content)) as png:
                self.assertEqual(png.size,(item['image_width'],item['image_height']))
        body=dict(self.body,regions=[dict(page=i['page'],top=0,bottom=i['image_height']/i['scale']) for i in items])
        saved=self.http.post(self.url,json=body)
        self.assertEqual(saved.status_code,200,saved.text)
        self.assertEqual([r['bbox'][3] for r in saved.json()['regions']],heights)
        self.assertTrue(self.http.post(self.url,json=body).json()['reused'])
        bad=dict(body,request_id=str(uuid.uuid4()),regions=[dict(page=1,top=0,bottom=heights[0]+1)])
        self.assertEqual(self.http.post(self.url,json=bad).status_code,400)

    def test_pages_error_codes_and_archived_read_access(self):
        self.assertEqual(self.http.get('/api/papers/missing/pages').status_code,404)
        self.assertEqual(self.http.get('/api/papers/missing/pages/1').status_code,404)
        for number in (0,-1,2):self.assertEqual(self.http.get(f'/api/papers/paper-test/pages/{number}').status_code,404)
        self.conn.execute("UPDATE papers SET archived_at='now' WHERE id='paper-test'");self.conn.commit()
        self.assertEqual(self.http.get('/api/papers/paper-test/pages').status_code,200)
        self.assertEqual(self.http.get('/api/papers/paper-test/pages/1').status_code,200)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM record_versions WHERE kind='question_regions'").fetchone()[0],0)
        self.f.f.pdf.unlink()
        for path in ('/api/papers/paper-test/pages','/api/papers/paper-test/pages/1'):
            response=self.http.get(path);self.assertEqual(response.status_code,400);self.assertIn('原PDF文件缺失',response.text)
        self.conn.execute("UPDATE papers SET source_path=NULL WHERE id='paper-test'");self.conn.commit()
        self.assertEqual(self.http.get('/api/papers/paper-test/pages').status_code,400)
        self.conn.execute("UPDATE papers SET source_path=? WHERE id='paper-test'",(str(self.f.config.data.parent/'old-paper.pdf'),));self.conn.commit()
        for path in ('/api/papers/paper-test/pages','/api/papers/paper-test/pages/1'):
            response=self.http.get(path);self.assertEqual(response.status_code,400);self.assertIn('原PDF文件缺失',response.text)
