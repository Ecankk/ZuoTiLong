"""Synthetic local PDF cases; no real paper, Codex or source library."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.config import AppConfig
from app.storage.database import Database
from app.services.papers import PaperService
from app.documents.pdf import segment_pages


def page(number,blocks):
    return dict(page_number=number,width=595,height=842,blocks=[dict(text=t,bbox=b) for t,b in blocks])


class LocalPaperExtractionTests(unittest.TestCase):
    def test_new_section_is_not_a_continuation_of_previous_question(self):
        pages=[page(1,[('(1) First main question',[50,700,400,715])]),
               page(2,[('二、解答题（本题共若干题）',[50,45,530,60]),('(2) Next main question',[50,65,400,80])])]
        questions,warnings=segment_pages(pages,2)
        self.assertEqual(warnings,[])
        self.assertEqual([q['number'] for q in questions],['1','2'])
        self.assertEqual([r['page'] for r in questions[0]['regions']],[1])
        self.assertNotIn('解答题',questions[0]['stem'])
        self.assertEqual(questions[0]['regions'][0]['bbox'][0],0)
        self.assertEqual(questions[0]['regions'][0]['bbox'][2],595)

    def test_actual_cross_page_continuation_is_preserved_before_new_section(self):
        pages=[page(1,[('(1) Main question',[50,700,400,715])]),
               page(2,[('Remaining options and work',[60,40,500,55]),
                       ('二.解答题',[50,100,530,115]),('(2) Next main question',[50,130,400,145])])]
        questions,_=segment_pages(pages,2)
        self.assertEqual([r['page'] for r in questions[0]['regions']],[1,2])
        self.assertIn('Remaining options',questions[0]['stem'])
        self.assertNotIn('解答题',questions[0]['stem'])

    def test_local_import_and_reanalysis_never_enqueue_and_keep_stable_questions(self):
        import pymupdf
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            cfg=AppConfig(root,root/'data',root/'dist',root/'data'/'learning.db')
            database=Database(cfg);database.initialize();service=PaperService(cfg,database)
            with pymupdf.open() as pdf:
                p=pdf.new_page();p.insert_text((50,70),'1. First main question.\n(1) Subpart.\n(2) Subpart.\n2. Next main question.')
                raw=pdf.tobytes()
            with patch('app.services.papers.enqueue',side_effect=AssertionError('AI queued')):
                result,code=service.import_pdf('fixture.pdf',raw,{},queue_agent=False)
                self.assertEqual(code,201);self.assertFalse(result['agent_queued'])
                pid=result['paper']['id']
                with database.session(write=True) as conn:
                    before=[tuple(r) for r in conn.execute('SELECT * FROM questions ORDER BY id')]
                    service.analyze(conn,pid)
                    self.assertEqual(before,[tuple(r) for r in conn.execute('SELECT * FROM questions ORDER BY id')])
                    self.assertEqual(conn.execute('SELECT count(*) FROM learning_tasks').fetchone()[0],0)
                    self.assertEqual(conn.execute('SELECT count(*) FROM workflow_jobs').fetchone()[0],0)
                reused,code=service.import_pdf('fixture.pdf',raw,{},queue_agent=False)
                self.assertTrue(reused['reused']);self.assertEqual(code,200)

    def test_tall_math_crop_context_does_not_reassign_preceding_ocr_text(self):
        questions,_=segment_pages([page(1,[('(1) First question',[50,40,400,55]),
            ('Previous answer tail',[60,80,400,90]),('(2) Matrix question',[50,100,400,120])])],2)
        self.assertLessEqual(questions[1]['bbox'][1],80)
        self.assertIn('Previous answer tail',questions[0]['stem'])
        self.assertNotIn('Previous answer tail',questions[1]['stem'])
        self.assertLess(questions[1]['bbox'][1],questions[0]['bbox'][3])
