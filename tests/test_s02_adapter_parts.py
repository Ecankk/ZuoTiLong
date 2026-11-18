import unittest

from scripts.bank_source_adapters.cxy_daguan import _convert_s02_parts
from app.bank.source_records import resource, sha256


class S02AdapterPartTests(unittest.TestCase):
    def test_parts_filter_and_book_metadata(self):
        questions=[]
        for uid,tags,label,kind in (
            ('a',['0.88k'],'0.88k·第二章·基础·选择第3题','single_choice'),
            ('b',['武忠祥基础严选'],'基础严选第4章解答2','subjective'),
            ('c',['1k'],'1k·第九章·基础·第5题','fill'),
        ):
            questions.append(dict(id=uid,source=label,original_source=label,source_details=label,
                source_tags=tags,question_type=kind,stem='stem',options=[],correct_answer='A' if kind!='subjective' else '',
                answer_explanation='analysis',category_name='',document={}))
        snapshot={'questions':questions,'assetMap':{}}
        a=_convert_s02_parts(snapshot,revision='r',source_sha256='0'*64,selected={'lilin-880'})
        self.assertEqual(len(a),1);self.assertEqual(a[0]['book']['part'],'李林880题');self.assertEqual(a[0]['book']['number'],'3')
        b=_convert_s02_parts(snapshot,revision='r',source_sha256='0'*64,selected={'wuzhongxiang-yanxuan'})
        self.assertEqual(b[0]['question_type'],'proof');self.assertEqual(b[0]['answer']['text'],'')
        c=_convert_s02_parts(snapshot,revision='r',source_sha256='0'*64,selected={'cxy-1k'})
        self.assertEqual(c[0]['book']['number'],'5');self.assertIsNone(c[0]['exam_year'])
