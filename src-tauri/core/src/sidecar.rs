//! sidecar 子进程：CREATE_SUSPENDED → 入 Job → 恢复；stdin 控制、stdout 协议、stderr 日志三路并发。
//!
//! 两条输出管道各一个读线程，互不等待（避免 PIPE 写满挂起）。stdout 的每一行先原样写入
//! 日志，再按协议解析并核对 nonce 与“pid 属于本次 Job”，通过后经通道交给调用方。

use crate::logs::{self, SharedSink};
use crate::protocol::{self, Event, Parsed};
use std::ffi::OsString;
use std::io::{self, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, ExitStatus, Stdio};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError};
use std::sync::Arc;
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

#[cfg(windows)]
use crate::job::{self, Job};

pub struct SpawnSpec {
    pub program: PathBuf,
    pub args: Vec<OsString>,
    pub cwd: PathBuf,
    /// 完整的子进程环境（调用方用 [`crate::envpath::child_env`] 生成；不继承其他变量）。
    pub env: Vec<(OsString, OsString)>,
}

#[derive(Debug)]
pub enum Message {
    Event(Box<Event>),
    /// 协议主版本不认识。
    Fatal(String),
    /// 收到不属于本次启动或格式不对的行（只记录，供诊断）。
    Ignored(String),
    StdoutClosed,
}

pub enum Outcome {
    /// 收到 shutdown 后自行退出。
    Exited(ExitStatus),
    /// 超时后结束了整个 Job。
    Killed(Option<ExitStatus>),
}

pub struct Sidecar {
    child: Child,
    #[cfg(windows)]
    job: Arc<Job>,
    stdin: Option<ChildStdin>,
    nonce: String,
    rx: Receiver<Message>,
    readers: Vec<JoinHandle<()>>,
    stdout_sink: SharedSink,
    stderr_sink: SharedSink,
}

#[cfg(windows)]
impl Sidecar {
    pub fn spawn(
        spec: SpawnSpec,
        nonce: &str,
        stdout_sink: SharedSink,
        stderr_sink: SharedSink,
    ) -> io::Result<Self> {
        use std::os::windows::process::CommandExt;
        use windows_sys::Win32::System::Threading::{
            CREATE_NO_WINDOW, CREATE_SUSPENDED, CREATE_UNICODE_ENVIRONMENT,
        };

        let job = Arc::new(Job::new_kill_on_close()?);
        let mut child = Command::new(&spec.program)
            .args(&spec.args)
            .current_dir(&spec.cwd)
            .env_clear()
            .envs(spec.env.iter().map(|(k, v)| (k, v)))
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .creation_flags(CREATE_SUSPENDED | CREATE_NO_WINDOW | CREATE_UNICODE_ENVIRONMENT)
            .spawn()?;
        let bound = job
            .assign_child(&child)
            .and_then(|_| job::resume_process(child.id()).map(|_| ()));
        if let Err(e) = bound {
            let _ = child.kill();
            let _ = child.wait();
            return Err(e);
        }

        let stdin = child.stdin.take();
        let stdout = child.stdout.take().expect("stdout piped");
        let stderr = child.stderr.take().expect("stderr piped");
        let (tx, rx) = mpsc::channel();

        let out_sink = stdout_sink.clone();
        let out_nonce = nonce.to_string();
        let out_job = job.clone();
        let stdout_reader =
            thread::Builder::new()
                .name("sidecar-stdout".into())
                .spawn(move || {
                    let mut reader = BufReader::new(stdout);
                    let mut line = Vec::new();
                    while let Ok(Some(truncated)) =
                        logs::read_capped_line(&mut reader, logs::LINE_CAP, &mut line)
                    {
                        if let Ok(mut sink) = out_sink.lock() {
                            sink.write_line(&line);
                            if truncated {
                                sink.write_line("[外壳] 上一行过长，已截断".as_bytes());
                            }
                        }
                        let msg = match std::str::from_utf8(&line) {
                            Err(_) => Message::Ignored("不是 UTF-8".into()),
                            Ok(text) => match protocol::parse_line(text, &out_nonce) {
                                Parsed::Event(event) => match event.pid {
                                    Some(pid) if !out_job.contains(pid) => {
                                        Message::Ignored(format!("pid {pid} 不属于本次启动"))
                                    }
                                    _ => Message::Event(event),
                                },
                                Parsed::Fatal(reason) => Message::Fatal(reason),
                                Parsed::Ignored(reason) => Message::Ignored(reason),
                            },
                        };
                        if tx.send(msg).is_err() {
                            break;
                        }
                    }
                    if let Ok(mut sink) = out_sink.lock() {
                        sink.flush();
                    }
                    let _ = tx.send(Message::StdoutClosed);
                })?;

        let err_sink = stderr_sink.clone();
        let stderr_reader =
            thread::Builder::new()
                .name("sidecar-stderr".into())
                .spawn(move || {
                    let mut reader = BufReader::new(stderr);
                    let mut line = Vec::new();
                    while let Ok(Some(truncated)) =
                        logs::read_capped_line(&mut reader, logs::LINE_CAP, &mut line)
                    {
                        if let Ok(mut sink) = err_sink.lock() {
                            sink.write_line(&line);
                            if truncated {
                                sink.write_line("[外壳] 上一行过长，已截断".as_bytes());
                            }
                        }
                    }
                    if let Ok(mut sink) = err_sink.lock() {
                        sink.flush();
                    }
                })?;

        Ok(Self {
            child,
            job,
            stdin,
            nonce: nonce.to_string(),
            rx,
            readers: vec![stdout_reader, stderr_reader],
            stdout_sink,
            stderr_sink,
        })
    }

