import copy
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.config import AppConfig
from app.storage.database import Database
from app.storage import catalog_packages as store
from app.knowledge import catalog, candidates, packages
from app.knowledge.coverage import read_report
from app.main import create_app
from app.agent.errors import BridgeConflict

ROOT = Path(__file__).resolve().parents[1]


def resigned(value):
    value = copy.deepcopy(value)
    value['document_sha256'] = catalog.digest(value['document'])
    value['sha256'] = catalog.digest({k: v for k, v in value.items() if k != 'sha256'})
    return value


class CatalogPackageTests(unittest.TestCase):
    def setUp(self):
        from test_knowledge_catalog import KnowledgeCatalogTests
        self.f = KnowledgeCatalogTests();self.f.setUp();self.f.publish()
        self.package = packages.export_package(self.f.conn)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT/'tmp', prefix='package-target-')
        self.data = Path(self.temp.name)
        self.config = AppConfig(ROOT, self.data, ROOT/'dist', self.data/'mathlens.db')
        self.db = Database(self.config);self.db.initialize();self.conn = self.db.connect(library_write=True)

    def tearDown(self):
        self.conn.close();self.temp.cleanup();self.f.tearDown()

    def accept(self, value=None, **override):
        value = value or self.package
        args = {'trusted_sha256': value['sha256'], 'expected_parent': catalog.active_id(self.conn), 'confirmed': True}
        args.update(override)
        return packages.import_package(self.conn, value, **args)

    def protected(self):
        return {table: self.conn.execute('SELECT count(*) FROM '+table).fetchone()[0]
                for table in ('papers', 'probe_attempts', 'learning_events', 'learning_tasks',
                              'learning_results', 'knowledge_mappings', 'task_reads')}

    def second_package(self):
        value = copy.deepcopy(catalog.document(self.f.conn)['document'])
        node = copy.deepcopy(value['nodes'][-1])
        node.update(id='isolated-second-atom', name='隔离结构测试概念', aliases=[], definition='隔离测试新增条件。')
        value['nodes'].append(node)
        value['source_resolutions'][0]['node_ids'].append(node['id'])
        self.f.publish(value)
        return packages.export_package(self.f.conn)

    def test_fresh_import_preserves_ids_without_faking_originals_or_learning(self):
        before = self.protected()
        self.assertFalse(self.accept()['reused'])
        self.assertEqual(catalog.search(self.conn, query='链式')['items'][0]['id'], 'GS-04-001')
        for table in ('knowledge_source_versions', 'knowledge_source_entries'):
            self.assertEqual(self.conn.execute('SELECT count(*) FROM '+table).fetchone()[0], 0)
        self.assertEqual(self.protected(), before)
        self.assertTrue(store.source_known(self.conn, self.f.sid, 'GS-04-001'))
        self.assertEqual(packages.export_package(self.conn), self.package)
        with self.assertRaisesRegex(ValueError, '来源版本'):
            candidates.browse(self.conn, source_version_id=self.f.sid)

    def test_repeat_import_with_original_parent_is_idempotent(self):
        self.accept();before = self.conn.total_changes
        self.assertTrue(self.accept(expected_parent=None)['reused'])
        self.assertEqual(self.conn.total_changes, before)

    def test_source_acceptance_and_digest_are_both_required(self):
        for override in ({'confirmed': False}, {'trusted_sha256': '0'*64}):
            with self.assertRaisesRegex(ValueError, '可信散列'):
                self.accept(**override)
        self.assertIsNone(catalog.active_id(self.conn))
        self.assertEqual(store.listing(self.conn), [])

    def test_tampering_unknown_fields_private_notes_and_paths_are_rejected(self):
        value = copy.deepcopy(self.package);value['document']['nodes'][-1]['definition'] += 'changed'
        with self.assertRaisesRegex(ValueError, '散列'):
            packages.validate_package(value)
        value = copy.deepcopy(self.package);value['session_id'] = 'not-allowed'
        with self.assertRaisesRegex(ValueError, '字段'):
            packages.validate_package(resigned(value))
        value = copy.deepcopy(self.package);value['document']['nodes'][-1]['review_note'] = 'private note'
        with self.assertRaisesRegex(ValueError, '备注'):
            packages.validate_package(resigned(value))
        value = copy.deepcopy(self.package);value['document']['nodes'][-1]['definition'] = 'C:/Users/private-person/material'
        with self.assertRaisesRegex(ValueError, '本机路径'):
            packages.validate_package(resigned(value))

    def test_export_drops_private_maintenance_metadata(self):
        value = copy.deepcopy(catalog.document(self.f.conn)['document'])
        value['label'] = '本地学习者私人维护批次';value['limitations'] = ['私人材料说明']
        value['nodes'][-1]['review_note'] = 'C:/Users/private-person/source-note'
        value['source_resolutions'][0]['reason'] = '本地学习者私人批次说明'
        self.f.publish(value);exported = packages.export_package(self.f.conn);text = catalog.encode(exported)
        for private in ('private-person', '本地学习者', '私人材料说明'):
            self.assertNotIn(private, text)
        self.assertNotIn('raw', exported['sources'][0]['entries'][0])
        self.assertEqual(exported['document']['nodes'][-1]['definition'], value['nodes'][-1]['definition'])

    def test_upgrade_and_historical_activation_preserve_both_versions(self):
        before = self.protected();first = self.accept();second_package = self.second_package();second = self.accept(second_package)
        self.assertNotEqual(first['release_id'], second['release_id'])
        packages.activate_package(self.conn, self.package['sha256'], expected_current=second['release_id'], confirmed=True)
        self.assertEqual(catalog.active_id(self.conn), first['release_id'])
        self.assertIsNotNone(catalog.document(self.conn, second['release_id']))
        packages.activate_package(self.conn, second_package['sha256'], expected_current=first['release_id'], confirmed=True)
        self.assertEqual(catalog.active_id(self.conn), second['release_id'])
        self.assertEqual(self.protected(), before)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM knowledge_package_activations').fetchone()[0], 4)

    def test_stale_parent_and_unimported_snapshot_are_rejected(self):
        self.accept()
        with self.assertRaisesRegex(ValueError, '目录已变化'):
            self.accept(self.second_package(), expected_parent=None)
        with self.assertRaisesRegex(ValueError, '尚未导入'):
            packages.activate_package(self.conn, '0'*64, expected_current=catalog.active_id(self.conn), confirmed=True)

    def test_failure_after_publish_rolls_back_all_package_state(self):
        before = self.protected()
        with patch('app.knowledge.packages.store.record_activation', side_effect=RuntimeError('after-publish')):
            with self.assertRaisesRegex(RuntimeError, 'after-publish'):
                self.accept()
        self.assertIsNone(catalog.active_id(self.conn))
        for table in ('knowledge_catalog_packages', 'knowledge_package_sources', 'knowledge_package_entries',
                      'knowledge_catalog_releases', 'knowledge_catalog_nodes', 'knowledge_package_activations'):
            self.assertEqual(self.conn.execute('SELECT count(*) FROM '+table).fetchone()[0], 0)
        self.assertEqual(self.protected(), before)

    def test_upgrade_cannot_discard_local_nodes(self):
        self.accept();value = copy.deepcopy(catalog.document(self.conn)['document'])
        node = copy.deepcopy(value['nodes'][-1]);node.update(id='local-extra', name='本地独立目录维护概念', aliases=[])
        value['nodes'].append(node);value['source_resolutions'][0]['node_ids'].append(node['id'])
        release = catalog.create_draft(self.conn, value, expected_parent=catalog.active_id(self.conn))
        catalog.publish(self.conn, release['id'], expected_parent=catalog.active_id(self.conn), reviewer='isolated-maintenance')
        current = catalog.active_id(self.conn)
        with self.assertRaisesRegex(ValueError, '历史考点'):
            self.accept(self.second_package())
        self.assertEqual(catalog.active_id(self.conn), current)
        self.assertEqual(len(store.listing(self.conn)), 1)

    def test_later_raw_source_import_must_match_package_anchors(self):
        self.accept();raw = candidates.read_11408(self.f.source)
        changed = copy.deepcopy(raw);changed['manifest_sha256'] = 'b'*64
        with self.assertRaisesRegex(ValueError, '出处冲突'):
            candidates._import_value(self.conn, changed)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM knowledge_source_entries').fetchone()[0], 0)
        self.assertFalse(candidates.import_11408(self.conn, self.f.source)['reused'])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM knowledge_source_entries').fetchone()[0], 1)
        self.assertTrue(store.source_known(self.conn, self.f.sid, 'GS-04-001'))

    def test_coverage_distinguishes_imported_metadata_and_actual_raw_source(self):
        self.accept();report = read_report(self.conn, self.data)
        self.assertEqual(report['sources'][0]['provenance'], 'imported_catalogue_only')
        self.assertEqual(report['sources'][0]['dispositions'], {'mapped': 1})
        self.assertEqual(report['summary']['published_atoms'], 1)
        candidates.import_11408(self.conn, self.f.source);report = read_report(self.conn, self.data)
        self.assertEqual(report['sources'][0]['source_atoms'], 1)
        self.assertEqual(report['sources'][0]['provenance'], 'local_source_entries')

    def test_http_preview_import_export_and_origin_boundary(self):
        with TestClient(create_app(self.config, agent_factory=None), base_url='http://127.0.0.1') as client:
            preview = client.post('/api/knowledge/packages/preview', json={'package': self.package})
            self.assertEqual(preview.status_code, 200);self.assertIsNone(preview.json()['current_release_id'])
            body = {'package': self.package, 'trusted_sha256': self.package['sha256'],
                    'expected_active_release_id': None, 'confirmed': True}
            saved = client.post('/api/knowledge/packages/import', json=body)
            self.assertEqual(saved.status_code, 200, saved.text)
            exported = client.get('/api/knowledge/packages/export')
            self.assertEqual(exported.json(), self.package)
            self.assertIn('attachment', exported.headers['content-disposition'])
            rejected = client.post('/api/knowledge/packages/import', json=body, headers={'Origin': 'https://elsewhere.test'})
            self.assertEqual(rejected.status_code, 403)
            self.assertEqual(len(client.get('/api/knowledge/packages').json()['packages']), 1)
        self.assertFalse((self.data/'agent-session.db').exists())
        self.assertEqual(self.protected(), {k: 0 for k in self.protected()})

    def test_busy_session_rejects_import_but_allows_preview(self):
        class Busy:
            lock = threading.RLock()
            def assert_user_write_allowed(self):raise BridgeConflict('busy-test')
        with TestClient(create_app(self.config, bridge=Busy(), agent_factory=None, manage_agent=False),
                        base_url='http://127.0.0.1') as client:
            body = {'package': self.package, 'trusted_sha256': self.package['sha256'],
                    'expected_active_release_id': None, 'confirmed': True}
            self.assertEqual(client.post('/api/knowledge/packages/preview', json={'package': self.package}).status_code, 200)
            self.assertEqual(client.post('/api/knowledge/packages/import', json=body).status_code, 409)
        self.assertIsNone(catalog.active_id(self.conn))

    def test_http_body_limit_applies_before_parsing(self):
        with TestClient(create_app(self.config, agent_factory=None), base_url='http://127.0.0.1') as client:
            result = client.post('/api/knowledge/packages/preview', content=b'{}',
                                 headers={'Content-Type': 'application/json', 'Content-Length': str(16*1024*1024+1)})
            self.assertEqual(result.status_code, 400);self.assertIn('过大', result.json()['error'])
