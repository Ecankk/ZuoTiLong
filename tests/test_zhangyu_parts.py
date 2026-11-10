import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts.bank_source_adapters import zhangyu_html as adapter
from app.bank.source_records import canonical,validate,bank_id


class ZhangyuPartTests(unittest.TestCase):
    def test_new_collection_is_registered_and_four_test_volumes_stay_separate(self):
        import test_source_import as fixtures
        from app.bank.source_import import import_source
        from app.main import create_app
        from fastapi.testclient import TestClient
        f=fixtures.SourceImportTests();f.setUp();self.addCleanup(f.doCleanups)
        f.apply()  # Existing membership is unaffected by the added default.
        old_id=bank_id(f.batch[0]);f.batch=[]
        for index,name in enumerate(('测试卷一','测试卷二','测试卷三','测试卷四'),68):
            q=fixtures.question(uid=f'chapters/chapter-{index}.html#q1',source='S03',number=None)
            q.update(exam_year=None,math_type=None,math_types=[1],book=dict(title='Synthetic',edition=None,
                part='综合篇',chapter=name,number='1',locator=name+' / 第 1 题'),tags=['测试卷',name])
            f.batch.append(q)
        f.save();plan=import_source(f.config,'S03',f.path,collection='zhangyu-1000-tests')
        import_source(f.config,'S03',f.path,collection='zhangyu-1000-tests',confirm=plan['plan_sha256'])
        with TestClient(create_app(f.config,agent_factory=None),base_url='http://127.0.0.1') as http:
            groups={v['id']:v for v in http.get('/api/bank/collections').json()}
            self.assertEqual(groups['zhangyu-1000-tests']['name'],'张宇1000题测试卷')
            self.assertEqual(groups['zhangyu-1000-tests']['total'],4)
            cards=http.get('/api/bank?collection=zhangyu-1000-tests&limit=100').json()['items']
            self.assertEqual({c['book']['chapter'] for c in cards},{'测试卷一','测试卷二','测试卷三','测试卷四'})
            self.assertEqual(http.get('/api/bank?collection=zhenti').json()['items'][0]['id'],old_id)

    def test_parts_locators_stable_default_raw_types_and_missing_answer(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'chapters').mkdir()
            (root/'index.html').write_text('<title>2026张宇1000题 数学一</title>',encoding='utf8')
            for chapter,part in [(1,'基础篇'),(32,'强化篇'),(68,'综合篇')]:
                text=f'''<div class="top-title">{part} · 测试卷一（1题）</div>
                <article class="question" data-no="1" id="q1"><span class="q-no">1</span><span class="q-kind">解答题</span>
                <div class="q-stem">Synthetic $x+1$</div><div class="analysis-body">Synthetic reasoning</div></article>'''
                if chapter==1:text=text.replace('Synthetic reasoning','')
                (root/f'chapters/chapter-{chapter:02d}.html').write_text(text,encoding='utf8')
            hashes={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*.html')}
            (root/'adapter.hashes.json').write_text(json.dumps(hashes),encoding='utf8')
            parts={'strengthening':(range(32,33),1),'comprehensive':(range(68,69),1),'basic':(range(1,2),1)}
            with patch.object(adapter,'PARTS',parts),patch.object(adapter,'__file__',str(root/'adapter.py')):
                default=adapter.adapt(root);explicit=adapter.adapt(root,parts=['strengthening'])
                self.assertEqual(canonical(default),canonical(explicit))
                self.assertEqual(default[0]['book']['number'],'1')
                combined=adapter.adapt(root,parts=['comprehensive','basic'])
                self.assertEqual([r['book']['part'] for r in combined],['基础篇','综合篇'])
                self.assertEqual(combined[0]['analysis']['text'],'')
                for r in combined:
                    validate(r,root)
                    self.assertIsNone(r['exam_year']);self.assertIsNone(r['math_type']);self.assertIsNone(r['number'])
                    self.assertEqual(r['math_types'],[1]);self.assertEqual(r['answer']['text'],'')
                    self.assertEqual(r['question_type'],'proof');self.assertEqual(r['original']['record']['upstream']['question_type'],'解答题')
                    self.assertEqual(r['locator']['pointer'],'#q1')
                    if r['book']['part']=='综合篇':
                        self.assertEqual(r['tags'],['测试卷','测试卷一']);self.assertEqual(r['book']['number'],'1')
                        self.assertEqual(r['book']['locator'],'测试卷一 / 第 1 题')
                    else:self.assertIn(r['book']['part'],r['tags'])
                self.assertEqual(bank_id(combined[1]),bank_id(adapter.adapt(root,parts=['comprehensive'])[0]))
                with self.assertRaises(ValueError):adapter.adapt(root,parts=['comprehensive','comprehensive'])
                (root/'chapters/chapter-68.html').write_text('tampered',encoding='utf8')
                self.assertEqual(adapter.adapt(root),default)  # Unselected chapters do not affect the old pipeline.
                with self.assertRaisesRegex(ValueError,'SHA256'):adapter.adapt(root,parts=['comprehensive'])
