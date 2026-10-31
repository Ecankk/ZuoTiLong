from unittest.mock import patch
from app.knowledge import catalog
from app.knowledge.index import snapshot, catalog as learning_catalog
from app.knowledge.profile import aggregate
from app.learning.tasks import capture_input, digest

import copy
import json
import unittest
import test_learning_loop as fixtures
from app.learning.loop import apply_report, submit_probe, assess_attempt, revise_assessment, supplement_attempt, skill_profile, loop_snapshot


class EvidenceProfileTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.LearningLoopTests();self.fixture.setUp();self.conn=self.fixture.conn
        self.fixture.report.update(completion='complete',review={'status':'verified','issues':[]})
        self.fixture.apply()

    def tearDown(self):self.fixture.tearDown()

    def attempt(self,correct):
        aid=submit_probe(self.conn,'paper-test-probe-test',{'response':'visible steps'})['attempt_id']
        assess_attempt(self.conn,aid,{'correct':correct,'feedback':'reviewed actual work','author':'agent'})
        return aid

    def test_assisted_correction_retains_independent_error_without_double_counting_attempt(self):
        aid=self.attempt(False)
        self.conn.execute("INSERT INTO bank_exposures VALUES('bank-test','now')")
        supplement_attempt(self.conn,aid,{'response':'corrected after reading'})
        assess_attempt(self.conn,aid,{'correct':True,'feedback':'assisted work is valid','author':'agent'})
        profile=skill_profile(self.conn)[0]
        self.assertEqual(profile['failures'],3)
        self.assertEqual(profile['independent_probe_successes'],0)
        self.assertEqual(profile['assisted_successes'],1)
        self.assertEqual(profile['attempt_count'],1)
        self.assertEqual(profile['state'],'需要关注')
        self.assertTrue(any(e.get('attempt_id')==aid and e['kind']=='probe_failure' for e in profile['events']))

    def test_regrading_same_work_replaces_interpretation_without_accumulating_outcomes(self):
        aid=self.attempt(False)
        revise_assessment(self.conn,aid,{'correct':True,'feedback':'another valid method','author':'agent'},'reference rechecked')
        profile=skill_profile(self.conn)[0]
        self.assertEqual(profile['failures'],2)
        self.assertEqual(profile['independent_probe_successes'],1)
        self.assertEqual(profile['attempt_count'],1)
        self.assertEqual(profile['state'],'巩固中')

    def test_hypotheses_and_blank_work_do_not_become_definite_weakness(self):
        report=copy.deepcopy(self.fixture.report)
        for q in report['questions']:
            q['correctness']='unknown'
            q['skill_events']=[{'skill_id':'bounds','label':'bounds','kind':'hypothesis'}]
            q['hypotheses']=[{'id':'maybe','label':'possible region issue','evidence':'unclear work','alternative':'not enough time','correction':''}]
        apply_report(self.conn,'paper-test',report,fixtures.ROOT)
        profile=skill_profile(self.conn)[0]
        self.assertEqual(profile['state'],'未覆盖')
        self.assertEqual(profile['failures'],0)
        self.assertEqual(len(profile['hypotheses']),2)

    def test_profile_is_read_only_and_rebuilds_identically(self):
        self.attempt(True)
        before=self.conn.total_changes
        first=skill_profile(self.conn);second=skill_profile(self.conn)
        self.assertEqual(first,second)
        self.assertEqual(before,self.conn.total_changes)
        self.assertEqual(first[0]['state'],'巩固中')

    def test_unverified_exam_analysis_is_traceable_but_not_decisive(self):
        report=copy.deepcopy(self.fixture.report)
        report['review']={'status':'needs_review','issues':['marking needs checking']}
        report['questions'][0]['correctness']='correct'
        report['questions'][0]['skill_events'][0]['kind']='exam_success'
        apply_report(self.conn,'paper-test',report,fixtures.ROOT)
        profile=skill_profile(self.conn)[0]
        self.assertEqual(profile['state'],'未覆盖')
        self.assertEqual((profile['failures'],profile['successes']),(0,0))
        self.assertEqual(profile['pending'],2)
        self.assertEqual(len(profile['events']),2)
        self.assertTrue(all(not e['verified'] for e in profile['events']))
        self.assertEqual(self.conn.execute('SELECT count(*) FROM learning_events').fetchone()[0],2)
        report['review']={'status':'verified','issues':[]}
        apply_report(self.conn,'paper-test',report,fixtures.ROOT)
        profile=skill_profile(self.conn)[0]
        self.assertEqual((profile['failures'],profile['successes']),(1,1))
        self.assertEqual(profile['pending'],0)

    def test_legacy_or_partial_report_cannot_claim_verified_mastery(self):
        for mode in ('legacy','partial'):
            with self.subTest(mode=mode):
                report=copy.deepcopy(self.fixture.report)
                if mode=='legacy':report.pop('review')
                else:report['completion']='partial'
                apply_report(self.conn,'paper-test',report,fixtures.ROOT)
                profile=skill_profile(self.conn)[0]
                self.assertEqual(profile['failures'],0)
                self.assertEqual(profile['pending'],2)

    def test_real_practice_evidence_survives_pending_paper_review(self):
        self.attempt(True)
        report=copy.deepcopy(self.fixture.report)
        report['review']={'status':'needs_review','issues':['paper recheck']}
        apply_report(self.conn,'paper-test',report,fixtures.ROOT)
        profile=skill_profile(self.conn)[0]
        self.assertEqual(profile['failures'],0)
        self.assertEqual(profile['independent_probe_successes'],1)
        self.assertEqual(profile['attempt_count'],1)
        self.assertEqual(profile['state'],'巩固中')

    def test_legacy_answer_match_does_not_count_as_reviewed_reasoning(self):
        aid=submit_probe(self.conn,'paper-test-probe-test',{'response':'2/3'})['attempt_id']
        legacy=json.dumps({'correct':True,'method':'explicit_answer_match','feedback':'matched value'})
        self.conn.execute('UPDATE probe_attempts SET assessment_json=? WHERE id=?',(legacy,aid))
        profile=skill_profile(self.conn)[0]
        self.assertEqual(profile['independent_probe_successes'],0)
        public=loop_snapshot(self.conn)['probes'][0]
        self.assertIsNone(public['attempts'][0]['assessment'])
        self.assertEqual(public['status'],'awaiting_assessment')
        self.assertEqual(self.conn.execute('SELECT assessment_json FROM probe_attempts WHERE id=?',(aid,)).fetchone()[0],legacy)

    def test_success_from_two_papers_supports_only_initial_mastery(self):
        self.attempt(True)
        self.conn.execute("INSERT INTO papers(id,title,created_at) VALUES('paper-two','second','now')")
        self.conn.execute("INSERT INTO questions(id,paper_id,number,created_at) VALUES('q-two','paper-two','1','now')")
        payload=json.dumps({'skill_label':'bounds','accepted':[]})
        self.conn.execute("INSERT INTO diagnostic_probes VALUES('probe-two','paper-two','q-two','bank-test','bounds',?,'awaiting_response','now')",(payload,))
        aid=submit_probe(self.conn,'probe-two',{'response':'independent steps'})['attempt_id']
        assess_attempt(self.conn,aid,{'correct':True,'feedback':'valid work','author':'agent'})
        profile=skill_profile(self.conn)[0]
        self.assertEqual(profile['state'],'初步掌握')
        self.assertEqual(profile['independent_probe_successes'],2)


