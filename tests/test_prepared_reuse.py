from app.storage.boundaries import library_root
"""Versioned reuse does not copy attempts or substitute current library content."""
import copy,json,unittest,uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from PIL import Image
import test_frozen_practice as frozen
from app.learning.tasks import create_task,record_read,deliver,finish_task,receipt
from app.learning.loop import apply_report,loop_snapshot
from app.learning.plans import practice_state
from app.storage.practice_materials import _publish

TOPIC=frozen.TOPIC
BANK=frozen.BANK


class PreparedReuseTests(unittest.TestCase):
    def setUp(self):
        self.base=frozen.FrozenPracticeTests();self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.f=self.base.f;self.case=self.base.case;self.conn=self.base.conn
        self.data=self.base.data;self.pid=self.base.probe_id
        self.probe_count=self.conn.execute('SELECT count(*) FROM diagnostic_probes').fetchone()[0]

    def start(self,paper='paper-test',kind='prepare_practice',version='1.9'):
        task=create_task(self.conn,self.f.root,self.data,kind,paper,'prepared-reuse',str(uuid.uuid4()),contract_version=version)
        self.f.task=task;self.f.kind=kind;self.f.lease=self.case.bind(task,'prepared-reuse')
        return json.loads(task['input_json'])

    def retained(self):
        value=self.case.payload();value['paper_id']=self.f.task['paper_id']
        value['result']['exercises']=[]
        value['result']['retained_exercises']=[{'probe_id':self.pid,'goal_ids':['chain']}]
        return value

    def read_original(self):
        self.case.tool('task_context',{'topic_ids':[TOPIC]})
        return self.case.tool('read_bank',{'bank_id':BANK,'probe_id':self.pid,'role':'all'})

    def save(self,value):
        saved=deliver(self.conn,self.f.root,self.data,value,self.f.lease)
        finish_task(self.conn,self.f.task['id']);self.conn.commit()
        return saved

    def test_explicit_membership_excludes_an_unassigned_old_probe_after_append(self):
        self.conn.execute('''INSERT INTO diagnostic_probes SELECT 'stray-probe',paper_id,question_id,
            bank_id,skill_id,payload_json,status,created_at FROM diagnostic_probes WHERE id=?''',(self.pid,))
        self.start();self.read_original();self.save(self.retained())
        state=practice_state(self.conn,'paper-test')
        self.assertTrue(state['explicit_membership']);self.assertEqual(state['probe_ids'],[self.pid])
        self.assertEqual(state['last_retained_count'],1)

    def test_current_bank_read_cannot_replace_the_retained_version_read(self):
        self.start();self.case.tool('task_context',{'topic_ids':[TOPIC]})
        self.case.tool('read_bank',{'bank_id':BANK,'role':'all'})
        with self.assertRaisesRegex(ValueError,'practice_material'):
            deliver(self.conn,self.f.root,self.data,self.retained(),self.f.lease)
        self.assertIsNone(receipt(self.conn,self.f.task['id']))
        self.read_original();self.save(self.retained())

    def test_library_update_cannot_change_the_shared_exercise_or_attempt(self):
        attempt=self.base.submit()['attempt_id']
        before=dict(self.conn.execute('SELECT * FROM probe_attempts WHERE id=?',(attempt,)).fetchone())
        events=self.conn.execute('SELECT count(*) FROM learning_events').fetchone()[0]
        self.conn.execute('UPDATE bank_questions SET stem=?,explanation=? WHERE id=?',('A different question','A different reference',BANK))
        Image.new('RGB',(40,40),'red').save(library_root(self.data)/'bank-assets/question.png')
        self.start();material=self.read_original()
        self.assertEqual(next(r['text'] for r in material['resources'] if r['role']=='question'),'求 f(x)=sin(x²) 的导数。')
        value=self.retained();value['result']['goals'].append({**value['result']['goals'][0],'id':'second','question_numbers':[2]})
        value['result']['retained_exercises'][0]['goal_ids'].append('second')
        self.save(value)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM diagnostic_probes').fetchone()[0],self.probe_count)
        self.assertEqual(dict(self.conn.execute('SELECT * FROM probe_attempts WHERE id=?',(attempt,)).fetchone()),before)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM learning_events').fetchone()[0],events)
        self.assertEqual(len(next(p for p in loop_snapshot(self.conn)['probes'] if p['id']==self.pid)['linked_goal_ids']),2)

    def test_cross_paper_reuse_reads_original_snapshot_and_keeps_one_probe(self):
        source=self.conn.execute("SELECT source_path FROM papers WHERE id='paper-test'").fetchone()[0]
        self.conn.execute("INSERT INTO papers(id,title,source_path,created_at) VALUES('paper-next','Next isolated paper',?,'now')",(source,))
        report=copy.deepcopy(json.loads(self.conn.execute("SELECT report_json FROM agent_reports WHERE paper_id='paper-test' ORDER BY rowid DESC LIMIT 1").fetchone()[0]))
        report['probes']=[]
        apply_report(self.conn,'paper-next',report,self.f.root)
        inputs=self.start('paper-next','organize_knowledge','1.8')
        for item in inputs['knowledge_sources']:
            record_read(self.conn,self.f.lease,'knowledge',item['source_id'],'evidence',item['source_revision'])
        self.case.tool('task_context',{'topic_ids':[TOPIC]})
        payload=self.f.envelope({'summary':'Associate saved isolated evidence.','new_nodes':[],
            'mappings':[{'source_id':s['source_id'],'source_revision':s['source_revision'],'topic_ids':[TOPIC],
                         'reason':'The original chain-rule task.',
                         'event_topics':[{'event_id':e['id'],'topic_ids':[TOPIC]} for e in s['events']]} for s in inputs['knowledge_sources']],
            'limitations':[]})
        payload['paper_id']='paper-next';self.save(payload)
        self.start('paper-next');self.read_original()
        value=self.retained();value['result']['retained_exercises']=[]
        value['result']['goals'][0]['related_probe_ids']=[self.pid]
        self.save(value)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM diagnostic_probes').fetchone()[0],self.probe_count)
        goals=[g for g in loop_snapshot(self.conn)['goals'] if g['paper_id']=='paper-next']
        self.assertEqual(goals[0]['related_probe_ids'],[self.pid])

    def test_unrelated_definition_and_alias_growth_does_not_invalidate_selection(self):
        self.start();self.read_original()
        self.case.m.change('math1.probability.testing',definition='An unrelated hypothesis-testing boundary.')
        self.case.m.change(TOPIC,aliases=['复合函数链式求导','同一概念别名'])
        self.save(self.retained())

    def test_unrelated_annotation_growth_does_not_invalidate_selection(self):
        self.start();self.read_original()
        row=dict(self.conn.execute('SELECT * FROM question_annotations LIMIT 1').fetchone());row['id']='unrelated-annotation'
        self.conn.execute('INSERT INTO question_annotations('+','.join(row)+') VALUES('+','.join('?' for _ in row)+')',list(row.values()))
        self.save(self.retained())

    def test_changed_original_definition_does_not_reuse_stale_selection(self):
        self.start();self.read_original()
        self.case.m.change(TOPIC,conditions=['A different mathematical domain.'])
        with self.assertRaisesRegex(ValueError,'映射尚未就绪|定义.*变化'):
            deliver(self.conn,self.f.root,self.data,self.retained(),self.f.lease)
        self.assertIsNone(receipt(self.conn,self.f.task['id']))

    def test_changed_student_evidence_still_invalidates_selection(self):
        self.start();self.read_original()
        self.conn.execute("UPDATE questions SET notes='new evidence' WHERE paper_id='paper-test'")
        with self.assertRaisesRegex(ValueError,'证据.*变化'):
            deliver(self.conn,self.f.root,self.data,self.retained(),self.f.lease)
        self.assertIsNone(receipt(self.conn,self.f.task['id']))


