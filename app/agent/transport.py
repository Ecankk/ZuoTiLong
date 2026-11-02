"""Codex JSON-RPC process transport, independent of study state."""
import json,os,queue,shutil,subprocess,threading
from pathlib import Path
from app.agent.errors import AgentUnavailable


def codex_executable():
    configured = os.environ.get('MATHLENS_CODEX_BIN')
    if configured:
        return shutil.which(configured) or (configured if Path(configured).is_file() else None)
    executable = shutil.which('codex')
    if executable:return executable
    fallback = Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs/OpenAI/Codex/bin/codex.exe'
    return str(fallback) if fallback.is_file() else None

class CodexProcess:
    def __init__(self, root, data, notify, disconnected):
        executable = codex_executable()
        if not executable:
            raise AgentUnavailable('not_installed', '未安装学习服务，请先完成安装。')
        self.notify, self.disconnected = notify, disconnected
        self.pending, self.serial = {}, 0
        self.lock = threading.Lock()
        self.closed = False
        self.log = (data / "codex.stderr.log").open("a", encoding="utf-8")
        env = os.environ.copy()
        env["MATHLENS_DATA_DIR"] = str(data)
        self.process = subprocess.Popen([executable, "app-server", "--listen", "stdio://"],
            cwd=root, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=self.log, text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            for line in self.process.stdout:
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if "method" in message:
                    self.notify(message)
                elif "id" in message:
                    with self.lock:
                        waiter = self.pending.get(message["id"])
                    if waiter:
                        waiter.put(message)
        finally:
            with self.lock:
                for waiter in self.pending.values():
                    waiter.put({"error": {"message": "Codex 进程连接已断开"}})
            if not self.closed:
                self.disconnected("Codex 进程连接已断开，当前输入已保存。")

    def send(self, message):
        with self.lock:
            self.process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
            self.process.stdin.flush()

    def request(self, method, params, timeout=45):
        with self.lock:
            self.serial += 1
            request_id = self.serial
            waiter = queue.Queue()
            self.pending[request_id] = waiter
        try:
            self.send({"id": request_id, "method": method, "params": params})
            try:
                response = waiter.get(timeout=timeout)
            except queue.Empty:
                raise TimeoutError(f"Codex 请求 {method} 超时；请重新连接核对状态。") from None
            if "error" in response:
                raise RuntimeError(response["error"].get("message", str(response["error"])))
            return response.get("result", {})
        finally:
            with self.lock:
                self.pending.pop(request_id, None)

    def close(self):
        self.closed = True
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.log.close()
