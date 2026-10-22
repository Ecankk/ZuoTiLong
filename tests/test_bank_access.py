import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server
from bank_access import access, init_access, register_identity, reveal, review_cross, save_preferences


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
            [('math1-2025-01', 'fixture', 'one', 'now'), ('math2-2025-01', 'fixture', 'two', 'now')],
        )
        from PIL import Image
        image_dir = self.root / 'bank-assets'
        image_dir.mkdir()
        for bid, color in [('math1-2025-01', 'white'), ('math2-2025-01', 'black')]:
            path = image_dir / (bid + '.png')
            Image.new('RGB', (20, 20), color).save(path)
            register_identity(self.conn, bid, int(bid[4]), '2025', 1, path)
        init_access(self.conn)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        server.DATA, server.PAPERS_DIR, server.DB_PATH = self.previous
        self.temp.cleanup()

    def test_metadata_is_hidden_until_same_category_confirmation(self):
        state = access(self.conn, 'math1-2025-01')
        self.assertFalse(state['can_view'])
        self.assertEqual(state['reason'], '同类别真题，确认后查看')
        reveal(self.conn, 'math1-2025-01', 'question', True)
        self.assertTrue(access(self.conn, 'math1-2025-01')['can_view'])

    def test_cross_category_requires_review_and_reserved_is_blocked(self):
        with self.assertRaisesRegex(ValueError, '跨类别'):
            reveal(self.conn, 'math2-2025-01', 'question', True)
        reviewed = review_cross(self.conn, 'math2-2025-01', '与当前数学一题目结构和考察环节不同，允许作为迁移检验')
        self.assertTrue(reviewed['cross_checked'])
        reveal(self.conn, 'math2-2025-01', 'question', True)
        self.assertTrue(access(self.conn, 'math2-2025-01')['can_view'])
        save_preferences(self.conn, {'study_type': 1, 'reserved': [{'math_type': 1, 'year': '2025'}]})
        self.assertTrue(access(self.conn, 'math1-2025-01')['reserved'])
        with self.assertRaisesRegex(ValueError, '预留'):
            reveal(self.conn, 'math1-2025-01', 'question', True)


if __name__ == '__main__':
    unittest.main()
