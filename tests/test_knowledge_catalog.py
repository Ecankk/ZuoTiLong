import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from app.config import AppConfig
from app.storage.database import Database
from app.knowledge import catalog, candidates

ROOT = Path(__file__).resolve().parents[1]
PARENT = 'math1.calculus.differentiation'


class KnowledgeCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT/'tmp', prefix='catalog-')
        self.data = Path(self.temp.name)
        self.config = AppConfig(ROOT, self.data, ROOT/'dist', self.data/'mathlens.db')
        db = Database(self.config);db.initialize();self.conn = db.connect(library_write=True)
        self.source = self.data/'candidate';self.source.mkdir()
        raw = '| GS-04-001 | 复合函数求导法则 |'
        self.atom = {'id': 'GS-04-001', 'statement': '复合函数求导法则', 'raw': raw,
                     'source_commit': 'a'*40, 'content_review': 'source_unreviewed',
                     'content_sha256': hashlib.sha256(raw.encode()).hexdigest(),
                     'source_path': 'chapter.md', 'source_line': 10, 'source_locator': 'section 1'}
        chapter = {'source_commit': 'a'*40, 'atoms': [self.atom], 'combinations': []}
        path = self.source/'chapter.json';path.write_text(json.dumps(chapter, ensure_ascii=False), encoding='utf-8')
        index = {'source_commit': 'a'*40, 'chapters': [{'key': 'GS-04', 'path': 'chapter.json',
                 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'atoms': 1, 'combinations': 0}]}
        (self.source/'index.json').write_text(json.dumps(index), encoding='utf-8')
        self.sid = candidates.import_11408(self.conn, self.source)['source_version_id']

    def tearDown(self):
        self.conn.close();self.temp.cleanup()

    def value(self):
        value = catalog.base_document(self.conn)
        value['nodes'].append({'id': 'GS-04-001', 'parent_id': PARENT, 'name': '一元复合函数的链式求导法则',
            'kind': 'atom', 'definition': '复合函数的导数等于外层导数与内层导数之积。',
            'conditions': ['各复合层在对应点可导。'], 'boundaries': ['不能将导数条件自动推广到仅连续的函数。'],
            'aliases': ['链式法则'], 'math_types': [1, 2, 3],
            'source_refs': [{'source_version_id': self.sid, 'source_id': 'GS-04-001'}],
            'review_note': '核对定义、条件和来源，属于微分知识而非本次计算表现。'})
        value['source_resolutions'] = [{'source_version_id': self.sid, 'source_id': 'GS-04-001',
            'disposition': 'mapped', 'node_ids': ['GS-04-001'], 'reason': '同一复合函数求导概念。'}]
        return value

    def publish(self, value=None):
        parent = catalog.active_id(self.conn)
        release = catalog.create_draft(self.conn, value or self.value(), expected_parent=parent)
        return catalog.publish(self.conn, release['id'], expected_parent=parent, reviewer='isolated-content-review')

    def test_full_candidate_import_is_idempotent_and_does_not_create_nodes_or_events(self):
        before = {t: self.conn.execute('SELECT count(*) FROM '+t).fetchone()[0]
                  for t in ('knowledge_nodes', 'learning_events', 'knowledge_mappings')}
        result = candidates.import_11408(self.conn, self.source)
        self.assertTrue(result['reused']);self.assertEqual(result['entries'], 1)
        self.assertIsNone(catalog.active_id(self.conn))
        for table, count in before.items():self.assertEqual(self.conn.execute('SELECT count(*) FROM '+table).fetchone()[0], count)
        self.assertEqual(candidates.browse(self.conn, source_version_id=self.sid, query='复合')['total'], 1)

    def test_tampered_source_is_rejected_without_partial_source_rows(self):
        before = self.conn.total_changes
        (self.source/'chapter.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, '散列'):candidates.import_11408(self.conn, self.source)
        self.assertEqual(self.conn.total_changes, before)

    def test_total_export_must_match_chapters(self):
        (self.source/'atoms.jsonl').write_text('{}\n')
        with self.assertRaises((ValueError, KeyError)):candidates.read_11408(self.source)

    def test_draft_is_invisible_until_explicit_publication_and_queries_share_version(self):
        draft = catalog.create_draft(self.conn, self.value(), expected_parent=None)
        self.assertIsNone(catalog.active_id(self.conn));self.assertEqual(catalog.search(self.conn)['total'], 0)
        published = catalog.publish(self.conn, draft['id'], expected_parent=None, reviewer='test-review')
        result = catalog.search(self.conn, query='链式法则', parent_id=PARENT, kinds=['atom'])
        self.assertEqual(result['release_id'], published['id']);self.assertEqual(result['total'], 1)
        self.assertEqual(catalog.resolve(self.conn, 'GS-04-001'), 'GS-04-001')
        self.assertIsNone(catalog.resolve(self.conn, 'invented'))
        self.assertEqual(catalog.create_draft(self.conn, published['document'], expected_parent=published['id'])['id'], published['id'])

    def test_same_names_formatting_and_unknown_sources_cannot_be_published(self):
        value = self.value();other = copy.deepcopy(value['nodes'][-1]);other['id'] = 'duplicate'
        other['name'] = ' 一元复合函数的链式求导法则 ';value['nodes'].append(other)
        with self.assertRaisesRegex(ValueError, '同名'):catalog.create_draft(self.conn, value, expected_parent=None)
        value = self.value();value['nodes'][-1]['source_refs'][0]['source_id'] = 'unknown'
        with self.assertRaisesRegex(ValueError, '来源'):catalog.create_draft(self.conn, value, expected_parent=None)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM knowledge_catalog_releases').fetchone()[0], 0)

    def test_broken_parent_cycles_and_loss_of_existing_ids_rejected(self):
        for parent in ('missing', 'GS-04-001'):
            value = self.value();value['nodes'][-1]['parent_id'] = parent
            with self.assertRaisesRegex(ValueError, '断链|循环'):catalog.create_draft(self.conn, value, expected_parent=None)
        value = self.value();value['nodes'] = [value['nodes'][-1]];value['nodes'][0]['parent_id'] = None
        with self.assertRaises(ValueError):catalog.create_draft(self.conn, value, expected_parent=None)

    def test_merge_redirect_preserves_old_ids_and_historical_release(self):
        first = self.publish();value = catalog.base_document(self.conn)
        value['nodes'][-1]['id'] = 'canonical.chain-rule'
        value['redirects'] = [{'old_id': 'GS-04-001', 'target_id': 'canonical.chain-rule', 'reason': '确认同一数学概念，保留来源ID。'}]
        value['source_resolutions'][0]['node_ids'] = ['canonical.chain-rule']
        second = self.publish(value)
        self.assertEqual(catalog.resolve(self.conn, 'GS-04-001'), 'canonical.chain-rule')
        self.assertEqual(catalog.resolve(self.conn, 'GS-04-001', first['id']), 'GS-04-001')
        self.assertEqual(catalog.document(self.conn, first['id'])['state'], 'published')
        self.assertNotEqual(first['id'], second['id'])

    def test_publication_conflict_keeps_current_release(self):
        first = self.publish();value = catalog.base_document(self.conn);value['label'] = 'next'
        draft = catalog.create_draft(self.conn, value, expected_parent=first['id'])
        value['label'] = 'other';other = self.publish(value)
        with self.assertRaisesRegex(ValueError, '父版本'):catalog.publish(self.conn, draft['id'], expected_parent=first['id'], reviewer='test-review')
        self.assertEqual(catalog.active_id(self.conn), other['id'])

    def test_different_concepts_can_have_ambiguous_alias_without_automatic_merge(self):
        value = self.value();other = copy.deepcopy(value['nodes'][-1])
        other.update(id='other.chain-rule', name='多元复合函数的链式求导法则', definition='沿多条中间变量路径求和。')
        value['nodes'].append(other);value['source_resolutions'][0]['node_ids'].append(other['id']);self.publish(value)
        found = catalog.search(self.conn, query='链式法则', kinds=['atom'])
        self.assertEqual(found['total'], 2);self.assertIsNone(catalog.resolve(self.conn, '链式法则'))

    def test_publishing_cannot_remove_prior_atom_without_redirect(self):
        self.publish();value = catalog.base_document(self.conn)
        value['nodes'] = value['nodes'][:-1];value['source_resolutions'] = []
        with self.assertRaisesRegex(ValueError, '历史考点'):catalog.create_draft(self.conn, value, expected_parent=catalog.active_id(self.conn))

    def test_existing_learning_evidence_follows_redirect_without_rewriting_history(self):
        from test_knowledge_index import KnowledgeIndexTests, TOPIC
        from app.knowledge.index import snapshot
        fixture = KnowledgeIndexTests();fixture.setUp()
        try:
            fixture.save()
            before = {t: [tuple(r) for r in fixture.conn.execute('SELECT * FROM '+t)]
                      for t in ('knowledge_mappings', 'learning_events', 'agent_reports')}
            value = catalog.base_document(fixture.conn)
            for node in value['nodes']:
                if node['id'] == TOPIC:node['id'] = 'canonical.multiple-integrals'
            value['redirects'] = [{'old_id': TOPIC, 'target_id': 'canonical.multiple-integrals',
                                   'reason': '规范同概念ID，保留原ID追溯。'}]
            release = catalog.create_draft(fixture.conn, value, expected_parent=None)
            catalog.publish(fixture.conn, release['id'], expected_parent=None, reviewer='isolated-review')
            state = snapshot(fixture.conn)
            item = next(n for n in state['nodes'] if n['skill_id'] == 'canonical.multiple-integrals')
            self.assertEqual(item['failures'], 2)
            self.assertNotIn(TOPIC, [n['skill_id'] for n in state['nodes']])
            for table, rows in before.items():
                self.assertEqual(rows, [tuple(r) for r in fixture.conn.execute('SELECT * FROM '+table)])
        finally:
            fixture.tearDown()

    def test_readonly_http_catalog_and_candidate_queries_do_not_create_session(self):
        from fastapi.testclient import TestClient
        from app.main import create_app
        published = self.publish()
        with TestClient(create_app(self.config, agent_factory=None), base_url='http://127.0.0.1') as client:
            summary = client.get('/api/knowledge/catalog/summary').json()
            self.assertEqual(summary['published_nodes'], 27)
            response = client.get('/api/knowledge/catalog', params={'query': '链式法则', 'kind': 'atom'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['release_id'], published['id'])
            self.assertEqual(response.json()['total'], 1)
            self.assertEqual(client.get('/api/knowledge/catalog/candidates', params={'source_version_id': self.sid}).json()['total'], 1)
            self.assertEqual(client.get('/api/knowledge/catalog', params={'kind': 'invented'}).status_code, 400)
            self.assertEqual(client.get('/api/knowledge/catalog', headers={'Host': 'attacker.example'}).status_code, 403)
        self.assertFalse((self.data/'agent-session.db').exists())
