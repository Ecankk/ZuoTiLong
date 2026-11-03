from contextlib import closing
import json,sqlite3,unittest
from pathlib import Path
from unittest.mock import patch

from app.bank import annotations,annotation_packages,annotation_revisions
from app.config import AppConfig
from app.knowledge import catalog
from app.storage.database import Database
from app.storage.provenance import SCHEMA,evidence_digest,reviewed_source
from app.storage.provenance_upgrade import upgrade
from app.storage.backup_archive import file_sha256


class ProvenanceUpgradeTests(unittest.TestCase):
    def setUp(self):
        from test_question_annotations import QuestionPreparationTests
        self.f=QuestionPreparationTests();self.f.setUp();self.addCleanup(self.f.tearDown)
        self.conn=self.f.conn;self.ids=self.f.save_annotation()
        self.library=self.f.f.config.library_dir;self.database=self.f.f.config.database
        self.current=annotations.current(self.conn,self.f.data,self.ids[0])

    def legacy(self):
        row=self.conn.execute('SELECT payload_json FROM annotation_provenance').fetchone()
        value=json.loads(row[0]);legacy={k:value[k] for k in ('published','rule_revision','source','analysis_sha256','reviewed_roles','result_sha256')}
        self.conn.execute('UPDATE annotation_provenance SET payload_json=?',(json.dumps(legacy),));self.conn.commit()

    def fresh(self):
        config=AppConfig(self.f.root,self.f.data/'empty',self.f.root/'dist',self.f.data/'empty'/'learning.db',library=self.library)
        Database(config).initialize();return config

    def test_new_proof_has_actual_definition_snapshots_and_no_execution_secrets(self):
        value=reviewed_source(self.conn,self.current)
        self.assertEqual(value['schema'],SCHEMA);self.assertEqual(value['evidence_sha256'],evidence_digest(value))
        self.assertTrue(value['definition_reads']);self.assertEqual(len(value['material_reads']),3)
        for key in ('session_id','run_token','turn_id'):
            self.assertNotIn(key,json.dumps(value))
        self.assertNotIn('review_note',value['input_summary'])
        self.assertEqual(value['definition_reads'][0]['sha256'],catalog.digest(value['definition_reads'][0]['definition']))

    def test_backfill_preview_backup_confirm_idempotence_and_source_unchanged(self):
        self.legacy();before=file_sha256(self.database)
        annotations_before=[tuple(r) for r in self.conn.execute('SELECT rowid,* FROM question_annotations')]
        plan=upgrade(self.library,self.database)
        self.assertEqual(plan['counts'],dict(changes=1,unchanged=0,blocked=0));self.assertFalse(plan['applied'])
        self.assertFalse((self.library.parent/'backups').exists())
        with self.assertRaises(ValueError):upgrade(self.library,self.database,confirm='bad')
        applied=upgrade(self.library,self.database,confirm=plan['plan_sha256'])
        self.assertTrue(Path(applied['backup']['path']).is_file());self.assertTrue(applied['applied'])
        again=upgrade(self.library,self.database)
        self.assertEqual(again['counts'],dict(changes=0,unchanged=1,blocked=0))
        self.assertFalse(upgrade(self.library,self.database,confirm=again['plan_sha256'])['applied'])
        self.assertEqual(file_sha256(self.database),before)
        self.assertEqual([tuple(r) for r in self.conn.execute('SELECT rowid,* FROM question_annotations')],annotations_before)

    def test_new_and_original_workspace_export_the_same_without_original_execution(self):
        self.legacy();plan=upgrade(self.library,self.database);upgrade(self.library,self.database,confirm=plan['plan_sha256'])
        original=annotation_packages.export_package(self.conn,self.f.data)
        config=self.fresh()
        with Database(config).session() as conn:
            conn.execute('PRAGMA query_only=ON')
            # Reject even attempting a read of private execution tables.
            conn.set_authorizer(lambda action,arg1,arg2,db,trigger: sqlite3.SQLITE_DENY
                if action==sqlite3.SQLITE_READ and arg1 in ('learning_results','learning_tasks','task_reads') else sqlite3.SQLITE_OK)
            value=annotations.current(conn,config.data,self.ids[0]);self.assertIsNotNone(value)
            self.assertEqual(annotation_packages.export_package(conn,config.data),original)
            request={'expected_annotations':{self.ids[0]:value['id']},'allowed_fields':['reference_reasoning']}
            self.assertTrue(annotation_revisions.capture_bases(conn,config.data,[self.ids[0]],request))
            from app.bank.retrieval import recall
            self.assertTrue(recall(conn,config.data,topic_ids=[value['analysis']['bindings'][0]['topic_id']])['total'])
            from app.storage.practice_materials import freeze
            from app.learning.practice_knowledge import material_binding,require_reviewed_references
            frozen=freeze(conn,config.data,material_binding(conn,config.data,self.ids[0],value))
            origin=conn.execute('SELECT * FROM question_annotations WHERE id=?',(value['id'],)).fetchone()
            require_reviewed_references(conn,origin,frozen['material_manifest'])

    def test_missing_real_reads_blocks_backfill_without_backup_or_write(self):
        self.legacy()
        self.conn.execute("DELETE FROM task_reads WHERE kind='knowledge_definition'");self.conn.commit()
        plan=upgrade(self.library,self.database)
        self.assertEqual(plan['counts']['blocked'],1);self.assertIn('定义阅读',plan['blocked'][0]['reason'])
        with self.assertRaisesRegex(ValueError,'无法验证'):upgrade(self.library,self.database,confirm=plan['plan_sha256'])
        self.assertFalse((self.library.parent/'backups').exists())

    def test_changed_source_after_preview_is_rejected_and_corrupt_proof_not_consumed(self):
        self.legacy();plan=upgrade(self.library,self.database)
        self.conn.execute("UPDATE task_reads SET sha256=? WHERE kind='bank_preparation'",('0'*64,));self.conn.commit()
        with self.assertRaisesRegex(ValueError,'预演已变化'):upgrade(self.library,self.database,confirm=plan['plan_sha256'])
        # Corruption cannot be hidden by merely recomputing the outer checksum.
        row=self.conn.execute('SELECT payload_json FROM annotation_provenance').fetchone()
        proof=json.loads(row[0]);proof['reviewed_roles']['analysis']='0'*64
        self.conn.execute('UPDATE annotation_provenance SET payload_json=?',(json.dumps(proof),));self.conn.commit()
        self.assertIsNone(annotations.current(self.conn,self.f.data,self.ids[0]))

    def test_failed_automatic_backup_leaves_provenance_unchanged(self):
        self.legacy();plan=upgrade(self.library,self.database)
        before=[tuple(r) for r in self.conn.execute('SELECT * FROM annotation_provenance')]
        with patch('app.storage.library_backup.backup_library',side_effect=ValueError('backup failed')):
            with self.assertRaisesRegex(ValueError,'backup failed'):upgrade(self.library,self.database,confirm=plan['plan_sha256'])
        self.assertEqual([tuple(r) for r in self.conn.execute('SELECT * FROM annotation_provenance')],before)

    def test_already_complete_v2_does_not_require_private_reads_again(self):
        self.conn.execute('DELETE FROM task_reads');self.conn.commit()
        with patch('app.storage.provenance_upgrade.capture_provenance',side_effect=AssertionError('private execution query')):
            plan=upgrade(self.library,self.database)
        self.assertEqual(plan['counts'],dict(changes=0,unchanged=1,blocked=0))
