import copy
import json
import unittest
import uuid

from app.bank import annotations
from app.knowledge import catalog
from app.knowledge.maintenance import normalize_scope, guard
from app.learning.tasks import create_task, finish_task, receipt, retry_task, bind_turn, task_package
from app.learning.workflows import enqueue


class AnnotationRevisionTests(unittest.TestCase):
    def setUp(self):
        from test_question_annotations import QuestionPreparationTests
        self.f = QuestionPreparationTests(); self.f.setUp(); self.addCleanup(self.f.tearDown)
        self.conn, self.root, self.data = self.f.conn, self.f.root, self.f.data
        self.ids = self.f.save_annotation()
        self.base = annotations.current(self.conn, self.data, self.ids[0])

    def scope(self, fields=None, ids=None):
        ids = self.ids if ids is None else ids
        return {'bank_ids': ids, 'revision': {
            'expected_annotations': {bid: annotations.current(self.conn, self.data, bid)['id'] for bid in ids},
            'allowed_fields': fields or ['reference_reasoning']}}

    def start(self, fields=None, ids=None):
        self.f.start('annotate_questions', self.scope(fields, ids))
        self.inputs = json.loads(self.f.task['input_json'])
        return self.inputs

    def payload(self):
        return self.f.envelope({'summary': 'Revise only the frozen fields.', 'limitations': [],
            'questions': [copy.deepcopy(q['revision_base']['analysis']) for q in self.inputs['bank_questions']]})

    def read(self):
        for source in self.inputs['bank_questions']:
            self.f.tool('read_bank', {'bank_id': source['bank_id'], 'role': 'all'})
        ids = sorted({catalog.resolve(self.conn, b['topic_id'], self.inputs['catalog_revision'])
                      for q in self.inputs['bank_questions'] for b in q['revision_base']['analysis']['bindings']})
        self.f.tool('task_context', {'topic_ids': ids})

    def save(self, payload):
        result = self.f.tool('apply_report', {'result': payload})
        finish_task(self.conn, self.f.task['id']); self.conn.commit()
        return result

    def test_plain_annotation_scopes_and_old_rule_inputs_get_no_revision_defaults(self):
        scope = {'bank_ids': self.ids}
        self.assertEqual(normalize_scope('annotate_questions', scope), scope)
        for version in annotations.SUPPORTED_RULE_REVISIONS:
            value = annotations.capture(self.conn, self.data, scope, rule_revision=version)
            self.assertNotIn('revision', value['task_scope'])
            self.assertTrue(all('revision_base' not in q for q in value['bank_questions']))

    def test_analysis_context_is_bounded_and_does_not_count_as_reading_the_current_materials(self):
        self.start()
        invalid = [None, [], [self.ids[0]] * 2, ['outside-batch'], self.ids, 'math1-2020-01', [None]]
        for bids in invalid:
            with self.subTest(bids=bids), self.assertRaises(ValueError):
                annotations.analysis_context(self.inputs, bids)
        context = self.f.tool('task_context', {'bank_ids': [self.ids[0]]})
        self.assertEqual(context['questions'][0]['revision_base'], self.inputs['bank_questions'][0]['revision_base'])
        self.assertNotIn('materials', context['questions'][0])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM task_reads WHERE task_id=?', (self.f.task['id'],)).fetchone()[0], 0)
        with self.assertRaisesRegex(ValueError, '尚未读取'): self.f.tool('apply_report', {'result': self.payload()})

    def test_baseline_is_frozen_visible_and_repeated_delivery_is_idempotent(self):
        self.start(); value = self.payload()
        manifest = task_package(self.conn, self.f.task['id'])
        self.assertEqual(manifest['input']['task_scope'], self.inputs['task_scope'])
        self.assertIn('revision_base', manifest['questions'][0]['available_context'])
        context = self.f.tool('task_context', {'bank_ids': [self.inputs['bank_questions'][0]['bank_id']]})
        self.assertEqual(context['questions'][0]['revision_base'], self.inputs['bank_questions'][0]['revision_base'])
        value['result']['questions'][0]['reference_reasoning'] += ' 用完整分隔符说明：\\(2x\\cos(x^2)\\)。'
        with self.assertRaises(ValueError): self.f.tool('apply_report', {'result': value})
        self.read()
        first = self.f.tool('apply_report', {'result': value})
        repeated = self.f.tool('apply_report', {'result': value})
        self.assertEqual(first['result_id'], repeated['result_id']); self.assertTrue(repeated['reused'])
        finish_task(self.conn, self.f.task['id']); self.conn.commit()
        current = annotations.current(self.conn, self.data, self.ids[0])
        self.assertNotEqual(current['id'], self.base['id'])
        for key, old in self.base['analysis'].items():
            if key != 'reference_reasoning': self.assertEqual(current['analysis'][key], old)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM question_annotations').fetchone()[0], 2)
        for name in ('learning_events', 'probe_attempts', 'bank_views', 'bank_exposures'):
            self.assertEqual(self.conn.execute('SELECT count(*) FROM ' + name).fetchone()[0], 0)

    def test_ungranted_retagging_and_other_payload_edits_are_rejected_without_receipts(self):
        self.start(); self.read(); base = self.payload()
        cases = [
            ('bindings', lambda q: q['bindings'][0].update(evidence='Unrequested retagging')),
            ('methods', lambda q: q.update(methods=['Unrequested method'])),
            ('fingerprint', lambda q: q['fingerprint'].update(goal='Different task')),
            ('answer_check.note', lambda q: q['answer_check'].update(note='Changed note')),
        ]
        for field, edit in cases:
            value = copy.deepcopy(base); edit(value['result']['questions'][0])
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, '未授权字段'):
                self.f.tool('apply_report', {'result': value})
            self.assertIsNone(receipt(self.conn, self.f.task['id']))
            self.assertEqual(self.conn.execute('SELECT count(*) FROM question_annotations').fetchone()[0], 1)
        self.save(base)

    def test_explicit_binding_revision_preserves_the_verified_derivation(self):
        self.start(['bindings']); self.read(); value = self.payload()
        value['result']['questions'][0]['bindings'][0]['stages'] = ['formula']
        self.save(value)
        current = annotations.current(self.conn, self.data, self.ids[0])['analysis']
        self.assertEqual(current['reference_reasoning'], self.base['analysis']['reference_reasoning'])
        self.assertEqual(current['bindings'][0]['stages'], ['formula'])

    def test_discovered_conflict_can_downgrade_without_forcing_ready(self):
        self.start(); self.read(); value = self.payload(); item = value['result']['questions'][0]
        item.update(status='needs_review', limitations=['The reference contains a newly observed conflicting step.'])
        item['answer_check'] = {'status': 'conflict', 'note': 'A concrete inconsistency was found in this isolated reference.'}
        self.save(value)
        self.assertEqual(annotations.current(self.conn, self.data, self.ids[0])['analysis']['status'], 'needs_review')
        self.assertEqual(annotations.search(self.conn, self.data, topic_ids=['GS-04-001'])['total'], 0)

    def test_unsupported_downgrade_has_no_silent_pool_effect(self):
        self.start(); self.read(); value = self.payload()
        value['result']['questions'][0]['status'] = 'needs_review'
        with self.assertRaisesRegex(ValueError, '具体限制'): self.f.tool('apply_report', {'result': value})
        self.assertEqual(annotations.current(self.conn, self.data, self.ids[0])['id'], self.base['id'])
        value['result']['questions'][0].update(status='needs_catalog', limitations=['Missing concept.'])
        with self.assertRaisesRegex(ValueError, '未匹配'): self.f.tool('apply_report', {'result': value})

    def test_each_requested_alias_base_is_checked_before_alias_deduplication(self):
        scope = self.scope(); scope['revision']['expected_annotations'][self.ids[1]] = 'annotation-stale'
        with self.assertRaisesRegex(ValueError, '修订基线'): annotations.capture(self.conn, self.data, scope)

    def test_alias_delivery_uses_its_own_identity_and_keeps_the_same_verified_knowledge(self):
        self.start(ids=[self.ids[1]]); self.read(); value = self.payload()
        source = self.inputs['bank_questions'][0]
        self.assertEqual(source['revision_base']['source_bank_id'], self.ids[0])
        self.assertEqual(value['result']['questions'][0]['bank_id'], self.ids[1])
        value['result']['questions'][0]['reference_reasoning'] += ' Alias-specific formatting.'
        self.save(value)
        current = annotations.current(self.conn, self.data, self.ids[1])
        self.assertEqual(current['analysis']['bindings'], self.base['analysis']['bindings'])
        self.assertEqual(current['id'], annotations.current(self.conn, self.data, self.ids[0])['id'])

    def test_changed_material_or_definition_invalidates_the_base_instead_of_replacing_it(self):
        self.start(); self.read(); value = self.payload()
        self.conn.execute('UPDATE bank_questions SET explanation=? WHERE id=?', ('A different reference.', self.ids[0]))
        self.conn.commit()
        with self.assertRaises(ValueError): self.f.tool('apply_report', {'result': value})
        self.assertIsNone(receipt(self.conn, self.f.task['id']))

    def test_related_definition_change_rejects_delivery_against_the_old_base(self):
        self.start(); self.read(); value = self.payload()
        doc = copy.deepcopy(catalog.document(self.conn)['document'])
        next(n for n in doc['nodes'] if n['id'] == 'GS-04-001')['conditions'].append('A changed mathematical condition for this isolated test.')
        self.f.f.publish(doc)
        self.conn.commit()
        with self.assertRaises(ValueError): self.f.tool('apply_report', {'result': value})
        self.assertIsNone(receipt(self.conn, self.f.task['id']))

    def test_stale_annotation_id_is_rejected_without_creating_a_new_task(self):
        scope = self.scope()
        self.f.start('annotate_questions', {'bank_ids': self.ids}); self.f.read_annotation_material()
        self.f.tool('apply_report', {'result': self.f.envelope(self.f.annotation_result())})
        finish_task(self.conn, self.f.task['id']); self.conn.commit()
        count = self.conn.execute('SELECT count(*) FROM learning_tasks').fetchone()[0]
        with self.assertRaisesRegex(ValueError, '修订基线'):
            create_task(self.conn, self.root, self.data, 'annotate_questions', None, 'same-session', str(uuid.uuid4()), task_scope=scope)
        self.assertEqual(count, self.conn.execute('SELECT count(*) FROM learning_tasks').fetchone()[0])

    def test_retry_preserves_the_exact_baseline_and_scope(self):
        self.start(); original = self.f.task['input_revision']
        retried = retry_task(self.conn, self.root, self.data, self.f.task['id'])
        self.assertEqual(retried['input_revision'], original)
        self.assertEqual(json.loads(retried['input_json']), self.inputs)
        bind_turn(self.conn, retried['id'], 'same-session', retried['run_token'], 'revision-retry')
        self.f.task = retried; self.f.lease.update(run_token=retried['run_token'], turn_id='revision-retry')
        self.conn.commit()
        self.read(); self.save(self.payload())

    def test_queue_guards_freeze_bases_and_do_not_merge_different_field_grants(self):
        scope = self.scope(); expected = guard(self.conn, self.data, 'annotate_questions', scope)
        self.assertTrue(expected['revision_bases'])
        first = enqueue(self.conn, self.root, self.data, 'annotate_questions', None, str(uuid.uuid4()), task_scope=scope)
        same = enqueue(self.conn, self.root, self.data, 'annotate_questions', None, str(uuid.uuid4()), task_scope=scope)
        other_scope = self.scope(['limitations'])
        other = enqueue(self.conn, self.root, self.data, 'annotate_questions', None, str(uuid.uuid4()), task_scope=other_scope)
        self.assertEqual(first['id'], same['id']); self.assertNotEqual(first['id'], other['id'])
        with self.assertRaises(ValueError):
            enqueue(self.conn, self.root, self.data, 'annotate_questions', None, first['request_id'], task_scope=other_scope)

    def test_malformed_revision_scopes_and_identity_grants_are_rejected(self):
        good = self.scope()['revision']
        cases = [None, {}, {'expected_annotations': {}, 'allowed_fields': ['reference_reasoning']},
                 {**good, 'allowed_fields': []}, {**good, 'allowed_fields': ['status']},
                 {**good, 'allowed_fields': ['bank_id']}, {**good, 'allowed_fields': ['reference_reasoning'] * 2},
                 {**good, 'expected_annotations': {bid: None for bid in self.ids}}, {**good, 'extra': True}]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_scope('annotate_questions', {'bank_ids': self.ids, 'revision': value})

    def test_historical_binding_ids_are_preserved_but_resolved_to_read_canonical_definitions(self):
        doc = copy.deepcopy(catalog.document(self.conn)['document'])
        next(n for n in doc['nodes'] if n['id'] == 'GS-04-001')['id'] = 'canonical.chain-rule'
        doc['redirects'].append({'old_id': 'GS-04-001', 'target_id': 'canonical.chain-rule', 'reason': 'A confirmed same-definition merge.'})
        doc['source_resolutions'][0]['node_ids'] = ['canonical.chain-rule']
        self.f.f.publish(doc)
        self.conn.commit()
        self.start(); self.read(); value = self.payload()
        self.assertEqual(value['result']['questions'][0]['bindings'][0]['topic_id'], 'GS-04-001')
        self.save(value)
        self.assertEqual(annotations.current(self.conn, self.data, self.ids[0])['analysis']['bindings'][0]['topic_id'], 'GS-04-001')

    def test_historical_merged_bindings_can_be_preserved_without_adding_a_duplicate(self):
        doc = copy.deepcopy(catalog.document(self.conn)['document'])
        old = next(n for n in doc['nodes'] if n['id'] == 'GS-04-001')
        extra = copy.deepcopy(old); extra.update(id='isolated.chain-rule', name='Isolated old chain-rule concept', aliases=[])
        doc['nodes'].append(extra)
        doc['source_resolutions'][0]['node_ids'].append(extra['id'])
        self.f.f.publish(doc); self.conn.commit()
        self.f.start('annotate_questions', {'bank_ids': self.ids})
        value = self.f.envelope(self.f.annotation_result())
        binding = copy.deepcopy(value['result']['questions'][0]['bindings'][0]); binding['topic_id'] = extra['id']
        value['result']['questions'][0]['bindings'].append(binding)
        self.f.read_annotation_material(); self.f.tool('task_context', {'topic_ids': [extra['id']]})
        self.f.tool('apply_report', {'result': value}); finish_task(self.conn, self.f.task['id']); self.conn.commit()
        doc = copy.deepcopy(catalog.document(self.conn)['document'])
        canonical = copy.deepcopy(old); canonical['id'] = 'canonical.chain-rule'
        merged = {'GS-04-001', extra['id']}
        doc['nodes'] = [n for n in doc['nodes'] if n['id'] not in merged] + [canonical]
        doc['redirects'].extend({'old_id': tid, 'target_id': canonical['id'], 'reason': 'Confirmed same-definition merge.'} for tid in sorted(merged))
        doc['source_resolutions'][0]['node_ids'] = [canonical['id']]
        self.f.f.publish(doc); self.conn.commit()
        self.start(['bindings', 'reference_reasoning']); self.read(); value = self.payload()
        self.assertEqual(len(value['result']['questions'][0]['bindings']), 2)
        forged = copy.deepcopy(value)
        forged['result']['questions'][0]['bindings'][1]['topic_id'] = canonical['id']
        with self.assertRaisesRegex(ValueError, '重复'): self.f.tool('apply_report', {'result': forged})
        value['result']['questions'][0]['reference_reasoning'] += ' Formatting only.'
        self.save(value)
        self.assertEqual(annotations.current(self.conn, self.data, self.ids[0])['analysis']['bindings'], value['result']['questions'][0]['bindings'])

    def test_saved_revision_can_finish_after_transport_retry_without_recapturing_its_base(self):
        self.start(); self.read(); value = self.payload()
        value['result']['questions'][0]['reference_reasoning'] += ' Frozen correction.'
        first = self.f.tool('apply_report', {'result': value})
        retried = retry_task(self.conn, self.root, self.data, self.f.task['id'])
        bind_turn(self.conn, retried['id'], 'same-session', retried['run_token'], 'saved-retry')
        self.conn.commit(); self.f.task = retried
        self.f.lease.update(run_token=retried['run_token'], turn_id='saved-retry')
        again = self.f.tool('apply_report', {'result': value})
        self.assertTrue(again['reused']); self.assertEqual(first['result_id'], again['result_id'])
        finish_task(self.conn, self.f.task['id']); self.conn.commit()
        self.assertEqual(self.conn.execute('SELECT count(*) FROM question_annotations').fetchone()[0], 2)

    def test_multiple_question_revision_rolls_back_every_projection_if_second_item_exceeds_its_grant(self):
        other = 'math3-2020-02'
        self.conn.execute('''INSERT INTO bank_questions(id,source,stem,answer,explanation,created_at)
            VALUES(?,?,?,?,?,?)''', (other, 'isolated-synthetic', '求 sin(x²) 的导数并解释链式法则。',
                                    '2x cos(x²)', '外层导数乘内层导数。', 'now'))
        from app.bank.access import init_access
        init_access(self.conn); self.conn.commit()
        self.f.start('annotate_questions', {'bank_ids': [other]}); self.f.read_annotation_material()
        self.f.tool('apply_report', {'result': self.f.envelope(self.f.annotation_result())})
        finish_task(self.conn, self.f.task['id']); self.conn.commit()
        self.start(ids=[self.ids[0], other]); self.read(); value = self.payload()
        tables = ('learning_results', 'question_annotations', 'question_annotation_links',
                  'question_annotation_topics', 'prepared_annotation_ids')
        before = {t: [tuple(r) for r in self.conn.execute('SELECT rowid,* FROM ' + t + ' ORDER BY rowid')] for t in tables}
        value['result']['questions'][0]['reference_reasoning'] += ' Permitted first change.'
        value['result']['questions'][1]['methods'].append('Unrequested second change')
        with self.assertRaisesRegex(ValueError, '未授权字段'): self.f.tool('apply_report', {'result': value})
        for table, rows in before.items():
            self.assertEqual([tuple(r) for r in self.conn.execute('SELECT rowid,* FROM ' + table + ' ORDER BY rowid')], rows)
        self.assertIsNone(receipt(self.conn, self.f.task['id']))
        value['result']['questions'][1] = copy.deepcopy(self.inputs['bank_questions'][1]['revision_base']['analysis'])
        self.save(value)
