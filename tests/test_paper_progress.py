import json
import unittest
from pathlib import Path
from unittest.mock import patch
import test_learning_loop as fixtures
from app.documents.pdf import extract_pdf
from app.documents.progress import write_progress, list_progress, interrupt_old_progress


class PaperProgressTests(unittest.TestCase):
    def setUp(self):self.fixture=fixtures.LearningLoopTests();self.fixture.setUp()
    def tearDown(self):self.fixture.tearDown()

    def test_observed_page_counts_warnings_and_restart_are_durable(self):
        f=self.fixture
        write_progress(f.root,'paper-test',status='running',phase='opening')
        result=extract_pdf(f.pdf,allow_ocr=False,cache_root=f.root/'cache',
                           on_progress=lambda **fields:write_progress(f.root,'paper-test',**fields))
        progress=list_progress(f.root)[0]
        self.assertEqual(progress['pages_done'],1)
        self.assertEqual(progress['pages_total'],1)
        self.assertEqual(progress['questions'],len(result['questions']))
        self.assertEqual(progress['warnings'],result['warnings'])
        interrupt_old_progress(f.root)
        self.assertEqual(list_progress(f.root)[0]['status'],'interrupted')
        self.assertTrue(f.pdf.is_file())

    def test_cached_read_still_reports_actual_total(self):
        f=self.fixture;updates=[]
        extract_pdf(f.pdf,allow_ocr=False,cache_root=f.root/'cache')
        extract_pdf(f.pdf,allow_ocr=False,cache_root=f.root/'cache',on_progress=lambda **v:updates.append(v))
        self.assertTrue(updates[0]['cached'])
        self.assertEqual(updates[0]['pages_done'],updates[0]['pages_total'])

    def test_transient_windows_replacement_retries_atomically(self):
        f=self.fixture;write_progress(f.root,'paper-test',status='running',pages_total=3)
        original=Path.replace;calls=[]
        def replace(source,target):
            calls.append(source)
            if len(calls)<3:
                error=PermissionError('temporary reader');error.winerror=5;raise error
            return original(source,target)
        with patch.object(Path,'replace',replace),patch('app.documents.progress.time.sleep') as sleep:
            write_progress(f.root,'paper-test',pages_done=2)
        self.assertEqual(len(calls),3);self.assertEqual(sleep.call_count,2)
        value=list_progress(f.root)[0]
        self.assertEqual((value['pages_done'],value['pages_total']),(2,3))
        self.assertEqual(len(set(calls)),1)
        self.assertFalse(list((f.root/'tasks/paper-test').glob('progress-*.tmp')))

    def test_persistent_windows_replacement_fails_and_keeps_saved_progress(self):
        f=self.fixture;write_progress(f.root,'paper-test',pages_done=1)
        path=f.root/'tasks/paper-test/progress.json';before=path.read_bytes()
        error=PermissionError('persistent sharing conflict');error.winerror=32
        with patch.object(Path,'replace',side_effect=error) as replace,patch('app.documents.progress.time.sleep') as sleep:
            with self.assertRaises(PermissionError):write_progress(f.root,'paper-test',pages_done=2)
        self.assertEqual(replace.call_count,5);self.assertEqual(sleep.call_count,4)
        self.assertEqual(path.read_bytes(),before)
        self.assertFalse(list(path.parent.glob('progress-*.tmp')))

    def test_unrelated_replacement_error_is_not_retried(self):
        f=self.fixture
        with patch.object(Path,'replace',side_effect=PermissionError('not a Windows transient error')) as replace,patch('app.documents.progress.time.sleep') as sleep:
            with self.assertRaises(PermissionError):write_progress(f.root,'paper-test',pages_done=1)
        self.assertEqual(replace.call_count,1);sleep.assert_not_called()
