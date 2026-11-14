//! 用户选择的 codex.exe：路径校验 + 固定参数 `--version` 探测（限时、无窗口、放进临时 Job）。
//! 首版只接受原生 .exe；.cmd/.bat 在路径含 %变量% 时会被批处理展开，不能可靠启动。

use std::ffi::OsString;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};

#[derive(Debug, Clone, PartialEq)]
pub struct Probe {
    pub ok: bool,
    pub version: Option<String>,
    pub message: Option<String>,
}

/// 官方原生安装的默认目录（存在时作为对话框的初始目录）。
pub fn default_dir(local_app_data: &Path) -> PathBuf {
    local_app_data
        .join("Programs")
        .join("OpenAI")
        .join("Codex")
        .join("bin")
}

pub fn validate_path(path: &Path) -> Result<(), String> {
    if !path.is_absolute() {
        return Err("请选择一个完整的文件位置。".into());
    }
    let ext = path
        .extension()
        .map(|e| e.to_string_lossy().to_ascii_lowercase())
        .unwrap_or_default();
    if ext == "cmd" || ext == "bat" {
        return Err(
            "这是批处理安装方式，做题龙不能可靠启动它。请选择官方安装的 codex.exe。".into(),
        );
    }
    if ext != "exe" {
        return Err("请选择官方安装的 codex.exe。".into());
    }
    match std::fs::metadata(path) {
        Ok(meta) if meta.is_file() => Ok(()),
        Ok(_) => Err("这里不是文件，请重新选择。".into()),
        Err(_) => Err("找不到这个文件，请重新选择。".into()),
    }
}

/// 运行 `<exe> --version`，最多等 `timeout`。
#[cfg(windows)]
pub fn probe(path: &Path, env: &[(OsString, OsString)], cwd: &Path, timeout: Duration) -> Probe {
    use crate::job::{self, Job};
    use std::os::windows::process::CommandExt;
    use windows_sys::Win32::System::Threading::{
        CREATE_NO_WINDOW, CREATE_SUSPENDED, CREATE_UNICODE_ENVIRONMENT,
    };

    let fail = |message: &str| Probe {
        ok: false,
        version: None,
        message: Some(message.into()),
    };
    if let Err(message) = validate_path(path) {
        return fail(&message);
    }
    let job = match Job::new_kill_on_close() {
        Ok(job) => job,
        Err(_) => return fail("已找到，但不能启动。"),
    };
    let child = Command::new(path)
        .arg("--version")
        .current_dir(cwd)
        .env_clear()
        .envs(env.iter().map(|(k, v)| (k, v)))
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .creation_flags(CREATE_SUSPENDED | CREATE_NO_WINDOW | CREATE_UNICODE_ENVIRONMENT)
        .spawn();
    let mut child = match child {
        Ok(child) => child,
        Err(_) => return fail("已找到，但不能启动。请确认选择的是官方安装的 codex.exe。"),
    };
    if job.assign_child(&child).is_err() || job::resume_process(child.id()).is_err() {
        let _ = child.kill();
        let _ = child.wait();
        return fail("已找到，但不能启动。");
    }
    let mut stdout = child.stdout.take().expect("stdout piped");
    let reader = thread::spawn(move || {
        let mut buf = Vec::new();
        let _ = stdout.by_ref().take(64 * 1024).read_to_end(&mut buf);
        buf
    });
    let deadline = Instant::now() + timeout;
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break Some(status),
            Ok(None) if Instant::now() < deadline => thread::sleep(Duration::from_millis(25)),
            _ => break None,
        }
    };
    let Some(status) = status else {
        let _ = job.terminate(1);
        let _ = child.wait();
        let _ = reader.join();
        return fail("已找到，但它没有响应。");
    };
    let out = reader.join().unwrap_or_default();
    let first = String::from_utf8_lossy(&out)
        .lines()
        .map(str::trim)
        .find(|l| !l.is_empty())
        .map(|l| l.chars().take(120).collect::<String>());
    match (status.success(), first) {
        (true, Some(version)) => Probe {
            ok: true,
            version: Some(version),
            message: None,
        },
        _ => fail("已找到，但不能启动。请确认选择的是官方安装的 codex.exe。"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_batch_and_non_exe() {
        let dir = tempfile::tempdir().unwrap();
        let cmd = dir.path().join("codex.cmd");
        std::fs::write(&cmd, "@echo off").unwrap();
        assert!(validate_path(&cmd).unwrap_err().contains("批处理"));
        let txt = dir.path().join("codex.txt");
        std::fs::write(&txt, "x").unwrap();
        assert!(validate_path(&txt).is_err());
        assert!(validate_path(&dir.path().join("missing.exe")).is_err());
        assert!(validate_path(Path::new("codex.exe")).is_err());
    }

    #[cfg(windows)]
    #[test]
    fn probes_a_real_executable_with_fixed_arguments() {
        // where.exe 不认识 --version，以非零退出：应报告“不能启动”而不是挂起
        let system = std::env::var_os("SystemRoot").map(PathBuf::from).unwrap();
        let exe = system.join("System32").join("where.exe");
        let env: Vec<(OsString, OsString)> = std::env::vars_os().collect();
        let probe = probe(&exe, &env, &std::env::temp_dir(), Duration::from_secs(10));
        assert!(!probe.ok);
        assert!(probe.message.is_some());
    }
}