    pub fn pid(&self) -> u32 {
        self.child.id()
    }

    pub fn nonce(&self) -> &str {
        &self.nonce
    }

    /// 某个 pid 是否属于本次启动的进程树。
    pub fn owns_pid(&self, pid: u32) -> bool {
        pid == self.child.id() || self.job.contains(pid)
    }

    pub fn stdout_sink(&self) -> &SharedSink {
        &self.stdout_sink
    }

    pub fn stderr_sink(&self) -> &SharedSink {
        &self.stderr_sink
    }

    /// 等下一条协议消息，超时返回 `None`。
    pub fn recv_timeout(&self, timeout: Duration) -> Option<Message> {
        match self.rx.recv_timeout(timeout) {
            Ok(msg) => Some(msg),
            Err(RecvTimeoutError::Timeout) => None,
            Err(RecvTimeoutError::Disconnected) => Some(Message::StdoutClosed),
        }
    }

    pub fn try_wait(&mut self) -> io::Result<Option<ExitStatus>> {
        self.child.try_wait()
    }

    /// 发送 shutdown 命令并关闭 stdin（EOF 同样表示关闭）。可重复调用。
    pub fn request_shutdown(&mut self) {
        if let Some(mut stdin) = self.stdin.take() {
            let _ = stdin.write_all(protocol::shutdown_line(&self.nonce).as_bytes());
            let _ = stdin.flush();
            drop(stdin);
        }
    }

    pub fn wait_timeout(&mut self, timeout: Duration) -> io::Result<Option<ExitStatus>> {
        let deadline = Instant::now() + timeout;
        loop {
            if let Some(status) = self.child.try_wait()? {
                return Ok(Some(status));
            }
            if Instant::now() >= deadline {
                return Ok(None);
            }
            thread::sleep(Duration::from_millis(25));
        }
    }

    /// 立即结束整个进程树。
    pub fn kill_tree(&mut self) {
        let _ = self.job.terminate(1);
        let _ = self.child.wait();
    }

    /// 优雅关闭：shutdown → 最多等 `grace` → 超时结束整个 Job。之后收拢读线程。
    pub fn shutdown(&mut self, grace: Duration) -> Outcome {
        self.request_shutdown();
        let outcome = match self.wait_timeout(grace) {
            Ok(Some(status)) => Outcome::Exited(status),
            _ => {
                let _ = self.job.terminate(1);
                Outcome::Killed(self.child.wait().ok())
            }
        };
        self.finish();
        outcome
    }

    /// 子进程已退出后调用：给孙进程一点时间放手管道，仍未结束的由 Job 结束，然后 join 读线程。
    pub fn finish(&mut self) {
        let deadline = Instant::now() + Duration::from_secs(2);
        while self.job.active_processes().unwrap_or(0) > 0 && Instant::now() < deadline {
            thread::sleep(Duration::from_millis(25));
        }
        if self.job.active_processes().unwrap_or(0) > 0 {
            let _ = self.job.terminate(1);
        }
        for reader in self.readers.drain(..) {
            let _ = reader.join();
        }
    }

    /// 读线程结束前已经排队的剩余消息。
    pub fn drain(&self) -> Vec<Message> {
        self.rx.try_iter().collect()
    }
}

impl Drop for Sidecar {
    fn drop(&mut self) {
        #[cfg(windows)]
        {
            if matches!(self.child.try_wait(), Ok(None)) {
                let _ = self.job.terminate(1);
                let _ = self.child.wait();
            }
        }
    }
}
