"""Real Codex smoke test in isolated data; never writes student attempts."""
import json
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from codex_bridge import CodexBridge


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
        bridge.submit("继续刚才的连接验收，不使用工具、不读写文件。只回复我上一轮给你的校验词。", str(uuid.uuid4()))
        result = wait(bridge, lambda s: s["can_submit"])
        remembered = token in ''.join(m['text'] for m in result['turns'][-1]['messages'])
        assert remembered, "Session did not retain the first turn"
        report = {"two_real_turns": True, "same_session_after_restart": True, "remembered_token": remembered, "locked_while_running": locked, "test_data": str(data)}
        (data / 'validation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report), flush=True)
    finally:
        bridge.close()


if __name__ == '__main__':
    main()
