import copy
import unittest
from app.knowledge import catalog


class CatalogueSearchTests(unittest.TestCase):
    def setUp(self):
        from test_question_annotations import QuestionPreparationTests
        self.f=QuestionPreparationTests();self.f.setUp();self.addCleanup(self.f.tearDown)
        self.conn=self.f.conn
        value=self.f.f.value();template=value['nodes'][-1]
        atoms=[('demo.joint','二维连续型随机变量的联合密度条件','联合密度非负，积分为一。',['联合密度']),
               ('demo.probability','连续型联合分布的区域概率积分','区域概率是联合密度在事件区域上的二重积分。',['区域概率']),
               ('demo.integral','二重积分的极坐标变换','坐标变换时保留面积元。',['极坐标'])]
        ids=[]
        for id,name,definition,aliases in atoms:
            node=copy.deepcopy(template);node.update(id=id,name=name,definition=definition,aliases=aliases)
            value['nodes'].append(node);ids.append(id)
        value['source_resolutions'][0]['node_ids']+=ids
        self.release=self.f.f.publish(value)['id'];self.conn.commit()

    def test_reported_multi_concept_query_recalls_existing_atoms_instead_of_a_false_gap(self):
        self.f.seed_questions();self.f.start('annotate_questions',{'bank_ids':['math1-2020-01']})
        result=self.f.tool('task_context',{'knowledge_query':{'query':'二维连续型随机变量 独立随机变量 联合概率密度 事件概率 二重积分 区域积分','kinds':['atom'],'limit':30}})
        ids={n['id'] for n in result['items']}
        self.assertIn('demo.joint',ids);self.assertIn('demo.probability',ids);self.assertIn('demo.integral',ids)
        self.assertEqual(result['match_mode'],'any_term')
        read=self.f.tool('task_context',{'topic_ids':['demo.joint','demo.probability']})
        self.assertEqual({n['id'] for n in read['nodes']},{'demo.joint','demo.probability'})

    def test_single_phrase_and_exact_ids_keep_normalized_lookup(self):
        result=catalog.search(self.conn,query='连续型联合分布的区域概率积分',kinds=['atom'])
        self.assertEqual([n['id'] for n in result['items']],['demo.probability'])
        result=catalog.search(self.conn,query='DEMO.JOINT',kinds=['atom'])
        self.assertEqual([n['id'] for n in result['items']],['demo.joint'])

    def test_tool_navigation_keeps_candidates_without_full_definition_or_read_credit(self):
        self.f.seed_questions();self.f.start('annotate_questions',{'bank_ids':['math1-2020-01']})
        query={'query':'联合密度 | 极坐标','kinds':['atom'],'offset':1,'limit':1}
        raw=catalog.search(self.conn,**query)
        result=self.f.tool('task_context',{'knowledge_query':query})
        self.assertEqual(result['projection'],'navigation')
        self.assertEqual(result['total'],raw['total'])
        self.assertEqual([n['id'] for n in result['items']],[n['id'] for n in raw['items']])
        self.assertEqual(result['items'][0]['aliases'],raw['items'][0]['aliases'])
        self.assertIn('definition',raw['items'][0])
        for node in result['items']:
            self.assertFalse({'definition','conditions','boundaries','source_refs','review_note'}&set(node))
        self.assertEqual(self.conn.execute("SELECT count(*) FROM task_reads WHERE kind='knowledge_definition'").fetchone()[0],0)
        actual=self.f.tool('task_context',{'topic_ids':[result['items'][0]['id']]})
        self.assertEqual(actual['nodes'][0]['definition'],raw['items'][0]['definition'])
        self.assertEqual(self.conn.execute("SELECT count(*) FROM task_reads WHERE kind='knowledge_definition'").fetchone()[0],1)

    def test_bad_definition_batch_reports_full_bad_id_without_partial_read_credit(self):
        self.f.seed_questions();self.f.start('annotate_questions',{'bank_ids':['math1-2020-01']})
        with self.assertRaisesRegex(ValueError,'truncated.source-id'):
            self.f.tool('task_context',{'topic_ids':['demo.joint','truncated.source-id']})
        self.assertEqual(self.conn.execute("SELECT count(*) FROM task_reads WHERE kind='knowledge_definition'").fetchone()[0],0)
        actual=self.f.tool('task_context',{'topic_ids':['demo.joint']})
        self.assertEqual(actual['nodes'][0]['id'],'demo.joint')
        self.assertIn('definition',actual['nodes'][0])

    def test_union_is_deduplicated_filtered_then_paginated(self):
        result=catalog.search(self.conn,query='联合密度 | 联合密度、极坐标',parent_id='math1.calculus.differentiation',kinds=['atom'],offset=1,limit=1)
        self.assertEqual(result['total'],3);self.assertEqual(len(result['items']),1)
        self.assertEqual(result['query_terms'],['联合密度','极坐标'])
        self.assertEqual(result['release_id'],self.release)
        self.assertEqual(catalog.search(self.conn,query='联合密度',kinds=['chapter'])['total'],0)
        with self.assertRaisesRegex(ValueError,'父节点'):catalog.search(self.conn,query='联合密度',parent_id='missing')

    def test_unknown_query_stays_empty_and_malformed_query_is_rejected(self):
        self.assertEqual(catalog.search(self.conn,query='确实不存在的目录字串')['total'],0)
        for bad in (None,True,[],{},'x'*2001,' '.join('term'+str(i) for i in range(21))):
            with self.subTest(bad_type=type(bad).__name__),self.assertRaises(ValueError):catalog.search(self.conn,query=bad)

    def merge_ids(self, redirects):
        value=copy.deepcopy(catalog.document(self.conn)['document'])
        value['nodes']=[n for n in value['nodes'] if n['id'] not in redirects]
        value['redirects'] += [{'old_id':old,'target_id':target,'reason':'已审核的同义考点归一。'}
                               for old,target in redirects.items()]
        for item in value['source_resolutions']:
            item['node_ids']=sorted({redirects.get(t,t) for t in item['node_ids']})
        self.f.f.publish(value);self.conn.commit()

    def test_merged_id_recalls_canonical_node_without_copied_alias_text(self):
        self.merge_ids({'demo.joint':'demo.probability'})
        result=catalog.search(self.conn,query='DEMO.JOINT',kinds=['atom'])
        self.assertEqual([n['id'] for n in result['items']],['demo.probability'])
        self.assertEqual(result['resolved_query_ids'],['demo.probability'])
        # A current-version redirect must not alter a historical query.
        old=catalog.search(self.conn,query='demo.joint',release_id=self.release)
        self.assertEqual([n['id'] for n in old['items']],['demo.joint'])
        self.assertEqual(old['resolved_query_ids'],[])

    def test_merged_ids_obey_kind_parent_union_and_pagination_filters(self):
        self.merge_ids({'demo.joint':'demo.probability'})
        result=catalog.search(self.conn,query='demo.joint demo.probability | 极坐标',kinds=['atom'],offset=1,limit=1)
        self.assertEqual(result['total'],2)
        self.assertEqual([n['id'] for n in result['items']],['demo.probability'])
        self.assertEqual(catalog.search(self.conn,query='demo.joint',kinds=['chapter'])['total'],0)
        self.assertEqual(catalog.search(self.conn,query='demo.joint',parent_id='math1.probability')['total'],0)

    def test_merged_parent_is_scoped_to_its_current_target(self):
        self.merge_ids({'demo.joint':'demo.probability'})
        current=catalog.search(self.conn,parent_id='demo.joint')
        self.assertEqual([n['id'] for n in current['items']],['demo.probability'])
        historical=catalog.search(self.conn,parent_id='demo.joint',release_id=self.release)
        self.assertEqual([n['id'] for n in historical['items']],['demo.joint'])

    def test_historical_id_resolution_keeps_significant_punctuation(self):
        value=copy.deepcopy(catalog.document(self.conn)['document'])
        value['redirects'] += [
            {'old_id':'old.a-b','target_id':'demo.joint','reason':'固定来源中的旧编号。'},
            {'old_id':'old.ab','target_id':'demo.probability','reason':'另一来源的不同旧编号。'}]
        self.f.f.publish(value);self.conn.commit()
        for old,target in [('old.a-b','demo.joint'),('old.ab','demo.probability')]:
            result=catalog.search(self.conn,query=old)
            self.assertEqual([n['id'] for n in result['items']],[target])


if __name__=='__main__':unittest.main()
