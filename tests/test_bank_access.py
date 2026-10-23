import tempfile
import json
import unittest
from unittest.mock import patch
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server
from bank_access import access, init_access, register_identity, reveal, save_preferences, public_bank, record_view, preferences
from urllib.parse import urlparse


class BankAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'tmp', prefix='bank-access-')
        self.root = Path(self.temp.name)
        self.previous = (server.DATA, server.PAPERS_DIR, server.DB_PATH)
        server.DATA = self.root
        server.PAPERS_DIR = self.root / 'papers'
        server.DB_PATH = self.root / 'test.db'
        server.init_db()
        self.conn = server.connect()
        self.conn.executemany(
            "INSERT INTO bank_questions(id,source,stem,created_at) VALUES(?,?,?,?)",
            [('math1-2025-01', 'fixture', 'one', 'now'), ('math2-2025-01', 'fixture', 'two', 'now'), ('math3-2025-01', 'fixture', 'three', 'now')],
        )
        from PIL import Image
        image_dir = self.root / 'bank-assets'
        image_dir.mkdir()
        for bid, color in [('math1-2025-01', 'white'), ('math2-2025-01', 'black'), ('math3-2025-01', 'gray')]:
            path = image_dir / (bid + '.png')
            Image.new('RGB', (20, 20), color).save(path)
            register_identity(self.conn, bid, int(bid[4]), '2025', 1, path)
            self.conn.execute('INSERT INTO bank_resources VALUES(?,?,?,?,NULL)',(bid,'{}',str(path.relative_to(self.root)),str(path.relative_to(self.root))))
        init_access(self.conn)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        server.DATA, server.PAPERS_DIR, server.DB_PATH = self.previous
        self.temp.cleanup()

    def test_metadata_is_hidden_until_same_category_confirmation(self):
        state = access(self.conn, 'math1-2025-01')
        self.assertFalse(state['can_view'])
        self.assertIn('检验题已隐藏',state['reason'])
        reveal(self.conn, 'math1-2025-01', 'question', True)
        self.assertTrue(access(self.conn, 'math1-2025-01')['can_view'])

    def test_other_categories_display_directly_and_reserved_is_not_selected(self):
        self.assertTrue(access(self.conn, 'math2-2025-01')['can_view'])
        self.assertTrue(access(self.conn, 'math3-2025-01')['can_view'])
        self.assertFalse(access(self.conn, 'math2-2025-01')['cross_checked'])
        save_preferences(self.conn, {'study_type': 1, 'reserved': [{'math_type': 1, 'year': '2025'}]})
        self.assertTrue(access(self.conn, 'math1-2025-01')['reserved'])
        with self.assertRaisesRegex(ValueError, '预留'):
            reveal(self.conn, 'math1-2025-01', 'question', True)
        self.assertIn('question_image',public_bank(self.conn,'math1-2025-01',view='library'))

    def test_study_category_and_hide_switch_only_control_probes(self):
        for selected in (1,2,3):
            save_preferences(self.conn,{'study_type':selected,'mask_same_type':True,'reserved':[]})
            for category in (1,2,3):
                bid=f'math{category}-2025-01'
                self.assertEqual(access(self.conn,bid)['can_view'],category!=selected)
                self.assertTrue(public_bank(self.conn,bid,view='library')['can_view'])
        save_preferences(self.conn,{'study_type':3,'mask_same_type':False,'reserved':[]})
        self.assertTrue(all(access(self.conn,f'math{n}-2025-01')['can_view'] for n in (1,2,3)))
        with self.assertRaises(ValueError):save_preferences(self.conn,{'study_type':1,'mask_same_type':'false'})

    def test_library_view_does_not_silently_confirm_hidden_probe(self):
        bid='math1-2025-01'
        visible=public_bank(self.conn,bid,view='library')
        self.assertIn('view=library',visible['question_image'])
        record_view(self.conn,bid,'question')
        self.assertFalse(access(self.conn,bid)['can_view'])
        self.assertNotIn('stem',public_bank(self.conn,bid))
        record_view(self.conn,bid,'analysis')
        self.assertTrue(self.conn.execute('SELECT 1 FROM bank_exposures WHERE bank_id=?',(bid,)).fetchone())
        self.assertFalse(access(self.conn,bid)['can_view'])

    def test_http_library_image_is_open_but_probe_image_stays_hidden(self):
        self.conn.commit()
        handler=server.Handler.__new__(server.Handler)
        result={};served=[]
        handler.send_json=lambda payload,status=200:result.update(status=status,payload=payload)
        handler.send_file=lambda path,mime:served.append(path)
        handler.api_get(urlparse('/api/bank/math1-2025-01/question'))
        self.assertEqual(result['status'],403)
        handler.api_get(urlparse('/api/bank/math1-2025-01/question?view=library'))
        self.assertEqual(len(served),1)
        self.assertFalse(access(self.conn,'math1-2025-01')['can_view'])
        handler.api_get(urlparse('/api/bank/math2-2025-01/question'))
        self.assertEqual(len(served),2)

    def test_legacy_preferences_default_to_masked_probes(self):
        self.conn.execute("UPDATE preferences SET payload=? WHERE id=1",('{"study_type":1,"reserved":[]}',))
        self.assertTrue(preferences(self.conn)['mask_same_type'])

    def test_agent_tool_distinguishes_direct_question_and_unrevealed_analysis(self):
        from learning_tools import execute
        with patch('learning_tools.connection',lambda data:server.connect()):
            direct=json.loads(execute(ROOT,self.root,'read_bank',{'bank_id':'math2-2025-01'})[0]['text'])
            reference=json.loads(execute(ROOT,self.root,'read_bank',{'bank_id':'math2-2025-01','role':'analysis'})[0]['text'])
            masked=json.loads(execute(ROOT,self.root,'read_bank',{'bank_id':'math1-2025-01'})[0]['text'])
        self.assertFalse(direct['internal_only'])
        self.assertTrue(reference['internal_only'])
        self.assertTrue(masked['internal_only'])


if __name__ == '__main__':
    unittest.main()
