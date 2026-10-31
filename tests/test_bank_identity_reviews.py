import copy
import json
import sqlite3
import threading
import unittest
import uuid
from unittest.mock import Mock

from fastapi.testclient import TestClient
from app.bank import annotations, identity_reviews
from app.bank.access import aliases, access, init_access, record_view, save_preferences
from app.knowledge.catalog import digest
from app.learning.tasks import finish_task
from app.main import create_app
from app.services.library import LibraryService
from app.storage.database import Database
from app.agent.errors import BridgeConflict


class BankIdentityReviewTests(unittest.TestCase):
    def setUp(self):
        from test_question_annotations import QuestionPreparationTests
        self.f = QuestionPreparationTests();self.f.setUp();self.addCleanup(self.f.tearDown)
        self.f.prepare_catalog()
        self.conn, self.data, self.config = self.f.conn, self.f.data, self.f.f.config
        self.ids = ['math1-2020-01', 'math3-2020-01', 'math2-2020-01']
        for bid in self.ids:
            self.conn.execute('''INSERT INTO bank_questions(id,source,stem,answer,explanation,created_at)
                VALUES(?,?,?,?,?,'now')''', (bid, 'isolated-synthetic', bid + ': 求sin(x²)的导数。',
                    '2x cos(x²)', '参考' + bid + '：先求外层sin导数，再乘2x。'))
        init_access(self.conn);self.conn.commit()
        self.service = LibraryService(self.config, Database(self.config))

    def preview(self, operation='confirm', pair=None):
        pair = pair or self.ids[:2]
        return self.service.preview_identity({'left_id': pair[0], 'right_id': pair[1], 'operation': operation})

    def body(self, operation='confirm', pair=None):
        p = self.preview(operation, pair)
        return {'left_id': p['left_id'], 'right_id': p['right_id'], 'operation': operation,
                'request_id': str(uuid.uuid4()), 'expected_preview_sha256': p['preview_sha256'],
                'reason': '逐一核对同一复合函数、求导目标和条件；不同出处的参考另行检查。', 'confirmed': True}

    def save_annotations(self, ids):
        self.f.start('annotate_questions', {'bank_ids': ids})
        inputs = json.loads(self.f.task['input_json'])
        template = self.f.annotation_result()
        value = {**template, 'questions': []}
        for source in inputs['bank_questions']:
            item = copy.deepcopy(template['questions'][0])
            item.update(bank_id=source['bank_id'], content_revision=source['content_revision'],
                        material_revision=source['material_revision'])
            self.f.tool('read_bank', {'bank_id': source['bank_id'], 'role': 'all'})
            value['questions'].append(item)
        self.f.tool('task_context', {'topic_ids': ['GS-04-001']})
        self.f.tool('apply_report', {'result': self.f.envelope(value)})
        finish_task(self.conn, self.f.task['id']);self.conn.commit()

    def test_preview_is_read_only_and_contains_no_question_or_solution(self):
        before = self.conn.total_changes
        value = self.preview()
        self.assertEqual(self.conn.total_changes, before)
        self.assertFalse(value['reference_materials_identical'])
        encoded = json.dumps(value, ensure_ascii=False)
        self.assertNotIn('sin', encoded);self.assertNotIn('cos', encoded)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM bank_identity_reviews').fetchone()[0], 0)

    def test_confirm_and_revoke_preserve_history_and_learner_evidence(self):
        body = self.body();confirmed = self.service.review_identity(body)
        self.assertEqual(aliases(self.conn, self.ids[0]), set(self.ids[:2]))
        self.assertFalse(confirmed['reference_quality_inherited'])
        revoked = self.service.review_identity(self.body('revoke'))
        self.assertFalse(revoked['currently_confirmed'])
        self.assertEqual(aliases(self.conn, self.ids[0]), {self.ids[0]})
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM bank_identity_reviews').fetchone()[0], 2)
        for table in ('probe_attempts', 'learning_events', 'bank_views', 'bank_exposures'):
            self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0], 0)

    def test_network_retry_after_later_revoke_does_not_restore_confirmation(self):
        body = self.body();first = self.service.review_identity(body)
        self.assertTrue(self.service.review_identity(body)['reused'])
        self.service.review_identity(self.body('revoke'))
        replay = self.service.review_identity(body)
        self.assertEqual(replay['review_id'], first['review_id'])
        self.assertTrue(replay['reused']);self.assertFalse(replay['still_current'])
        self.assertFalse(replay['currently_confirmed'])
        self.assertEqual(aliases(self.conn, self.ids[0]), {self.ids[0]})
        with self.assertRaisesRegex(ValueError, '同一同题维护请求'):
            self.service.review_identity({**body, 'reason': '换一份说明不允许覆盖原先记录。'})

    def test_material_change_between_preview_and_confirm_rejects_without_write(self):
        body = self.body()
        self.conn.execute('UPDATE bank_questions SET answer=? WHERE id=?', ('changed reference', self.ids[1]));self.conn.commit()
        with self.assertRaisesRegex(ValueError, '已变化'):
            self.service.review_identity(body)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM bank_identity_reviews').fetchone()[0], 0)

    def test_related_graph_change_requires_a_new_preview(self):
        body = self.body()
        self.service.review_identity(self.body(pair=self.ids[1:]))
        with self.assertRaisesRegex(ValueError, '已变化'):
            self.service.review_identity(body)
        self.assertEqual(aliases(self.conn, self.ids[0]), {self.ids[0]})

    def test_new_registered_question_text_invalidates_confirmation(self):
        body = self.body();self.service.review_identity(body)
        self.conn.execute('UPDATE bank_questions SET stem=? WHERE id=?', ('新的题目条件，不能继承旧同题。', self.ids[1]));self.conn.commit()
        self.assertEqual(aliases(self.conn, self.ids[0]), {self.ids[0]})
        replay = self.service.review_identity(body)
        self.assertTrue(replay['reused']);self.assertFalse(replay['still_current'])

    def test_registered_pixel_version_change_invalidates_but_reference_change_does_not(self):
        for bid, sha in zip(self.ids[:2], ('first-pixels', 'second-pixels')):
            self.conn.execute('UPDATE bank_identity SET sha256=? WHERE bank_id=?', (sha, bid))
        self.conn.commit();self.service.review_identity(self.body())
        self.conn.execute('UPDATE bank_questions SET explanation=? WHERE id=?', ('另一版解析须单独核验。', self.ids[1]));self.conn.commit()
        self.assertEqual(aliases(self.conn, self.ids[0]), set(self.ids[:2]))
        self.conn.execute('UPDATE bank_identity SET sha256=? WHERE bank_id=?', ('new-pixels', self.ids[1]));self.conn.commit()
        self.assertEqual(aliases(self.conn, self.ids[0]), {self.ids[0]})

    def test_generated_navigation_change_preserves_same_registered_pixels(self):
        for bid, sha in zip(self.ids[:2], ('first-pixels', 'second-pixels')):
            self.conn.execute('UPDATE bank_identity SET sha256=? WHERE bank_id=?', (sha, bid))
        self.conn.commit();self.service.review_identity(self.body())
        self.conn.execute('UPDATE bank_questions SET stem=? WHERE id=?', ('新的题源导航，原图未改。', self.ids[1]));self.conn.commit()
        self.assertEqual(aliases(self.conn, self.ids[0]), set(self.ids[:2]))

    def test_legacy_link_is_audited_before_revoke(self):
        reason = '旧的人工确认依据，必须随撤回保留。'
        self.conn.execute('INSERT INTO bank_links VALUES(?,?,?)', (*self.ids[:2], reason));self.conn.commit()
        self.service.review_identity(self.body('revoke'))
        saved = self.conn.execute('SELECT before_json FROM bank_identity_reviews').fetchone()[0]
        self.assertEqual(json.loads(saved)['legacy_edges'][0]['reason'], reason)
        self.assertEqual(aliases(self.conn, self.ids[0]), {self.ids[0]})

    def test_revoke_one_edge_does_not_erase_other_transitive_proofs(self):
        self.service.review_identity(self.body())
        self.service.review_identity(self.body(pair=self.ids[1:]))
        self.service.review_identity(self.body(pair=(self.ids[0], self.ids[2])))
        self.service.review_identity(self.body('revoke'))
        self.assertEqual(aliases(self.conn, self.ids[0]), set(self.ids))

    def test_reserved_alias_excludes_the_group_and_revoke_splits_it(self):
        save_preferences(self.conn, {'study_type': 1, 'reserved': [{'math_type': 1, 'year': '2020'}]});self.conn.commit()
        self.service.review_identity(self.body())
        self.assertTrue(access(self.conn, self.ids[1])['reserved'])
        self.service.review_identity(self.body('revoke'))
        self.assertFalse(access(self.conn, self.ids[1])['reserved'])

    def test_existing_solution_exposure_is_shared_without_copying_or_success(self):
        record_view(self.conn, self.ids[0], 'analysis');self.conn.commit()
        before = [tuple(r) for r in self.conn.execute('SELECT * FROM bank_views')]
        self.service.review_identity(self.body())
        self.assertEqual([tuple(r) for r in self.conn.execute('SELECT * FROM bank_views')], before)
        self.assertTrue(access(self.conn, self.ids[1])['analysis_allowed'])
        self.service.review_identity(self.body('revoke'))
        self.assertFalse(access(self.conn, self.ids[1])['analysis_allowed'])

    def test_revoked_alias_cannot_inherit_former_sources_annotation(self):
        self.conn.execute('UPDATE bank_questions SET explanation=? WHERE id=?', ('完全相同的参考推导。', self.ids[0]))
        self.conn.execute('UPDATE bank_questions SET explanation=? WHERE id=?', ('完全相同的参考推导。', self.ids[1]));self.conn.commit()
        self.service.review_identity(self.body());self.save_annotations(self.ids[:2])
        self.assertIsNotNone(annotations.current(self.conn, self.data, self.ids[1]))
        old = [tuple(r) for r in self.conn.execute('SELECT * FROM question_annotations')]
        self.service.review_identity(self.body('revoke'))
        self.assertIsNotNone(annotations.current(self.conn, self.data, self.ids[0]))
        self.assertIsNone(annotations.current(self.conn, self.data, self.ids[1]))
        self.assertEqual([tuple(r) for r in self.conn.execute('SELECT * FROM question_annotations')], old)

    def test_different_references_do_not_inherit_ready_and_current_recall_splits_after_revoke(self):
        self.service.review_identity(self.body());self.save_annotations(self.ids[:2])
        current = [annotations.current(self.conn, self.data, bid) for bid in self.ids[:2]]
        self.assertNotEqual(current[0]['id'], current[1]['id'])
        self.assertEqual(len({v['entity_id'] for v in current}), 1)
        before = annotations.search(self.conn, self.data, topic_ids=['GS-04-001'])
        self.assertEqual(before['total'], 1)
        self.service.review_identity(self.body('revoke'))
        after = annotations.search(self.conn, self.data, topic_ids=['GS-04-001'])
        self.assertEqual(after['total'], 2)
        self.assertEqual(len({q['entity_id'] for q in after['items']}), 2)
        # The historic proof is not rewritten to manufacture new provenance.
        self.assertEqual(len({annotations.current(self.conn, self.data, bid)['entity_id'] for bid in self.ids[:2]}), 1)

    def test_no_ready_alias_is_created_merely_by_confirmation(self):
        self.save_annotations([self.ids[0]])
        self.service.review_identity(self.body())
        self.assertIsNone(annotations.current(self.conn, self.data, self.ids[1]))
        self.assertIsNotNone(annotations.current(self.conn, self.data, self.ids[0]))

    def test_failure_preserves_old_links_and_writes_no_partial_history(self):
        self.conn.execute('INSERT INTO bank_links VALUES(?,?,?)', (*self.ids[:2], '旧的确认依据，保持原样。'))
        self.conn.execute("CREATE TRIGGER library.reject_identity_history BEFORE INSERT ON bank_identity_reviews BEGIN SELECT RAISE(ABORT,'injected identity failure'); END")
        self.conn.commit();body = self.body('revoke')
        with self.assertRaises(sqlite3.IntegrityError):self.service.review_identity(body)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM bank_links').fetchone()[0], 1)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM bank_identity_reviews').fetchone()[0], 0)

    def test_invalid_ids_confirmation_operation_and_preview_are_rejected(self):
        for patch in ({'confirmed': False}, {'expected_preview_sha256': '0' * 64},
                      {'request_id': 'bad'}, {'left_id': self.ids[1]}, {'reason': '短'}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                self.service.review_identity({**self.body(), **patch})
        with self.assertRaises(ValueError):self.preview('other')
        with self.assertRaises(ValueError):self.preview(pair=(self.ids[0], 'missing'))
        with self.assertRaisesRegex(ValueError, '没有可撤回'):self.service.review_identity(self.body('revoke'))

    def test_http_confirm_preview_same_origin_and_busy_guard(self):
        with TestClient(create_app(self.config, agent_factory=None), base_url='http://127.0.0.1') as client:
            response = client.post('/api/bank/identity-reviews/preview', json={'left_id': self.ids[0], 'right_id': self.ids[1], 'operation': 'confirm'})
            self.assertEqual(response.status_code, 200, response.text)
            body = self.body()
            self.assertEqual(client.post('/api/bank/identity-reviews', json={**body, 'confirmed': 'true'}).status_code, 400)
            self.assertEqual(client.post('/api/bank/identity-reviews', json=body, headers={'Origin': 'http://evil.test'}).status_code, 403)
            runtime = client.app.state.runtime
            bridge = Mock(spec=['lock','assert_user_write_allowed','workflow_wakeup','close']);bridge.lock = threading.RLock()
            bridge.assert_user_write_allowed.side_effect = BridgeConflict('学习任务进行中')
            runtime.bridge = bridge
            self.assertEqual(client.post('/api/bank/identity-reviews', json=body).status_code, 409)
            runtime.bridge = None
            self.assertEqual(client.post('/api/bank/identity-reviews', json=body).status_code, 200)
            self.assertEqual(client.post('/api/bank/identity-reviews', json={**body, 'unexpected': 1}).status_code, 400)

    def test_initialization_and_empty_old_database_read_are_non_destructive(self):
        self.service.review_identity(self.body());old = [tuple(r) for r in self.conn.execute('SELECT * FROM bank_identity_reviews')]
        identity_reviews.initialize(self.conn);identity_reviews.initialize(self.conn)
        self.assertEqual([tuple(r) for r in self.conn.execute('SELECT * FROM bank_identity_reviews')], old)
        scratch = sqlite3.connect(':memory:');scratch.row_factory = sqlite3.Row
        try:self.assertEqual(identity_reviews.confirmed_pairs(scratch), [])
        finally:scratch.close()

    def test_failure_after_history_insert_rolls_back_history_and_legacy_delete(self):
        self.conn.execute('INSERT INTO bank_links VALUES(?,?,?)', (*self.ids[:2], '已核的旧边，失败后应保留。'))
        self.conn.execute("CREATE TRIGGER library.reject_identity_delete BEFORE DELETE ON bank_links BEGIN SELECT RAISE(ABORT,'injected delete failure'); END")
        self.conn.commit()
        with self.assertRaises(sqlite3.IntegrityError):self.service.review_identity(self.body('revoke'))
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM bank_links').fetchone()[0], 1)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM bank_identity_reviews').fetchone()[0], 0)

    def test_reversing_pair_order_reuses_the_same_request(self):
        body = self.body();first = self.service.review_identity(body)
        retry = self.service.review_identity({**body, 'left_id': body['right_id'], 'right_id': body['left_id']})
        self.assertTrue(retry['reused']);self.assertEqual(retry['review_id'], first['review_id'])
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM bank_identity_reviews').fetchone()[0], 1)

    def test_automatic_pixel_equivalence_is_not_silently_removed_by_revoke(self):
        self.conn.execute('UPDATE bank_identity SET sha256=? WHERE bank_id IN (?,?)', ('same-pixels', *self.ids[:2]));self.conn.commit()
        self.service.review_identity(self.body())
        answer = self.service.review_identity(self.body('revoke'))
        self.assertFalse(answer['currently_confirmed'])
        self.assertEqual(answer['group'], sorted(self.ids[:2]))

    def test_reference_quality_is_still_checked_after_manual_merge(self):
        self.save_annotations([self.ids[0]])
        self.conn.execute('UPDATE bank_questions SET explanation=? WHERE id=?', ('错误参考：导数为0。', self.ids[1]));self.conn.commit()
        self.service.review_identity(self.body())
        self.assertIsNone(annotations.current(self.conn, self.data, self.ids[1]))
        value = annotations.capture(self.conn, self.data, {'bank_ids': self.ids[:2]})
        self.assertEqual(len(value['bank_questions']), 2)
        self.assertEqual(len({q['entity_id'] for q in value['bank_questions']}), 1)
