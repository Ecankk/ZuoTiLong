//! 日志：有界轮转文件与 prepare 阶段的内存缓冲。
//!
//! server.stdout.log / server.stderr.log 单文件 5 MiB，保留 `.1`、`.2` 两个历史文件。
//! prepare 期间工作区可能还没发布，先写内存环形缓冲，成功后再落到工作区。

use std::collections::VecDeque;
use std::fs::{self, File, OpenOptions};
use std::io::{self, BufRead, Write};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

pub const SERVER_LOG_MAX: u64 = 5 * 1024 * 1024;
pub const SERVER_LOG_KEEP: usize = 2;
pub const RING_CAP: usize = 2 * 1024 * 1024;
/// 单行上限，超出截断并标注。
pub const LINE_CAP: usize = 64 * 1024;
pub const STDOUT_LOG: &str = "server.stdout.log";
pub const STDERR_LOG: &str = "server.stderr.log";

pub struct RotatingFile {
    path: PathBuf,
    max: u64,
    keep: usize,
    file: Option<File>,
    size: u64,
}

impl RotatingFile {
    pub fn open(path: &Path, max: u64, keep: usize) -> io::Result<Self> {
        if let Some(dir) = path.parent() {
            fs::create_dir_all(dir)?;
        }
        let file = OpenOptions::new().create(true).append(true).open(path)?;
        let size = file.metadata()?.len();
        Ok(Self {
            path: path.to_path_buf(),
            max,
            keep,
            file: Some(file),
            size,
        })
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    /// 写一行（自动补换行）。写入前若会超出上限且当前文件非空，则先轮转。
    pub fn write_line(&mut self, line: &[u8]) -> io::Result<()> {
        let len = line.len() as u64 + 1;
        if self.size > 0 && self.size + len > self.max {
            self.rotate()?;
        }
        let file = match self.file.as_mut() {
            Some(f) => f,
            None => {
                self.file = Some(
                    OpenOptions::new()
                        .create(true)
                        .append(true)
                        .open(&self.path)?,
                );
                self.file.as_mut().unwrap()
            }
        };
        file.write_all(line)?;
        file.write_all(b"\n")?;
        self.size += len;
        Ok(())
    }

    pub fn flush(&mut self) -> io::Result<()> {
        match self.file.as_mut() {
            Some(f) => f.flush(),
            None => Ok(()),
        }
    }

    fn rotate(&mut self) -> io::Result<()> {
        self.file = None; // 先关句柄，Windows 才能改名
        if self.keep == 0 {
            let _ = fs::remove_file(&self.path);
        } else {
            let _ = fs::remove_file(numbered(&self.path, self.keep));
            for n in (1..self.keep).rev() {
                let from = numbered(&self.path, n);
                if from.exists() {
                    fs::rename(&from, numbered(&self.path, n + 1))?;
                }
            }
            fs::rename(&self.path, numbered(&self.path, 1))?;
        }
        self.file = Some(
            OpenOptions::new()
                .create(true)
                .append(true)
                .open(&self.path)?,
        );
        self.size = 0;
        Ok(())
    }
}

/// `server.stdout.log` → `server.stdout.log.1`
pub fn numbered(path: &Path, n: usize) -> PathBuf {
    let mut name = path.as_os_str().to_owned();
    name.push(format!(".{n}"));
    PathBuf::from(name)
}

/// 按字节计的环形缓冲，按行保存，超出容量丢掉最早的行。
#[derive(Default)]
pub struct Ring {
    cap: usize,
    lines: VecDeque<Vec<u8>>,
    bytes: usize,
    pub dropped_lines: u64,
}

impl Ring {
    pub fn new(cap: usize) -> Self {
        Self {
            cap,
            ..Default::default()
        }
    }

    pub fn push_line(&mut self, line: &[u8]) {
        self.lines.push_back(line.to_vec());
        self.bytes += line.len();
        while self.bytes > self.cap {
            match self.lines.pop_front() {
                Some(old) => {
                    self.bytes -= old.len();
                    self.dropped_lines += 1;
                }
                None => break,
            }
        }
    }

    pub fn lines(&self) -> impl Iterator<Item = &[u8]> {
        self.lines.iter().map(|l| l.as_slice())
    }

    pub fn is_empty(&self) -> bool {
        self.lines.is_empty()
    }
}

pub enum Sink {
    Buffer(Ring),
    File(RotatingFile),
    Null,
}

impl Sink {
    pub fn write_line(&mut self, line: &[u8]) {
        match self {
            Sink::Buffer(ring) => ring.push_line(line),
            Sink::File(file) => {
                let _ = file.write_line(line);
            }
            Sink::Null => {}
        }
    }

