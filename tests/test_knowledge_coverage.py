import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from app.knowledge.coverage import build_report, read_report, markdown

ROOT = Path(__file__).resolve().parents[1]


class KnowledgeCoverageTests(unittest.TestCase):
    def setUp(self):
        self.nodes = [
            {'id': 'subject', 'parent_id': None, 'name': '高数', 'kind': 'subject'},
            {'id': 'chapter', 'parent_id': 'subject', 'name': '微分', 'kind': 'chapter'},
            {'id': 'a', 'parent_id': 'chapter', 'name': '链式法则', 'kind': 'atom'},
            {'id': 'b', 'parent_id': 'chapter', 'name': '乘积法则', 'kind': 'atom'}]
        self.document = {'nodes': self.nodes, 'redirects': [], 'source_resolutions': []}
        self.sources = [{'id': 'v1', 'source': 'fixed-source', 'revision': 'r1',
                         'chapters': {'c1': '来源章节'}}]
        self.entries = []
        self.questions = []

    def source_atom(self, rid, state, topics=None, version='v1'):
        self.entries.append({'source_version_id': version, 'id': rid, 'kind': 'atom', 'chapter_key': 'c1'})
        if state:
            self.document['source_resolutions'].append({'source_version_id': version, 'source_id': rid,
                                                        'disposition': state, 'node_ids': topics or [],
                                                        'reason': '独立固定来源核查'})

    def report(self):
        return build_report({'id': 'release', 'content_sha256': 'sha', 'document': self.document},
                            self.sources, self.entries, self.questions,
                            outline_nodes=[('subject', None, '高数'), ('chapter', 'subject', '微分')])

    def test_source_disposition_and_atom_count_are_distinct(self):
        self.source_atom('r1', 'mapped', ['a', 'b'])
        self.source_atom('r2', 'method')
        self.source_atom('r3', 'pending')
        self.source_atom('r4', None)
        report = self.report()
        source = report['sources'][0]
        self.assertEqual(source['source_atoms'], 4)
        self.assertEqual(source['mapped_published_atoms'], 2)
        self.assertEqual(source['dispositions'], {'mapped': 1, 'method': 1, 'pending': 1, 'unresolved': 1})
        self.assertEqual(len(source['pending']), 2)
        self.assertEqual(report['claims']['official_syllabus_complete'], 'not_evaluated')
        self.assertEqual(report['summary']['atoms_with_ready_questions'], 0)

    def test_confirmed_aliases_share_entity_but_keep_source_counts_and_redirects(self):
        self.document['redirects'] = [{'old_id': 'old-a', 'target_id': 'a', 'reason': '经审核的同义合并'}]
        self.source_atom('source-a', 'mapped', ['old-a'])
        self.questions = [{'bank_id': 'math1-x', 'entity_id': 'same-q', 'topic_ids': ['old-a', 'b']},
                          {'bank_id': 'math2-x', 'entity_id': 'same-q', 'topic_ids': ['a', 'b']}]
        report = self.report()
        self.assertEqual(report['summary']['ready_source_records'], 2)
        self.assertEqual(report['summary']['ready_question_entities'], 1)
        self.assertEqual(report['outline'][0]['ready_source_records'], 2)
        self.assertEqual(report['outline'][0]['ready_question_entities'], 1)
        self.assertEqual(report['sources'][0]['mapped_published_atoms'], 1)
        self.assertEqual([r['ready_question_entities'] for r in report['atoms']], [1, 1])

    def test_same_source_id_in_two_versions_is_not_combined(self):
        self.sources.append({'id': 'v2', 'source': 'fixed-source', 'revision': 'r2'})
        self.source_atom('r1', 'mapped', ['a'])
        self.source_atom('r1', 'pending', version='v2')
        report = self.report()
        self.assertEqual(len(report['source_chapters']), 2)
        self.assertEqual(report['sources'][0]['dispositions'], {'mapped': 1})
        self.assertEqual(report['sources'][1]['dispositions'], {'pending': 1})

    def test_broken_ancestry_or_unknown_mapping_fails_instead_of_faking_coverage(self):
        self.nodes[2]['parent_id'] = 'missing'
        with self.assertRaisesRegex(ValueError, '父节点'):
            self.report()
        self.nodes[2]['parent_id'] = 'chapter'
        self.source_atom('r1', 'mapped', ['unknown'])
        with self.assertRaisesRegex(ValueError, '不存在'):
            self.report()

    def test_metadata_report_does_not_export_definitions_or_learner_judgment(self):
        self.nodes[2]['definition'] = 'not-to-export-definition'
        report = self.report()
        self.assertNotIn('not-to-export-definition', json.dumps(report))
        text = markdown(report)
        self.assertIn('无练习不等于学生薄弱', text)
        self.assertNotIn('not-to-export-definition', text)

    def test_database_reader_does_not_read_learner_tables_or_write(self):
        from test_knowledge_catalog import KnowledgeCatalogTests
        fixture = KnowledgeCatalogTests();fixture.setUp()
        try:
            fixture.publish()
            fixture.conn.commit()
            before = fixture.conn.total_changes
            forbidden = {'papers', 'probe_attempts', 'learning_events', 'agent_reports',
                         'question_diagnoses', 'knowledge_mappings', 'diagnostic_probes'}
            def authorizer(action, first, second, database, trigger):
                if action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE):
                    return sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_READ and first in forbidden:
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            fixture.conn.set_authorizer(authorizer)
            report = read_report(fixture.conn, fixture.data)
            self.assertEqual(report['summary']['published_atoms'], 1)
            self.assertEqual(report['sources'][0]['dispositions'], {'mapped': 1})
            self.assertEqual(fixture.conn.total_changes, before)
        finally:
            fixture.conn.set_authorizer(None);fixture.tearDown()

    def test_cli_missing_database_and_output_into_data_are_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as folder:
            data = Path(folder)/'missing'
            result = subprocess.run([sys.executable, '-X', 'utf8', str(ROOT/'scripts/audit_knowledge_coverage.py'),
                                     '--data', str(data)], capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(result.returncode, 2)
            self.assertIn('数据库不存在', result.stderr)
            self.assertFalse(data.exists())
            result = subprocess.run([sys.executable, '-X', 'utf8', str(ROOT/'scripts/audit_knowledge_coverage.py'),
                                     '--data', folder, '--output', str(Path(folder)/'papers/report')],
                                    capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(result.returncode, 2)
            self.assertIn('不能写入学习资料目录', result.stderr)
            self.assertFalse((Path(folder)/'papers').exists())
