"""Real Codex smoke test in isolated data; never writes student attempts."""
import json
from pathlib import Path
import sys
import time
import uuid
import sqlite3
from io import BytesIO
from contextlib import closing

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from codex_bridge import CodexBridge
from answer_images import init_answer_images, save_answer_image


def wait(bridge, predicate, seconds=180):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        state = bridge.snapshot()
        if predicate(state):
            return state
        if state["status"] in ("failed", "interrupted") or (state["status"] == "disconnected" and state.get("error")):
            raise RuntimeError(state.get("error"))
        if state.get("requests"):
            raise RuntimeError("Test needs user approval; no automatic approval performed")
        time.sleep(.25)
    raise TimeoutError("Codex test timed out")


def main():
    data = ROOT / "tmp" / ("codex-live-" + uuid.uuid4().hex[:8])
    bridge = CodexBridge(ROOT, data)
    try:
        bridge.connect()
        first = wait(bridge, lambda s: s["can_submit"])
        sid = first["session_id"]
        bridge.close()
        bridge = CodexBridge(ROOT, data)
        bridge.connect()
        resumed = wait(bridge, lambda s:s['can_submit'])
        zero_turn_same = resumed['session_id'] == sid
        assert zero_turn_same or resumed.get('connection_notice'), 'Empty-session recovery must be explicit'
        sid = resumed['session_id']
        print(json.dumps({"connected": True, "session_id": sid, "test_data": str(data)}), flush=True)
        token = "MATHLENS_" + uuid.uuid4().hex[:10]
        bridge.submit(f"这是 MathLens 连接验收，不是学习任务。不使用工具、不读写文件。请记住校验词 {token}，只回复这个校验词。", str(uuid.uuid4()))
        locked = bridge.snapshot()["input_locked"]
        result = wait(bridge, lambda s: s["can_submit"])
        assert token in ''.join(m['text'] for m in result['turns'][-1]['messages'])
        print(json.dumps({"first_turn": "completed", "locked_while_running": locked}), flush=True)
        bridge.close()
        bridge = CodexBridge(ROOT, data)
        bridge.connect()
        wait(bridge, lambda s: s["can_submit"])
        assert bridge.state['session_id'] == sid
        from PIL import Image, ImageDraw, ImageFont
        picture = Image.new('RGB',(750,220),'white')
        draw = ImageDraw.Draw(picture)
        draw.text((30,30),'TEST ANSWER',fill='black',font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',36))
        draw.text((30,100),'6 + 7 = 15',fill='black',font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',52))
        raw=BytesIO();picture.save(raw,format='PNG')
        with closing(sqlite3.connect(data/'mathlens.db')) as conn, conn:
            conn.row_factory=sqlite3.Row
            init_answer_images(conn)
            asset=save_answer_image(conn,data,raw.getvalue())
        bridge.submit("继续连接验收，不使用工具、不写文件。这是合成图片，不是真实学生作答。复述上一轮校验词，再读所附图片的算式，指出错误并给正确结果。", str(uuid.uuid4()), image_ids=[asset['id']])
        result = wait(bridge, lambda s: s["can_submit"])
        remembered = token in ''.join(m['text'] for m in result['turns'][-1]['messages'])
        assert remembered, "Session did not retain the first turn"
        image_read = '13' in ''.join(m['text'] for m in result['turns'][-1]['messages'])
        assert image_read, 'Codex did not evaluate the synthetic photographed answer'
        report = {"two_real_turns": True, "same_session_after_restart": True, "zero_turn_restart_same_session":zero_turn_same, "remembered_token": remembered, "answer_image_read":image_read, "locked_while_running": locked, "test_data": str(data)}
        (data / 'validation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report), flush=True)
    finally:
        bridge.close()


if __name__ == '__main__':
    main()
