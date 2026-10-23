import json
from pathlib import Path
import sys
import tempfile
import unittest
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import server
from learning_loop import import_image_bank
from bank_access import reveal


class BankImportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'tmp',prefix='bank-import-')
        self.root=Path(self.temp.name)
        self.previous=(server.DATA,server.PAPERS_DIR,server.DB_PATH)
        server.DATA=self.root/'data';server.PAPERS_DIR=server.DATA/'papers';server.DB_PATH=server.DATA/'mathlens.db'
        server.init_db();self.conn=server.connect()
        self.source=self.root/'source'
        for category,label,color in ((1,'数学一','white'),(2,'数学二','black'),(3,'数学三','gray')):
            group=self.source/'kaoyan_math_images'/label
            paper=group/'2025';(paper/'analysis').mkdir(parents=True)
            record={'paper':'2025','index':1,'question_id':category,'knowledge_point':'导数','answer':'A'}
            (group/'answers.json').write_text(json.dumps({'fixture':record}),encoding='utf8')
            Image.new('RGB',(30,20),color).save(paper/f'Q01_id{category}.png')
            Image.new('RGB',(30,20),'blue').save(paper/'analysis'/f'Q01_id{category}_analysis.png')

    def tearDown(self):
        self.conn.close();server.DATA,server.PAPERS_DIR,server.DB_PATH=self.previous
        self.temp.cleanup()

    def test_imports_all_three_categories_with_identity_and_resources(self):
        result=import_image_bank(self.conn,self.source,server.DATA)
        self.assertEqual(result['by_type'],{'1':1,'2':1,'3':1})
        self.assertEqual(result['missing'],[])
        rows=list(self.conn.execute('SELECT * FROM bank_identity ORDER BY math_type'))
        self.assertEqual([row['math_type'] for row in rows],[1,2,3])
        self.assertTrue(all(len(row['sha256'])==64 for row in rows))
        self.assertEqual(self.conn.execute('SELECT count(*) FROM bank_resources').fetchone()[0],3)

    def test_reimport_preserves_agent_fingerprint_and_exposure(self):
        import_image_bank(self.conn,self.source,server.DATA)
        self.conn.execute('UPDATE bank_questions SET fingerprint_json=? WHERE id=?',('{"micro_skills":["validated"]}','math1-2025-01'))
        reveal(self.conn,'math1-2025-01','question',True);reveal(self.conn,'math1-2025-01','analysis',True)
        import_image_bank(self.conn,self.source,server.DATA)
        row=self.conn.execute('SELECT fingerprint_json FROM bank_questions WHERE id=?',('math1-2025-01',)).fetchone()
        self.assertEqual(json.loads(row[0])['micro_skills'],['validated'])
        self.assertTrue(self.conn.execute('SELECT 1 FROM bank_exposures WHERE bank_id=?',('math1-2025-01',)).fetchone())
        self.assertEqual(self.conn.execute('SELECT count(*) FROM bank_questions').fetchone()[0],3)


if __name__=='__main__':unittest.main()
