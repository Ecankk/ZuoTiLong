"""Verification provenance is stable; actual evidence changes remain visible."""
import copy
import json
import unittest

import test_learning_tasks as task_fixtures
from app.learning.loop import apply_report
from app.learning.tasks import deliver, finish_task
from app.knowledge.index import sources


class EvidenceStabilityTests(unittest.TestCase):
    def setUp(self):
        self.f=task_fixtures.LearningTaskTests();self.f.setUp();self.conn=self.f.conn

    def tearDown(self):self.f.tearDown()

    def initial(self,verified=True):
        self.f.start();self.f.read_page();value=self.f.analysis()
        if not verified:
            value['result']['completion']='partial'
            value['result']['report']['review']={'status':'needs_review','issues':['第1题仍需核对。']}
            value['result']['report']['limitations']=['本隔离样本先保留未核实状态。']
        result=deliver(self.conn,self.f.root,self.f.data,value,self.f.lease)
        finish_task(self.conn,self.f.task['id']);self.conn.commit()
        return result['projection']['report_id']

    def originals(self):return {s['content']['number']:s for s in sources(self.conn,'paper-test') if s['kind']=='question'}

    def review(self,number=1,verified=True):
        row=self.conn.execute("SELECT id,report_json FROM agent_reports WHERE paper_id='paper-test' ORDER BY rowid DESC LIMIT 1").fetchone()
        report=json.loads(row['report_json'])
        selected=next(q for q in report['questions'] if q['number']==number)
        selected['observation']+=' A newly checked detail.'
        report.update(summary='Scoped synthetic verification.',completion='complete' if verified else 'partial',
            review={'status':'verified' if verified else 'needs_review','issues':[] if verified else ['第1题新发现的疑点。']},
            revision={'kind':'review_question','parent_report_id':row['id'],'question_id':'paper-test-q-'+str(number).zfill(2)})
        if not verified:report['limitations']=['本次不将未核实内容转为已验证。']
        result=apply_report(self.conn,'paper-test',report,self.f.root,question_numbers={number});self.conn.commit()
        return result['report_id']

    def test_verified_original_keeps_its_own_proof_after_another_question_is_reviewed(self):
        self.initial();before=self.originals();self.review();after=self.originals()
        self.assertEqual(before['2'],after['2'])
        self.assertNotEqual(before['1']['source_revision'],after['1']['source_revision'])
        self.assertTrue(after['2']['events'][0]['verified'])
        self.assertIsNone(after['2']['events'][0]['verified_by_report_id'])

    def test_provisional_evidence_is_certified_once_and_retains_first_valid_review(self):
        self.initial(verified=False);before=self.originals()
        self.assertFalse(before['2']['events'][0]['verified'])
        first=self.review();certified=self.originals()['2']
        self.assertTrue(certified['events'][0]['verified'])
        self.assertEqual(certified['events'][0]['verified_by_report_id'],first)
        self.assertNotEqual(before['2']['source_revision'],certified['source_revision'])
        self.review();again=self.originals()['2']
        self.assertEqual(again,certified)

    def test_pending_review_of_another_question_does_not_erase_existing_proof(self):
        self.initial(verified=False);first=self.review();before=self.originals()['2']
        self.review(verified=False);after=self.originals()['2']
        self.assertEqual(before,after)
        self.assertTrue(after['events'][0]['verified'])
        self.assertEqual(after['events'][0]['verified_by_report_id'],first)

    def test_actual_reviewed_evidence_changes_are_not_hidden_by_stable_provenance(self):
        self.initial();self.review();before=self.originals()
        self.review(number=2);after=self.originals()
        self.assertEqual(before['1'],after['1'])
        self.assertNotEqual(before['2']['source_revision'],after['2']['source_revision'])
        self.assertNotEqual(before['2']['content'],after['2']['content'])

    def test_other_pdf_or_paper_cannot_supply_a_proof(self):
        source_id=self.initial(verified=False)
        original=self.conn.execute("SELECT report_json FROM agent_reports WHERE paper_id='paper-test' ORDER BY rowid LIMIT 1").fetchone()
        report=json.loads(original[0]);report.update(completion='complete',review={'status':'verified','issues':[]},
            revision={'kind':'review_question','parent_report_id':source_id})
        self.conn.execute("INSERT INTO papers(id,title,created_at) VALUES('other-paper','another paper','now')")
        self.conn.execute('INSERT INTO agent_reports VALUES(?,?,?,?,?)',('other-paper-proof','other-paper',report['source_sha256'],json.dumps(report),'later'))
        wrong_pdf=copy.deepcopy(report);wrong_pdf['source_sha256']='f'*64
        self.conn.execute('INSERT INTO agent_reports VALUES(?,?,?,?,?)',('other-pdf-proof','paper-test','f'*64,json.dumps(wrong_pdf),'later'))
        value=self.originals()['2']['events'][0]
        self.assertFalse(value['verified']);self.assertIsNone(value['verified_by_report_id'])

    def test_matching_review_without_source_lineage_cannot_certify_new_unverified_evidence(self):
        self.initial(verified=False)
        row=self.conn.execute("SELECT report_json FROM agent_reports WHERE paper_id='paper-test' ORDER BY rowid LIMIT 1").fetchone()
        report=json.loads(row[0]);report.update(completion='complete',review={'status':'verified','issues':[]},
            revision={'kind':'review_question','parent_report_id':'unrelated-report'})
        self.conn.execute('INSERT INTO agent_reports VALUES(?,?,?,?,?)',
            ('unrelated-review','paper-test',report['source_sha256'],json.dumps(report),'later'))
        event=self.originals()['2']['events'][0]
        self.assertFalse(event['verified']);self.assertIsNone(event['verified_by_report_id'])

    def test_projection_is_read_only_and_does_not_relabel_original_events(self):
        self.initial(verified=False)
        before=[tuple(r) for r in self.conn.execute('SELECT rowid,* FROM learning_events WHERE question_id=?',('paper-test-q-02',))]
        self.review();changes=self.conn.total_changes
        first=self.originals();second=self.originals()
        self.assertEqual(first,second);self.assertEqual(changes,self.conn.total_changes)
        self.assertEqual(before,[tuple(r) for r in self.conn.execute('SELECT rowid,* FROM learning_events WHERE question_id=?',('paper-test-q-02',))])


if __name__=='__main__':unittest.main()