class ProfileNodeKindTests(unittest.TestCase):
    def evidence(self, scope='concept', kind=None):
        return {'scope_level': scope, 'origin': {} if kind is None else {'node_kind': kind},
            'events': [{'id': f'e-{i}', 'question_id': f'q-{i}', 'paper_id': f'p-{i}',
                        'created_at': f'2026-10-{20+i}', 'source': 'exam',
                        'kind': 'exam_success', 'verified': True} for i in (1, 2)],
            'question_ids': ['q-1', 'q-2'], 'probe_ids': [], 'scopes': [{'paper_id': 'p-1'}, {'paper_id': 'p-2'}]}

    def test_authoritative_kind_prevents_topic_or_parent_mastery_from_two_local_successes(self):
        for kind in ('topic', 'chapter', 'subject'):
            with self.subTest(kind=kind):
                item = self.evidence(kind=kind)
                aggregate(item)
                self.assertEqual(item['state'], '巩固中')
                self.assertIn('整个范围', item['state_reason'])

    def test_published_atom_and_legacy_scope_keep_their_compatible_rules(self):
        cases = [('chapter', 'atom', '初步掌握'), ('concept', None, '初步掌握'), ('chapter', None, '巩固中')]
        for scope, kind, expected in cases:
            with self.subTest(scope=scope, kind=kind):
                item = self.evidence(scope, kind)
                aggregate(item)
                self.assertEqual(item['state'], expected)

    def test_actual_published_tree_preserves_topic_scope_and_never_mutates_evidence(self):
        from test_knowledge_catalog import KnowledgeCatalogTests
        fixture = KnowledgeCatalogTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        value = fixture.value()
        atom = value['nodes'][-1]
        parent = copy.deepcopy(atom)
        parent.update(id='project.composite-differentiation', kind='topic', name='复合函数求导综合范围',
                      aliases=[], source_refs=[])
        atom['parent_id'] = parent['id']
        value['nodes'].append(parent)
        fixture.publish(value)
        before = fixture.conn.total_changes
        first = snapshot(fixture.conn)
        nodes = {n['skill_id']: n for n in first['nodes']}
        self.assertEqual(nodes[parent['id']]['scope_level'], 'topic')
        self.assertEqual(nodes[atom['id']]['scope_level'], 'concept')
        self.assertEqual(nodes[parent['id']]['state'], '未覆盖')
        self.assertEqual(first, snapshot(fixture.conn))
        self.assertEqual(before, fixture.conn.total_changes)