    pub fn flush(&mut self) {
        if let Sink::File(f) = self {
            let _ = f.flush();
        }
    }
}

pub type SharedSink = Arc<Mutex<Sink>>;

pub fn shared(sink: Sink) -> SharedSink {
    Arc::new(Mutex::new(sink))
}

/// 把缓冲内容写入文件（prepare 成功后落到工作区；失败时写外壳日志目录）。
pub fn drain_ring_to(ring: &Ring, file: &mut RotatingFile) -> io::Result<()> {
    if ring.dropped_lines > 0 {
        file.write_line(
            format!("[外壳] 缓冲已满，较早的 {} 行未保留", ring.dropped_lines).as_bytes(),
        )?;
    }
    for line in ring.lines() {
        file.write_line(line)?;
    }
    file.flush()
}

/// 读一行，最多保留 `cap` 字节，超出部分丢弃。返回 `Ok(None)` 表示 EOF。
/// 返回值中的 bool 表示是否被截断。行尾的 `\r\n` / `\n` 不包含在结果里。
pub fn read_capped_line<R: BufRead>(
    reader: &mut R,
    cap: usize,
    out: &mut Vec<u8>,
) -> io::Result<Option<bool>> {
    out.clear();
    let mut truncated = false;
    let mut saw_any = false;
    loop {
        let available = match reader.fill_buf() {
            Ok(buf) => buf,
            Err(e) if e.kind() == io::ErrorKind::Interrupted => continue,
            Err(e) => return Err(e),
        };
        if available.is_empty() {
            return Ok(if saw_any { Some(truncated) } else { None });
        }
        saw_any = true;
        let (chunk, found, used) = match available.iter().position(|&b| b == b'\n') {
            Some(i) => (&available[..i], true, i + 1),
            None => (available, false, available.len()),
        };
        let room = cap.saturating_sub(out.len());
        if chunk.len() > room {
            out.extend_from_slice(&chunk[..room]);
            truncated = true;
        } else {
            out.extend_from_slice(chunk);
        }
        reader.consume(used);
        if found {
            if out.last() == Some(&b'\r') {
                out.pop();
            }
            return Ok(Some(truncated));
        }
    }
}

/// 只保留目录下最近 `keep` 个以 `prefix` 开头的文件（按文件名排序，名字含时间戳）。
pub fn prune_files(dir: &Path, prefix: &str, keep: usize) -> io::Result<()> {
    let mut names: Vec<PathBuf> = fs::read_dir(dir)?
        .filter_map(|e| e.ok())
        .map(|e| e.path())
        .filter(|p| {
            p.file_name()
                .map(|n| n.to_string_lossy().starts_with(prefix))
                .unwrap_or(false)
        })
        .collect();
    names.sort();
    let excess = names.len().saturating_sub(keep);
    for old in names.into_iter().take(excess) {
        let _ = fs::remove_file(old);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    #[test]
    fn rotates_at_limit_and_keeps_two_histories() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("server.stderr.log");
        let mut log = RotatingFile::open(&path, 100, 2).unwrap();
        for i in 0..40 {
            log.write_line(format!("line {i:03} ........").as_bytes())
                .unwrap();
        }
        log.flush().unwrap();
        assert!(path.exists());
        assert!(numbered(&path, 1).exists());
        assert!(numbered(&path, 2).exists());
        assert!(!numbered(&path, 3).exists());
        for p in [path.clone(), numbered(&path, 1), numbered(&path, 2)] {
            assert!(fs::metadata(&p).unwrap().len() <= 100, "{p:?}");
        }
        let newest = fs::read_to_string(&path).unwrap();
        assert!(newest.contains("line 039"));
    }

    #[test]
    fn ring_drops_oldest_lines() {
        let mut ring = Ring::new(10);
        ring.push_line(b"aaaa");
        ring.push_line(b"bbbb");
        ring.push_line(b"cccc");
        let kept: Vec<&[u8]> = ring.lines().collect();
        assert_eq!(kept, vec![b"bbbb".as_slice(), b"cccc".as_slice()]);
        assert_eq!(ring.dropped_lines, 1);
    }

    #[test]
    fn capped_reader_truncates_long_lines_and_strips_crlf() {
        let data = format!("short\r\n{}\nlast", "x".repeat(50));
        let mut reader = Cursor::new(data.into_bytes());
        let mut out = Vec::new();
        assert_eq!(
            read_capped_line(&mut reader, 10, &mut out).unwrap(),
            Some(false)
        );
        assert_eq!(out, b"short");
        assert_eq!(
            read_capped_line(&mut reader, 10, &mut out).unwrap(),
            Some(true)
        );
        assert_eq!(out, b"xxxxxxxxxx");
        assert_eq!(
            read_capped_line(&mut reader, 10, &mut out).unwrap(),
            Some(false)
        );
        assert_eq!(out, b"last");
        assert_eq!(read_capped_line(&mut reader, 10, &mut out).unwrap(), None);
    }

    #[test]
    fn prune_keeps_newest() {
        let dir = tempfile::tempdir().unwrap();
        for n in 1..=7 {
            fs::write(
                dir.path().join(format!("prepare-failed-2026111{n}.log")),
                "x",
            )
            .unwrap();
        }
        fs::write(dir.path().join("shell.log"), "x").unwrap();
        prune_files(dir.path(), "prepare-failed-", 5).unwrap();
        let left: Vec<String> = fs::read_dir(dir.path())
            .unwrap()
            .map(|e| e.unwrap().file_name().to_string_lossy().into_owned())
            .collect();
        assert_eq!(left.len(), 6);
        assert!(!left.contains(&"prepare-failed-20261111.log".to_string()));
        assert!(left.contains(&"shell.log".to_string()));
    }
}
