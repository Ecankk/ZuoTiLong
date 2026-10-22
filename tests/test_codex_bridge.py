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
from codex_bridge import CodexBridge, BridgeConflict


class FakeCodex:
    def __init__(self, root, data, notify, disconnected):
        self.notify = notify
        self.calls, self.sent, self.history, self.items = [], [], [], []

    def request(self, method, params):
        self.calls.append((method, params))
        if method in ("thread/start", "thread/resume"):
            return {"thread": {"id": "fixed-test-session"}}
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
        from answer_images import init_answer_images,save_answer_image
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
            conn.executescript("CREATE TABLE papers(id TEXT,source_path TEXT); CREATE TABLE questions(id TEXT,paper_id TEXT,regions_json TEXT); CREATE TABLE diagnostic_probes(id TEXT,paper_id TEXT,question_id TEXT,bank_id TEXT); CREATE TABLE bank_resources(bank_id TEXT,question_path TEXT);")
            conn.execute("INSERT INTO papers VALUES('paper',?)", (str(pdf),))
            conn.execute("INSERT INTO diagnostic_probes VALUES('probe','paper','q1','bank')")
            conn.execute("INSERT INTO bank_resources VALUES('bank','probe.png')")
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
        import server
        previous = server.BRIDGE
        server.BRIDGE = self.bridge
        try:
            self.send()
            for origin, expected in [(None, 409), ("https://unrelated.example", 403)]:
                headers = Message();headers["Content-Type"] = "application/json";headers["Host"] = "127.0.0.1:4173"
                if origin:headers["Origin"] = origin
                handler = object.__new__(server.Handler)
                handler.path = "/api/papers";handler.headers = headers
                codes = [];handler.send_json = lambda body, code: codes.append(code)
                handler.do_POST()
                self.assertEqual(codes, [expected])
        finally:
            server.BRIDGE = previous


if __name__ == "__main__":
    unittest.main()
