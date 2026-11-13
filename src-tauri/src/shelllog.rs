//! 外壳自身日志：`<定位目录>\shell-logs\shell.log`，1 MiB × 保留 2。只记状态转换与核对原因，
//! 不记学生材料。

use desktop_core::logs::RotatingFile;
use desktop_core::timefmt;
use std::path::Path;
use std::sync::{Mutex, OnceLock};

static LOG: OnceLock<Mutex<Option<RotatingFile>>> = OnceLock::new();

pub fn init(dir: &Path) {
    let file = RotatingFile::open(&dir.join("shell.log"), 1024 * 1024, 2).ok();
    let _ = LOG.set(Mutex::new(file));
}

pub fn log(message: impl AsRef<str>) {
    let line = format!("{} {}", timefmt::utc_now_iso(), message.as_ref());
    #[cfg(debug_assertions)]
    eprintln!("[shell] {line}");
    if let Some(lock) = LOG.get() {
        if let Ok(mut guard) = lock.lock() {
            if let Some(file) = guard.as_mut() {
                let _ = file.write_line(line.as_bytes());
                let _ = file.flush();
            }
        }
    }
}
