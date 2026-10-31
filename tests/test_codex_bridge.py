import json
from contextlib import closing
import hashlib
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from email.message import Message
import uuid
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.agent.bridge import CodexBridge, BridgeConflict


class FakeCodex:
    def __init__(self, root, data, notify, disconnected):
        self.notify = notify
        self.calls, self.sent, self.history, self.items = [], [], [], []

    def request(self, method, params):
        self.calls.append((method, params))
        if method in ("thread/start", "thread/resume"):
            return {"thread": {"id": "fixed-test-session"}, 'model':'gpt-6-luna','reasoningEffort':'xhigh'}
        if method == 'model/list':
            return {'data':[{'model':'gpt-6-luna','supportedReasoningEfforts':[{'reasoningEffort':'xhigh'}]}]}
        if method == "turn/start":
            return {"turn": {"id": f"turn-{len(self.calls)}"}}
        if method == "thread/turns/list":
            return {"data": self.history}
        if method == "thread/items/list":
            return {"data": self.items}
        return {}

    def send(self, message):
        self.sent.append(message)

    def close(self):
        pass


class CodexBridgeTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "tmp").mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / "tmp", prefix="bridge-test-")
        self.data = Path(self.tmp.name)
        self.bridge = CodexBridge(ROOT, self.data, FakeCodex)
        self.bridge.connect()
        self.wait(lambda: self.bridge.connected)

    def tearDown(self):
        self.bridge.close()
        self.assertEqual(self.data.resolve().parent, (ROOT / "tmp").resolve())
        self.tmp.cleanup()

    def wait(self, predicate):
        deadline = time.monotonic() + 3
        while not predicate():
            if time.monotonic() > deadline:
                self.fail("background operation did not finish")
            time.sleep(.01)

    def send(self, text="测试输入"):
        rid = str(uuid.uuid4())
        self.bridge.submit(text, rid)
        self.wait(lambda: self.bridge.state["turns"][-1]["codex_turn_id"] is not None)
        return rid, self.bridge.state["turns"][-1]["codex_turn_id"]

    def event(self, method, tid, **params):
        self.bridge.event({"method": method, "params": {"threadId": "fixed-test-session", "turnId": tid, **params}})

    def finish(self, tid, phase="final_answer", status="completed"):
        self.event("item/completed", tid, item={"id": "message", "type": "agentMessage", "phase": phase, "text": "已核对，完整反馈。"})
        self.event("turn/completed", tid, turn={"id": tid, "status": status})

    def test_only_final_feedback_and_completed_turn_unlock(self):
        _, tid = self.send()
        self.event("item/agentMessage/delta", tid, itemId="message", delta="正在看题")
        self.assertFalse(self.bridge.snapshot()["can_submit"])
        self.event("item/completed", tid, item={"id": "message", "type": "agentMessage", "phase": "final_answer", "text": "最终回答"})
        self.assertFalse(self.bridge.snapshot()["can_submit"])
        self.event("turn/completed", tid, turn={"id": tid, "status": "completed"})
        self.assertTrue(self.bridge.snapshot()["can_submit"])
        self.assertTrue(self.bridge.state['turns'][-1]['finished_at'])

    def test_model_default_applied_once_and_reconnect_follows_codex_on_same_session(self):
        starts = [p for m,p in self.bridge.transport.calls if m == 'thread/start']
        self.assertEqual(starts[0]['model'], 'gpt-6-luna')
        self.assertEqual(starts[0]['config']['model_reasoning_effort'], 'xhigh')
        class ExternalSelection(FakeCodex):
            def request(self, method, params):
                result = super().request(method, params)
                if method == 'thread/resume':
                    result.update(model='gpt-6-sol', reasoningEffort='low')
                return result
        sid = self.bridge.state['session_id']
        self.bridge.release()
        self.assertTrue(self.bridge.snapshot()['input_locked'])
        with self.assertRaises(BridgeConflict):self.bridge.assert_user_write_allowed()
        self.bridge.close()
        self.bridge = CodexBridge(ROOT, self.data, ExternalSelection)
        self.bridge.connect();self.wait(lambda:self.bridge.connected)
        self.assertEqual(self.bridge.state['session_id'], sid)
        resume = next(p for m,p in self.bridge.transport.calls if m == 'thread/resume')
        self.assertNotIn('model', resume);self.assertNotIn('config', resume)
        self.assertFalse(any(m == 'thread/start' for m,_ in self.bridge.transport.calls))
        settings = self.bridge.snapshot()['model_settings']
        self.assertEqual((settings['model'], settings['effort']), ('gpt-6-sol','low'))
        self.assertFalse(self.bridge.snapshot()['external_control'])
        self.assertTrue(self.bridge.snapshot()['can_submit'])
        self.send()
        self.assertEqual(self.bridge.state['turns'][-1]['model_settings'],settings)
        sent = next(p for m,p in self.bridge.transport.calls if m == 'turn/start')
        self.assertNotIn('model',sent);self.assertNotIn('effort',sent)

    def test_running_or_unresolved_turn_cannot_release_session(self):
        _,tid = self.send()
        transport = self.bridge.transport
        with self.assertRaises(BridgeConflict):self.bridge.release()
        self.assertIs(self.bridge.transport,transport)
        self.finish(tid,status='interrupted')
        with self.assertRaises(BridgeConflict):self.bridge.release()

    def test_active_writer_conflict_does_not_create_replacement_session(self):
        class BusyCodex(FakeCodex):
            def request(self,method,params):
                if method == 'thread/resume':
                    self.calls.append((method,params))
                    raise RuntimeError('thread already has an active writer')
                return super().request(method,params)
        sid = self.bridge.state['session_id']
        self.bridge.close();self.bridge=CodexBridge(ROOT,self.data,BusyCodex)
        self.bridge.connect();self.wait(lambda:self.bridge.state.get('error'))
        self.assertIn('占用',self.bridge.state['error'])
        self.assertEqual(self.bridge.state['session_id'],sid)
        self.assertFalse(any(m=='thread/start' for m,_ in self.bridge.transport.calls))
        self.assertFalse(self.bridge.snapshot()['can_submit'])
        self.assertTrue(self.bridge.snapshot()['external_control'])
        self.assertTrue(self.bridge.snapshot()['input_locked'])

    def test_idle_reconnect_rejects_foreign_running_turn_without_new_session(self):
        sid=self.bridge.state['session_id']
        self.bridge.close()
        clients=[]
        def factory(root,data,notify,disconnected):
            transport=FakeCodex(root,data,notify,disconnected)
            transport.history=[{'id':'desktop-turn','status':'inProgress'}]
            clients.append(transport)
            return transport
        self.bridge=CodexBridge(ROOT,self.data,factory)
        self.bridge.connect();self.wait(lambda:bool(self.bridge.state.get('error')))
        state=self.bridge.snapshot()
        self.assertEqual(state['session_id'],sid)
        self.assertFalse(state['connected']);self.assertFalse(state['can_submit'])
        self.assertTrue(state['input_locked']);self.assertTrue(state['external_control'])
        self.assertFalse(any(m in ('thread/start','turn/start') for m,_ in clients[0].calls))

    def test_dispatch_does_not_steer_a_foreign_running_turn(self):
        transport=self.bridge.transport
        transport.history=[{'id':'desktop-turn','status':'inProgress'}]
        self.bridge.submit('do not steer',str(uuid.uuid4()))
        self.wait(lambda:self.bridge.state['status']=='disconnected')
        self.assertFalse(any(m=='turn/start' for m,_ in transport.calls))
        self.assertTrue(self.bridge.snapshot()['input_locked'])
        self.assertTrue(self.bridge.snapshot()['external_control'])
        self.assertEqual(self.bridge._active()['status'],'failed')

    def test_closed_session_fences_old_events_and_reconnects_same_id(self):
        sid=self.bridge.state['session_id'];generation=self.bridge.generation
        self.bridge.event({'method':'thread/closed','params':{'threadId':sid}},generation)
        self.assertFalse(self.bridge.snapshot()['connected'])
        self.assertTrue(self.bridge.snapshot()['input_locked'])
        self.bridge.event({'method':'thread/settings/updated','params':{'threadId':sid,
                          'threadSettings':{'model':'wrong','effort':'low'}}},generation)
        self.assertEqual(self.bridge.state['model_settings']['model'],'gpt-6-luna')
        self.bridge.connect();self.wait(lambda:self.bridge.snapshot()['can_submit'])
        self.assertEqual(self.bridge.state['session_id'],sid)
        self.assertFalse(self.bridge.snapshot()['external_control'])
        self.assertFalse(any(m=='thread/start' for m,_ in self.bridge.transport.calls))

    def test_unsolicited_remote_turn_blocks_idle_web_writes(self):
        self.event('turn/started','desktop-turn',turn={'id':'desktop-turn','status':'inProgress'})
        self.assertFalse(self.bridge.snapshot()['connected'])
        self.assertTrue(self.bridge.snapshot()['input_locked'])
        self.assertFalse(self.bridge.state['turns'])
        with self.assertRaises(BridgeConflict):self.bridge.submit('blocked',str(uuid.uuid4()))

    def test_pending_chain_cannot_be_released_between_stages(self):
        self.bridge.state['pending_chain']={'paper_id':'paper','request_id':'queued','workflow_id':'workflow'}
        with self.assertRaises(BridgeConflict):self.bridge.release()
        self.assertTrue(self.bridge.connected)

    def test_model_unavailable_is_not_silently_replaced(self):
        self.bridge.release()
        with self.bridge.lock:
            self.bridge.state.pop('model_policy_version',None);self.bridge._save()
        class NoModel(FakeCodex):
            def request(self,method,params):
                if method=='model/list':self.calls.append((method,params));return {'data':[]}
                return super().request(method,params)
        self.bridge.transport_factory=NoModel
        self.bridge.connect();self.wait(lambda:self.bridge.state.get('error'))
        self.assertIn('未提供',self.bridge.state['error'])
        self.assertFalse(any(m in ('thread/start','thread/resume') for m,_ in self.bridge.transport.calls))

    def test_reasoning_commentary_and_unclassified_deltas_are_not_web_feedback(self):
        _,tid=self.send()
        self.event('item/reasoning/summaryTextDelta',tid,itemId='reason',delta='internal reasoning')
        self.event('item/agentMessage/delta',tid,itemId='progress',delta='uncategorized progress')
        self.assertEqual(self.bridge.snapshot()['turns'][-1]['messages'],[])
        self.event('item/completed',tid,item={'id':'progress','type':'agentMessage','phase':'commentary','text':'internal progress'})
        self.assertEqual(self.bridge.snapshot()['turns'][-1]['messages'],[])
        self.event('item/started',tid,item={'id':'answer','type':'agentMessage','phase':'final_answer','text':''})
        self.event('item/agentMessage/delta',tid,itemId='answer',delta='给学生的解释')
        self.assertEqual(self.bridge.snapshot()['turns'][-1]['messages'][0]['text'],'给学生的解释')
        self.assertFalse(self.bridge.snapshot()['can_submit'])
        self.finish(tid)
        self.assertTrue(self.bridge.snapshot()['can_submit'])
        self.assertNotIn('internal',json.dumps(self.bridge.snapshot(),ensure_ascii=False))

    def test_settings_event_is_visible_when_idle_and_from_current_generation_only(self):
        self.bridge.event({'method':'thread/settings/updated','params':{'threadId':self.bridge.state['session_id'],
            'threadSettings':{'model':'gpt-6-luna','effort':'high'}}},self.bridge.generation)
        self.assertEqual(self.bridge.snapshot()['model_settings']['effort'],'high')
        self.bridge.event({'method':'thread/settings/updated','params':{'threadId':self.bridge.state['session_id'],
            'threadSettings':{'model':'stale','effort':'low'}}},self.bridge.generation-1)
        self.assertEqual(self.bridge.snapshot()['model_settings']['model'],'gpt-6-luna')

    def test_custom_prompt_is_attached_at_top_without_paper(self):
        with closing(sqlite3.connect(self.data/'mathlens.db')) as conn,conn:
            conn.execute('CREATE TABLE preferences(id INTEGER PRIMARY KEY,payload TEXT NOT NULL)')
            conn.execute('INSERT INTO preferences VALUES(1,?)',(json.dumps({'study_type':1,'reserved':[],'paper_marking_convention':'蓝色为独立作答，绿色为事后批改。'}),))
        self.bridge.submit('分析试卷',str(uuid.uuid4()))
        text=self.bridge.state['turns'][-1]['inputs'][0]['text']
        self.assertIn('蓝色为独立作答',text)
        self.assertIn('task_packages',text)
        self.assertLess(text.index('蓝色为独立作答'),text.index('MathLens 网页请求'))
        self.assertEqual(self.bridge.state['turns'][-1]['agent_prompt'],'蓝色为独立作答，绿色为事后批改。')

    def test_default_prompt_and_next_turn_change_keep_original_snapshot(self):
        from app.bank.access import DEFAULT_AGENT_PROMPT
        _,tid=self.send()
        original=self.bridge.state['turns'][-1]
        self.assertEqual(original['agent_prompt'],DEFAULT_AGENT_PROMPT)
        self.assertTrue(original['inputs'][0]['text'].startswith('【MathLens 默认提示词】\n'+DEFAULT_AGENT_PROMPT))
        self.finish(tid)
        with closing(sqlite3.connect(self.data/'mathlens.db')) as conn,conn:
            conn.execute('CREATE TABLE preferences(id INTEGER PRIMARY KEY,payload TEXT NOT NULL)')
            conn.execute('INSERT INTO preferences VALUES(1,?)',(json.dumps({'study_type':1,'reserved':[],'paper_marking_convention':'新的用户约定'}),))
        self.send()
        self.assertEqual(self.bridge.state['turns'][-1]['agent_prompt'],'新的用户约定')
        self.assertEqual(original['agent_prompt'],DEFAULT_AGENT_PROMPT)
        self.assertIn(DEFAULT_AGENT_PROMPT,original['inputs'][0]['text'])

    def test_connect_is_not_ready_until_reconciliation_finishes(self):
        self.bridge.close();self.bridge=CodexBridge(ROOT,self.data,FakeCodex)
        entered=threading.Event();release=threading.Event()
        def reconcile(_transport):
            entered.set();release.wait(3)
        self.bridge._reconcile=reconcile
        self.bridge.connect()
        self.assertTrue(entered.wait(2))
        try:
            self.assertFalse(self.bridge.snapshot()['can_submit'])
            self.assertTrue(self.bridge.snapshot()['input_locked'])
            with self.assertRaises(BridgeConflict):self.bridge.submit('不能抢跑',str(uuid.uuid4()))
            transport=self.bridge.transport
            self.bridge.connect()
            self.assertIs(self.bridge.transport,transport)
        finally:release.set()
        self.wait(lambda:self.bridge.snapshot()['can_submit'])

    def test_missing_empty_session_is_recovered_but_history_is_never_replaced(self):
        class MissingRollout(FakeCodex):
            def request(self,method,params):
                if method=='thread/resume':
                    self.calls.append((method,params));raise RuntimeError('no rollout found for thread id old')
                if method=='thread/start':
                    self.calls.append((method,params));return {'thread':{'id':'recovered-session'}}
                return super().request(method,params)
        self.bridge.close();self.bridge=CodexBridge(ROOT,self.data,MissingRollout)
        self.bridge.connect();self.wait(lambda:self.bridge.snapshot()['can_submit'])
        self.assertEqual(self.bridge.state['session_id'],'recovered-session')
        self.assertTrue(self.bridge.state['connection_notice'])
        self.assertTrue(any(m=='thread/name/set' for m,_ in self.bridge.transport.calls))
        self.send();self.bridge.close();self.bridge=CodexBridge(ROOT,self.data,MissingRollout)
        self.bridge.connect();self.wait(lambda:self.bridge.state.get('error'))
        self.assertTrue(self.bridge.snapshot()['input_locked'])
        self.assertFalse(any(m=='thread/start' for m,_ in self.bridge.transport.calls))

    def test_photo_only_message_attaches_validated_image_to_codex(self):
        from PIL import Image
        from io import BytesIO
        from app.storage.images import init_answer_images, save_answer_image
        raw=BytesIO();Image.new('RGB',(60,40),'white').save(raw,format='PNG')
        with closing(sqlite3.connect(self.data/'mathlens.db')) as conn,conn:
            conn.row_factory=sqlite3.Row;init_answer_images(conn)
            asset=save_answer_image(conn,self.data,raw.getvalue())
        rid=str(uuid.uuid4());self.bridge.submit('',rid,image_ids=[asset['id']])
        self.wait(lambda:self.bridge.state['turns'][-1]['codex_turn_id'])
        turn=self.bridge.state['turns'][-1]
        self.assertEqual(turn['image_ids'],[asset['id']])
        self.assertEqual(turn['inputs'][-1]['type'],'localImage')
        self.assertTrue(Path(turn['inputs'][-1]['path']).is_file())
        self.assertFalse(self.bridge.snapshot()['can_submit'])
        self.bridge.submit('',rid,image_ids=[asset['id']])
        self.assertEqual(len(self.bridge.state['turns']),1)

    def test_page_only_context_does_not_require_a_paper_or_database(self):
        context = {"screen": {"view": "本地题库", "label": "题库列表", "section": "检索"}}
        self.bridge.submit("解释这一页", str(uuid.uuid4()), context)
        self.assertFalse((self.data / "mathlens.db").exists())
        self.assertIn('题库列表', self.bridge.state["turns"][-1]["inputs"][0]["text"])
        self.assertEqual(len(self.bridge.state["turns"][-1]["inputs"]), 1)

    def test_screen_schema_rejects_unbounded_or_unsupported_content(self):
        for screen in ({"url": "file:///private"}, {"view": {}}, {"expanded": ["x"] * 17}, {"label": "x" * 2001}):
            with self.assertRaises(ValueError):
                self.bridge.submit("测试", str(uuid.uuid4()), {"screen": screen})
        self.assertEqual(self.bridge.state["turns"], [])

    def test_followed_question_and_manual_override_attach_the_correct_region(self):
        import pymupdf
        pdf = self.data / "fixture.pdf"
        with pymupdf.open() as doc:
            for color in ((1,0,0), (0,0,1)):
                page = doc.new_page(width=100, height=100)
                page.draw_rect(page.rect, fill=color)
            doc.save(pdf)
            doc[0].get_pixmap().save(self.data / "probe.png")
        with closing(sqlite3.connect(self.data / "mathlens.db")) as conn, conn:
            conn.row_factory=sqlite3.Row
            conn.executescript("CREATE TABLE papers(id TEXT,source_path TEXT); CREATE TABLE questions(id TEXT,paper_id TEXT,regions_json TEXT); CREATE TABLE diagnostic_probes(id TEXT,paper_id TEXT,question_id TEXT,bank_id TEXT); CREATE TABLE bank_resources(bank_id TEXT,question_path TEXT);")
            conn.execute("INSERT INTO papers VALUES('paper',?)", (str(pdf),))
            conn.execute("INSERT INTO diagnostic_probes VALUES('probe','paper','q1','bank')")
            conn.execute("INSERT INTO bank_resources VALUES('bank','probe.png')")
            from app.bank.access import init_access, reveal
            conn.execute('CREATE TABLE bank_questions(id TEXT)');conn.execute("INSERT INTO bank_questions VALUES('bank')")
            conn.execute('CREATE TABLE bank_exposures(bank_id TEXT,created_at TEXT)');init_access(conn);reveal(conn,'bank','question',True)
            for index in (1, 2):
                conn.execute("INSERT INTO questions VALUES(?, 'paper', ?)", (f"q{index}", json.dumps([{"page": index, "bbox": [0,0,100,100]}])))
        images = []
        for index in (1, 2):
            context = {"paper_id": "paper", "question_id": f"q{index}", "screen": {"view": "今日工作", "paper_id": "paper", "question_id": "q1", "probe_id": "probe", "bank_id": "bank", "expanded": ["这道题的指纹"]}}
            self.bridge.submit("解释这道题", str(uuid.uuid4()), context)
            self.wait(lambda: self.bridge.state["turns"][-1]["codex_turn_id"] is not None)
            turn = self.bridge.state["turns"][-1]
            images.append(hashlib.sha256(Path(turn["inputs"][1]["path"]).read_bytes()).hexdigest())
            self.assertEqual(turn["context"]["screen"]["question_id"], "q1")
            self.assertEqual(len(turn["inputs"]), 3 if index == 1 else 2)
            self.finish(turn["codex_turn_id"])
        self.assertNotEqual(images[0], images[1])
        with self.assertRaises(ValueError):
            self.bridge.submit("测试", str(uuid.uuid4()), {"screen": {"question_id": "not-found"}})
        with self.assertRaises(ValueError):
            self.bridge.submit("测试", str(uuid.uuid4()), {"screen": {"question_id": "q2", "probe_id": "probe"}})

    def test_duplicate_retry_is_idempotent_and_other_input_is_rejected(self):
        rid, _ = self.send()
        self.bridge.submit("测试输入", rid)
        self.assertEqual(len(self.bridge.state["turns"]), 1)
        with self.assertRaises(BridgeConflict):
            self.bridge.submit("另一条输入", str(uuid.uuid4()))
        with self.assertRaises(BridgeConflict):
            self.bridge.submit("不同内容", rid)

    def test_competing_tabs_only_accept_one_new_turn(self):
        barrier = threading.Barrier(3)
        accepted, rejected = [], []
        def send():
            barrier.wait()
            try:
                self.bridge.submit("同一时刻发送", str(uuid.uuid4()));accepted.append(1)
            except BridgeConflict:
                rejected.append(1)
        threads = [threading.Thread(target=send) for _ in range(2)]
        for t in threads:t.start()
        barrier.wait()
        for t in threads:t.join()
        self.wait(lambda: self.bridge.state["turns"][-1]["codex_turn_id"] is not None)
        self.assertEqual((len(accepted), len(rejected)), (1, 1))

    def test_commentary_alone_or_failure_does_not_unlock(self):
        _, tid = self.send()
        self.finish(tid, phase="commentary")
        self.assertEqual(self.bridge.snapshot()["status"], "failed")
        self.assertTrue(self.bridge.snapshot()["input_locked"])

    def test_foreign_and_old_turn_events_cannot_unlock(self):
        _, tid = self.send()
        self.finish("unrelated-turn")
        self.assertTrue(self.bridge.snapshot()["input_locked"])
        self.finish(tid, status="interrupted")
        self.bridge.transport.history = [{"id": tid, "status": "interrupted"}]
        self.bridge.retry()
        self.wait(lambda: self.bridge.state["turns"][-1]["codex_turn_id"] is not None)
        new_tid = self.bridge.state["turns"][-1]["codex_turn_id"]
        self.assertNotEqual(new_tid, tid)
        self.finish(tid)
        self.assertTrue(self.bridge.snapshot()["input_locked"])
        self.finish(new_tid)
        self.assertTrue(self.bridge.snapshot()["can_submit"])

    def test_restart_recovers_same_session_and_persisted_lock(self):
        rid, tid = self.send()
        self.bridge.close()
        self.bridge = CodexBridge(ROOT, self.data, FakeCodex)
        self.assertTrue(self.bridge.snapshot()["input_locked"])
        self.assertEqual(self.bridge.state["active_request"], rid)
        self.bridge.connect()
        self.wait(lambda: self.bridge.connected and self.bridge.state["status"] != "connecting")
        self.wait(lambda: any(m == "thread/turns/list" for m, _ in self.bridge.transport.calls))
        self.assertEqual(self.bridge.state["session_id"], "fixed-test-session")
        self.assertTrue(any(m == "thread/resume" for m, _ in self.bridge.transport.calls))
        self.bridge.transport.history = [{"id": tid, "status": "completed"}]
        self.bridge.transport.items = [{"id": "saved", "type": "agentMessage", "phase": "final_answer", "text": "断线期间已完成的反馈"}]
        self.bridge._reconcile(self.bridge.transport)
        self.assertTrue(self.bridge.snapshot()["can_submit"])

    def test_approval_is_not_automatic_and_is_one_time(self):
        _, tid = self.send()
        message = {"id": 81, "method": "item/commandExecution/requestApproval", "params": {"threadId": "fixed-test-session", "turnId": tid, "command": "test-command"}}
        self.bridge.event(message)
        self.assertEqual(self.bridge.state["status"], "waiting_user")
        self.assertFalse(any(m.get("id") == 81 for m in self.bridge.transport.sent))
        self.bridge.respond("81", {"decision": "decline"})
        self.assertEqual(self.bridge.transport.sent[-1], {"id": 81, "result": {"decision": "decline"}})
        self.assertTrue(self.bridge.snapshot()["input_locked"])
        with self.assertRaises(BridgeConflict):self.bridge.respond("81", {"decision": "accept"})
        self.bridge.event({**message, "id": 82, "params": {**message["params"], "availableDecisions": ["accept", "cancel"]}})
        self.bridge.respond("82", {"decision": "decline"})
        self.assertEqual(self.bridge.transport.sent[-1], {"id": 82, "result": {"decision": "cancel"}})

    def test_http_write_lock_and_cross_origin_rejection(self):
        from fastapi.testclient import TestClient
        from app.config import AppConfig
        from app.main import create_app
        config=AppConfig(ROOT,self.data,ROOT/'dist',self.data/'mathlens.db')
        self.send()
        with TestClient(create_app(config,bridge=self.bridge,agent_factory=None,manage_agent=False),base_url='http://127.0.0.1') as http:
            for path,origin,expected in [('/api/papers',None,409),('/api/preferences/agent-prompt',None,409),('/api/preferences/agent-prompt','https://unrelated.example',403)]:
                # Valid bodies reach the application write guard.
                body={'title':'test'} if path=='/api/papers' else {'prompt':'test'}
                response=http.post(path,json=body,headers={'Origin':origin} if origin else {})
                self.assertEqual(response.status_code,expected,response.text)



if __name__ == "__main__":
    unittest.main()