class SnapshotPublishTests(unittest.TestCase):
    def test_transient_windows_file_hold_does_not_expose_partial_materials(self):
        with TemporaryDirectory() as folder:
            source=Path(folder)/'complete';source.mkdir();(source/'question.png').write_bytes(b'complete')
            target=Path(folder)/'published';rename=Path.rename;attempts=[]
            def publish(path,destination):
                attempts.append(destination);self.assertFalse(target.exists())
                if len(attempts)<3:raise PermissionError('transient scanner hold')
                return rename(path,destination)
            with patch.object(Path,'rename',autospec=True,side_effect=publish),patch('app.storage.practice_materials.time.sleep'):
                _publish(source,target)
            self.assertEqual((target/'question.png').read_bytes(),b'complete');self.assertEqual(len(attempts),3)

    def test_permanent_publish_failure_preserves_complete_source_and_no_destination(self):
        with TemporaryDirectory() as folder:
            source=Path(folder)/'complete';source.mkdir();(source/'question.png').write_bytes(b'complete')
            target=Path(folder)/'published'
            with patch.object(Path,'rename',side_effect=PermissionError('still held')),patch('app.storage.practice_materials.time.sleep'):
                with self.assertRaises(PermissionError):_publish(source,target)
            self.assertFalse(target.exists());self.assertEqual((source/'question.png').read_bytes(),b'complete')