class ProfileTopicRedirectTests(unittest.TestCase):
    def setUp(self):
        from test_knowledge_catalog import KnowledgeCatalogTests
        self.f = KnowledgeCatalogTests(); self.f.setUp(); self.addCleanup(self.f.tearDown)
        self.conn = self.f.conn
        self.first = self.f.publish()

    def merge(self, target):
        doc = copy.deepcopy(catalog.document(self.conn)['document'])
        old_id = doc['nodes'][-1]['id']
        doc['nodes'][-1]['id'] = target
        for row in doc['redirects']:
            if row['target_id'] == old_id: row['target_id'] = target
        doc['redirects'].append({'old_id': old_id, 'target_id': target, 'reason': '同一知识的规范ID，保留历史。'})
        for source in doc['source_resolutions']:
            source['node_ids'] = [target if nid == old_id else nid for nid in source['node_ids']]
        self.f.publish(doc)
        return old_id

    def test_current_profile_lists_all_previous_ids_once_without_copying_nodes_or_alias_names(self):
        before = learning_catalog(self.conn)[-1]
        self.merge('canonical.chain-rule')
        self.merge('canonical.chain-rule.v2')
        value = snapshot(self.conn)
        node = next(n for n in value['nodes'] if n['skill_id'] == 'canonical.chain-rule.v2')
        self.assertEqual(node['previous_ids'], ['GS-04-001', 'canonical.chain-rule'])
        self.assertEqual(node['aliases'], before['aliases'])
        self.assertEqual(node['origin']['definition'], before['origin']['definition'])
        self.assertNotIn('GS-04-001', [n['skill_id'] for n in value['nodes']])
        self.assertEqual(node['events'], [])
        self.assertEqual(node['state'], '未覆盖')

    def test_profile_reads_do_not_change_frozen_task_material_or_register_definition_reads(self):
        self.merge('canonical.chain-rule')
        scope = {'source_version_id': self.f.sid, 'source_ids': ['GS-04-001']}
        before = capture_input(self.conn, self.f.config.root, self.f.data, 'maintain_catalog', None, task_scope=scope)
        changes = self.conn.total_changes
        snapshot(self.conn); snapshot(self.conn)
        after = capture_input(self.conn, self.f.config.root, self.f.data, 'maintain_catalog', None, task_scope=scope)
        self.assertEqual(digest(before), digest(after))
        self.assertEqual(changes, self.conn.total_changes)
        self.assertFalse(any('previous_ids' in n for n in learning_catalog(self.conn)))
        self.assertEqual(self.conn.execute('SELECT count(*) FROM task_reads').fetchone()[0], 0)

    def test_only_the_current_release_contributes_navigation_ids(self):
        self.merge('canonical.chain-rule')
        self.assertEqual(next(n for n in snapshot(self.conn)['nodes'] if n['skill_id'] == 'canonical.chain-rule')['previous_ids'], ['GS-04-001'])
        # A fixture-only historical switch proves rows from other releases do
        # not leak into the projection; no personal database is involved.
        self.conn.execute('UPDATE knowledge_catalog_state SET release_id=? WHERE singleton=1', (self.first['id'],))
        self.assertTrue(all(n['previous_ids'] == [] for n in snapshot(self.conn)['nodes']))
        self.assertIn('GS-04-001', [n['skill_id'] for n in snapshot(self.conn)['nodes']])

    def test_legacy_outline_without_a_published_catalogue_keeps_normal_navigation(self):
        self.conn.execute('DELETE FROM knowledge_catalog_state')
        value = snapshot(self.conn)
        self.assertTrue(value['nodes'])
        self.assertTrue(all(n['previous_ids'] == [] for n in value['nodes']))

    def test_navigation_uses_the_same_release_as_the_nodes_if_a_new_catalogue_is_published_between_reads(self):
        self.merge('canonical.chain-rule')
        captured_nodes = learning_catalog(self.conn)
        doc = copy.deepcopy(catalog.document(self.conn)['document'])
        doc['redirects'].append({'old_id': 'external.historical-id', 'target_id': 'canonical.chain-rule',
                                 'reason': '较晚版本补登记的历史ID，仅用于验证版本边界。'})
        self.f.publish(doc)
        with patch('app.knowledge.index.catalog', return_value=captured_nodes):
            projected = snapshot(self.conn)
        node = next(n for n in projected['nodes'] if n['skill_id'] == 'canonical.chain-rule')
        self.assertEqual(node['previous_ids'], ['GS-04-001'])
        current = next(n for n in snapshot(self.conn)['nodes'] if n['skill_id'] == 'canonical.chain-rule')
        self.assertEqual(current['previous_ids'], ['GS-04-001', 'external.historical-id'])


if __name__ == '__main__':
    unittest.main()
