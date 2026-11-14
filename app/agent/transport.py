"""Codex JSON-RPC process transport, independent of study state."""
import json,os,queue,shutil,subprocess,threading
import logging
from logging.handlers import RotatingFileHandler
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
        if os.name=='nt' and Path(executable).suffix.lower() in ('.cmd','.bat'):
            raise AgentUnavailable('other','已找到学习服务，但不能可靠启动此批处理安装。请选择原生 codex.exe。')
        self.notify, self.disconnected = notify, disconnected
        self.pending, self.serial = {}, 0
        self.lock = threading.Lock()
        self.closed = False
        self.log = RotatingFileHandler(data/'codex.stderr.log',maxBytes=5*1024*1024,backupCount=2,encoding='utf8',delay=True)
        env = os.environ.copy()
        env["MATHLENS_DATA_DIR"] = str(data)
        try:
            self.process = subprocess.Popen([executable, "app-server", "--listen", "stdio://"],
                cwd=root, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        except OSError as exc:
            self.log.close()
            raise AgentUnavailable('other','已找到学习服务，但不能启动。请确认权限并选择原生 codex.exe。'+str(exc)) from exc
        self.reader=threading.Thread(target=self._read,daemon=True,name='codex-rpc-reader')
        self.stderr_reader=threading.Thread(target=self._stderr,daemon=True,name='codex-stderr-reader')
        self.reader.start();self.stderr_reader.start()

    def _stderr(self):
        for line in iter(lambda:self.process.stderr.readline(4096),''):
            self.log.emit(logging.makeLogRecord(dict(msg=line.rstrip('\r\n'),levelno=logging.WARNING,levelname='WARNING')))

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
        if self.closed:return
        self.closed = True
        with self.lock:
            try:self.process.stdin.close()
            except OSError:pass
        if self.process.poll() is None:
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:self.process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    self.process.kill();self.process.wait(timeout=2)
        self.reader.join(timeout=2);self.stderr_reader.join(timeout=2)
        for stream,thread in ((self.process.stdout,self.reader),(self.process.stderr,self.stderr_reader)):
            if not thread.is_alive():stream.close()
        self.log.close()
