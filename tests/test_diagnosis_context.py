import json
import copy
import hashlib
import unittest
from unittest.mock import patch

import test_learning_loop as fixtures
from app.agent.workspace import workspace_context, read_task_package
from app.bank.access import preferences, save_preferences, save_agent_prompt, DEFAULT_AGENT_PROMPT
from app.agent.tools import execute
from app.learning.loop import apply_report, loop_snapshot
import database_fixture as server


class DiagnosisContextTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.LearningLoopTests()
        self.fixture.setUp()
        self.conn=self.fixture.conn
        self.conn.execute('UPDATE papers SET source_sha256=? WHERE id=?',(self.fixture.digest,'paper-test'))
        self.folder=self.fixture.root/'tasks/paper-test'
        self.folder.mkdir(parents=True)
        self.task={'paper_id':'paper-test','source_sha256':self.fixture.digest,'questions':[{'number':1,'stem':'OCR draft'}]}
        (self.folder/'request.json').write_text(json.dumps(self.task),encoding='utf8')
        self.conn.commit()

    def tearDown(self):
        self.fixture.tearDown()

    def test_focused_context_contains_task_json_and_personal_convention_without_writes(self):
        value=save_preferences(self.conn,{'study_type':1,'paper_marking_convention':'黑字是考试作答，红字是事后批改。'})
        self.conn.commit();before=self.conn.total_changes
        context=workspace_context(self.conn,self.fixture.root,'paper-test')
        self.assertEqual(context['task_packages'][0]['task'],self.task)
        self.assertEqual(context['preferences']['paper_marking_convention'],value['paper_marking_convention'])
        self.assertEqual(before,self.conn.total_changes)

    def test_default_is_present_and_old_settings_client_preserves_convention(self):
        self.assertEqual(preferences(self.conn)['paper_marking_convention'],DEFAULT_AGENT_PROMPT)
        save_preferences(self.conn,{'study_type':1,'paper_marking_convention':'personal convention'})
        saved=save_preferences(self.conn,{'study_type':2,'reserved':[]})
        self.assertEqual(saved['paper_marking_convention'],'personal convention')
        for invalid in (None,{},'x'*1001):
            with self.assertRaises(ValueError):save_preferences(self.conn,{'study_type':1,'paper_marking_convention':invalid})

    def test_prompt_only_save_preserves_other_preferences_and_can_restore_default(self):
        initial=save_preferences(self.conn,{'study_type':3,'mask_same_type':False,'reserved':[{'math_type':1,'year':'2025'}]})
        saved=save_agent_prompt(self.conn,{'prompt':'蓝色是作答，绿色是批改。'})
        self.assertEqual(saved['paper_marking_convention'],'蓝色是作答，绿色是批改。')
        for key in ('study_type','mask_same_type','reserved'):self.assertEqual(saved[key],initial[key])
        self.assertEqual(save_agent_prompt(self.conn,{'prompt':'  '})['paper_marking_convention'],DEFAULT_AGENT_PROMPT)
        with self.assertRaises(ValueError):save_agent_prompt(self.conn,{'prompt':'override','study_type':1})

    def test_legacy_empty_prompt_uses_default_without_rewriting_settings(self):
        self.conn.execute('UPDATE preferences SET payload=? WHERE id=1',(json.dumps({'study_type':1,'reserved':[],'paper_marking_convention':''}),))
        before=self.conn.total_changes
        self.assertEqual(preferences(self.conn)['paper_marking_convention'],DEFAULT_AGENT_PROMPT)
        self.assertEqual(self.conn.total_changes,before)

    def test_task_paths_missing_and_wrong_paper_are_explicit(self):
        self.assertFalse(read_task_package(self.fixture.root,'missing')['available'])
        with self.assertRaises(ValueError):read_task_package(self.fixture.root,'../outside')
        (self.folder/'request.json').write_text('{"paper_id":"other"}',encoding='utf8')
        with self.assertRaises(ValueError):read_task_package(self.fixture.root,'paper-test')

    def test_existing_skill_tool_supplies_contract_without_shell_or_new_session(self):
        with patch('app.agent.tools.connection',lambda data:server.connect()):
            result=json.loads(execute(fixtures.ROOT,self.fixture.root,'read_skill',{'name':'paper-diagnosis'})[0]['text'])
        self.assertEqual(result['report_contract'],(fixtures.ROOT/'docs/agent-workflow.md').read_text(encoding='utf-8'))
        self.assertIn('task_packages',result['instructions'])
        self.assertTrue(result['knowledge_catalog'])
        self.assertFalse(result['catalog_policy']['new_nodes_allowed'])

    def test_report_guidance_does_not_depend_on_specific_markdown_headings(self):
        root=self.fixture.root/'renamed-docs'
        skill=root/'.agents/skills/mathlens-paper-diagnosis/SKILL.md'
        skill.parent.mkdir(parents=True)
        skill.write_text('test diagnosis skill',encoding='utf-8')
        (root/'docs').mkdir()
        guidance='## Renamed guidance\nUse the task result_schema; expected_count is required.'
        (root/'docs/agent-workflow.md').write_text(guidance,encoding='utf-8')
        with patch('app.agent.tools.connection',lambda data:server.connect()):
            result=json.loads(execute(root,self.fixture.root,'read_skill',{'name':'paper-diagnosis'})[0]['text'])
        self.assertEqual(result['report_contract'],guidance)

    def test_bank_skill_reads_updated_source_catalog_without_restarting_session(self):
        root=self.fixture.root/'skill-project'
        skill=root/'.agents/skills/mathlens-bank-search/SKILL.md'
        skill.parent.mkdir(parents=True)
        skill.write_text('test skill',encoding='utf8')
        docs=root/'docs';docs.mkdir()
        catalog=docs/'question-sources.md'
        interface=docs/'bank-source-interface.md'
        catalog.write_text('source revision one: candidate only',encoding='utf8')
        interface.write_text('supported test interface',encoding='utf8')
        with patch('app.agent.tools.connection',lambda data:server.connect()):
            first=json.loads(execute(root,self.fixture.root,'read_skill',{'name':'bank-search'})[0]['text'])
            catalog.write_text('source revision two: still candidate only',encoding='utf8')
            second=json.loads(execute(root,self.fixture.root,'read_skill',{'name':'bank-search'})[0]['text'])
        self.assertNotEqual(first['source_catalog']['sha256'],second['source_catalog']['sha256'])
        self.assertEqual(second['source_catalog']['text'],catalog.read_text(encoding='utf8'))
        self.assertEqual(second['source_catalog']['sha256'],hashlib.sha256(catalog.read_bytes()).hexdigest())
        self.assertEqual(second['source_interface']['text'],interface.read_text(encoding='utf8'))
        self.assertEqual(second['source_catalog']['path'],'docs/question-sources.md')
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM bank_questions').fetchone()[0],1)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM probe_attempts').fetchone()[0],0)

    def test_missing_source_reference_is_not_reported_as_loaded(self):
        root=self.fixture.root/'incomplete-skill-project'
        skill=root/'.agents/skills/mathlens-bank-search/SKILL.md'
        skill.parent.mkdir(parents=True)
        skill.write_text('test skill',encoding='utf8')
        with patch('app.agent.tools.connection',lambda data:server.connect()):
            with self.assertRaises(FileNotFoundError):
                execute(root,self.fixture.root,'read_skill',{'name':'bank-search'})
        self.assertEqual(self.conn.execute('SELECT count(*) FROM tool_audit').fetchone()[0],0)

    def test_incomplete_new_reports_are_rejected_before_any_write(self):
        cases=[]
        for field in ('expected_count','summary','score_status','priorities','limitations'):
            candidate=copy.deepcopy(self.fixture.report);candidate.pop(field);cases.append(candidate)
        candidate=copy.deepcopy(self.fixture.report)
        candidate['questions'][0]['hypotheses']=[{'cause':'legacy field name'}];cases.append(candidate)
        candidate=copy.deepcopy(self.fixture.report);candidate['priorities']=42;cases.append(candidate)
        before=self.conn.total_changes
        for candidate in cases:
            with self.assertRaisesRegex(ValueError,'报告格式不完整'):apply_report(self.conn,'paper-test',candidate,fixtures.ROOT)
        self.assertEqual(before,self.conn.total_changes)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM agent_reports').fetchone()[0],0)

    def test_legacy_report_can_be_displayed_without_modifying_evidence(self):
        self.fixture.apply()
        report=copy.deepcopy(self.fixture.report);report.pop('summary');report['score_status']=None;report['priorities']=None
        serialized=json.dumps(report)
        self.conn.execute('UPDATE agent_reports SET report_json=?',(serialized,))
        question=copy.deepcopy(report['questions'][0]);question['reference_answer']=None
        question['hypotheses']=[{'cause':'待核对','evidence':'可见作答','alternatives':['时间不足','不会'],'minimal_check':'待用户确认'}]
        self.conn.execute('UPDATE question_diagnoses SET diagnosis_json=?',(json.dumps(question),))
        before=self.conn.total_changes
        snapshot=loop_snapshot(self.conn)
        self.assertTrue(snapshot['reports'][0]['needs_completion'])
        self.assertEqual(snapshot['reports'][0]['summary'],'')
        self.assertEqual(snapshot['reports'][0]['score_status'],'')
        self.assertEqual(snapshot['reports'][0]['limitations'],report['limitations'])
        self.assertIn('summary',snapshot['reports'][0]['validation_issues'])
        self.assertEqual(snapshot['reports'][0]['priorities'],[])
        q=next(iter(snapshot['diagnoses'].values()))
        self.assertEqual(q['reference_answer'],'')
        self.assertEqual(q['hypotheses'][0]['label'],'待核对')
        self.assertEqual(q['hypotheses'][0]['alternative'],'时间不足；不会')
        self.assertEqual(q['hypotheses'][0]['correction'],'')
        self.assertEqual(q['hypotheses'][0]['minimal_check'],'待用户确认')
        self.assertEqual(before,self.conn.total_changes)
        self.assertEqual(self.conn.execute('SELECT report_json FROM agent_reports LIMIT 1').fetchone()[0],serialized)


if __name__=='__main__':unittest.main()
