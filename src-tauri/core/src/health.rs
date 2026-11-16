//! 健康核对：address_published 事件、工作区 server.json 与 /api/health 三处一致，
//! 且属于本次启动（pid 在本次 Job 内、nonce 相同）、版本与外壳一致、地址是 127.0.0.1。
//!
//! 附一个只连 127.0.0.1 的最小 HTTP/1.1 客户端（无 TLS、无重定向）。

use crate::protocol::ServerInfo;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::fs;
use std::io::{self, Read, Write};
use std::net::{Ipv4Addr, SocketAddr, TcpStream};
use std::path::Path;
use std::time::Duration;

pub const SERVER_JSON: &str = "server.json";
const BODY_CAP: usize = 4 * 1024 * 1024;

#[derive(Debug, Clone, PartialEq)]
pub struct Verified {
    pub port: u16,
    pub origin: String,
    pub pid: u32,
    pub data_id: String,
}

#[derive(Debug, Clone, PartialEq)]
pub enum VerifyError {
    BadUrl(String),
    PidMismatch,
    NonceMismatch,
    VersionMismatch { got: String, want: String },
    DataIdMismatch,
    HealthNotOk,
}

impl std::fmt::Display for VerifyError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            VerifyError::BadUrl(u) => write!(f, "地址不是本机 127.0.0.1：{u}"),
            VerifyError::PidMismatch => write!(f, "进程号与本次启动不符"),
            VerifyError::NonceMismatch => write!(f, "启动标识与本次启动不符"),
            VerifyError::VersionMismatch { got, want } => {
                write!(f, "后台版本 {got} 与外壳版本 {want} 不一致")
            }
            VerifyError::DataIdMismatch => write!(f, "数据标识不一致"),
            VerifyError::HealthNotOk => write!(f, "健康检查未通过"),
        }
    }
}

/// 只接受 `http://127.0.0.1:<port>/`（末尾斜杠可省），返回端口。
pub fn loopback_port(url: &str) -> Result<u16, VerifyError> {
    let bad = || VerifyError::BadUrl(url.to_string());
    let rest = url.strip_prefix("http://127.0.0.1:").ok_or_else(bad)?;
    let port_text = rest.strip_suffix('/').unwrap_or(rest);
    if port_text.is_empty() || !port_text.bytes().all(|b| b.is_ascii_digit()) {
        return Err(bad());
    }
    match port_text.parse::<u16>() {
        Ok(0) | Err(_) => Err(bad()),
        Ok(port) => Ok(port),
    }
}

/// 读工作区 server.json（不存在或格式不对返回 None）。
pub fn read_server_json(workspace: &Path) -> Option<ServerInfo> {
    let text = fs::read_to_string(workspace.join(SERVER_JSON)).ok()?;
    serde_json::from_str(&text).ok()
}

/// 核对三处信息。`owns_pid` 判断 pid 是否属于本次启动；`file` 为 None 时只核对事件与 health。
pub fn verify(
    event: &ServerInfo,
    file: Option<&ServerInfo>,
    health: &Value,
    owns_pid: impl Fn(u32) -> bool,
    nonce: &str,
    version: &str,
) -> Result<Verified, VerifyError> {
    let port = loopback_port(&event.url)?;
    if !owns_pid(event.pid) {
        return Err(VerifyError::PidMismatch);
    }
    if event.nonce.as_deref() != Some(nonce) {
        return Err(VerifyError::NonceMismatch);
    }
    if event.version != version {
        return Err(VerifyError::VersionMismatch {
            got: event.version.clone(),
            want: version.to_string(),
        });
    }
    if let Some(file) = file {
        if loopback_port(&file.url)? != port {
            return Err(VerifyError::BadUrl(file.url.clone()));
        }
        if file.pid != event.pid {
            return Err(VerifyError::PidMismatch);
        }
        if file.nonce.as_deref() != Some(nonce) {
            return Err(VerifyError::NonceMismatch);
        }
        if file.data_id != event.data_id {
            return Err(VerifyError::DataIdMismatch);
        }
    }
    if health.get("ok").and_then(Value::as_bool) != Some(true) {
        return Err(VerifyError::HealthNotOk);
    }
    if health.get("pid").and_then(Value::as_u64) != Some(event.pid as u64) {
        return Err(VerifyError::PidMismatch);
    }
    if health.get("nonce").and_then(Value::as_str) != Some(nonce) {
        return Err(VerifyError::NonceMismatch);
    }
    let health_version = health.get("version").and_then(Value::as_str).unwrap_or("");
    if health_version != version {
        return Err(VerifyError::VersionMismatch {
            got: health_version.to_string(),
            want: version.to_string(),
        });
    }
    if health.get("data_id").and_then(Value::as_str) != Some(event.data_id.as_str()) {
        return Err(VerifyError::DataIdMismatch);
    }
    Ok(Verified {
        port,
        origin: format!("http://127.0.0.1:{port}"),
        pid: event.pid,
        data_id: event.data_id.clone(),
    })
}

/// 与后端 `data_identity` 同义的估算（sha256(小写绝对路径)）。Rust 与 Python 的规范化在少数
/// 字符上可能不同，只用于日志对照，不作为拒绝依据。
pub fn estimated_data_id(workspace: &Path) -> String {
    let text = workspace.to_string_lossy().to_lowercase();
    let digest = Sha256::digest(text.as_bytes());
    crate::nonce::hex(&digest)
}

/// GET http://127.0.0.1:port{path}，返回 (状态码, 正文)。
pub fn http_get(port: u16, path: &str, timeout: Duration) -> io::Result<(u16, String)> {
    let addr = SocketAddr::from((Ipv4Addr::LOCALHOST, port));
    let mut stream = TcpStream::connect_timeout(&addr, timeout)?;
    stream.set_read_timeout(Some(timeout))?;
    stream.set_write_timeout(Some(timeout))?;
    write!(
        stream,
        "GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nAccept: application/json\r\nConnection: close\r\n\r\n"
    )?;
    let mut raw = Vec::new();
    let limit = BODY_CAP + 64 * 1024;
    let mut chunk = [0u8; 16 * 1024];
    loop {
        match stream.read(&mut chunk) {
            Ok(0) => break,
            Ok(n) => {
                raw.extend_from_slice(&chunk[..n]);
                if raw.len() > limit {
                    return Err(io::Error::new(io::ErrorKind::InvalidData, "响应过大"));
                }
            }
            Err(e) if e.kind() == io::ErrorKind::Interrupted => continue,
            // 对方回完响应后直接复位连接：已收到完整响应就照常使用
            Err(e) if e.kind() == io::ErrorKind::ConnectionReset && complete(&raw) => break,
            Err(e) => return Err(e),
        }
    }
    parse_response(&raw)
}

/// 是否已收到完整响应（按 Content-Length 判断；分块编码看结尾块）。
fn complete(raw: &[u8]) -> bool {
    let Some(split) = raw.windows(4).position(|w| w == b"\r\n\r\n") else {
        return false;
    };
    let head = String::from_utf8_lossy(&raw[..split]).to_ascii_lowercase();
    let body = raw.len() - split - 4;
    if let Some(len) = head
        .lines()
        .find_map(|l| l.strip_prefix("content-length:"))
        .and_then(|v| v.trim().parse::<usize>().ok())
    {
        return body >= len;
    }
    head.contains("chunked") && raw.ends_with(b"0\r\n\r\n")
}

fn parse_response(raw: &[u8]) -> io::Result<(u16, String)> {
    let bad = |m: &str| io::Error::new(io::ErrorKind::InvalidData, m.to_string());
    let split = raw
        .windows(4)
        .position(|w| w == b"\r\n\r\n")
        .ok_or_else(|| bad("响应不完整"))?;
    let head = std::str::from_utf8(&raw[..split]).map_err(|_| bad("响应头不是 UTF-8"))?;
    let mut lines = head.split("\r\n");
    let status: u16 = lines
        .next()
        .and_then(|l| l.split_whitespace().nth(1))
        .and_then(|s| s.parse().ok())
        .ok_or_else(|| bad("状态行不合法"))?;
    let chunked = lines.any(|l| {
        let l = l.to_ascii_lowercase();
        l.starts_with("transfer-encoding:") && l.contains("chunked")
    });
    let body = &raw[split + 4..];
    let body = if chunked {
        dechunk(body)?
    } else {
        body.to_vec()
    };
    Ok((status, String::from_utf8_lossy(&body).into_owned()))
}

fn dechunk(mut data: &[u8]) -> io::Result<Vec<u8>> {
    let bad = || io::Error::new(io::ErrorKind::InvalidData, "分块编码不合法");
    let mut out = Vec::new();
    loop {
        let line_end = data.windows(2).position(|w| w == b"\r\n").ok_or_else(bad)?;
        let size_text = std::str::from_utf8(&data[..line_end]).map_err(|_| bad())?;
        let size_text = size_text.split(';').next().unwrap_or("").trim();
        let size = usize::from_str_radix(size_text, 16).map_err(|_| bad())?;
        data = &data[line_end + 2..];
        if size == 0 {
            return Ok(out);
        }
        if data.len() < size + 2 {
            return Err(bad());
        }
        out.extend_from_slice(&data[..size]);
        data = &data[size + 2..];
    }
}

/// GET /api/health 并解析 JSON；非 200 或解析失败返回错误文本。
pub fn fetch_health(port: u16, timeout: Duration) -> Result<Value, String> {
    let (status, body) = http_get(port, "/api/health", timeout).map_err(|e| e.to_string())?;
    if status != 200 {
        return Err(format!("HTTP {status}"));
    }
    serde_json::from_str(&body).map_err(|e| e.to_string())
}

/// 是否有正在运行的任务（`GET /api/tasks` 的 `active` 非空）。
pub fn tasks_active(port: u16, timeout: Duration) -> Result<bool, String> {
    let (status, body) = http_get(port, "/api/tasks", timeout).map_err(|e| e.to_string())?;
    if status != 200 {
        return Err(format!("HTTP {status}"));
    }
    let value: Value = serde_json::from_str(&body).map_err(|e| e.to_string())?;
    Ok(!value.get("active").map(Value::is_null).unwrap_or(true))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    const N: &str = "4ddc73b05326e40fb418d87d029c34752bdb08d7c37a2299ef44252f567ead6d";

    fn server(pid: u32, nonce: &str) -> ServerInfo {
        ServerInfo {
            url: "http://127.0.0.1:9318/".into(),
            pid,
            version: "0.10.0".into(),
            data_id: "401fad31".into(),
            nonce: Some(nonce.into()),
        }
    }

    fn health(pid: u32, nonce: &str, version: &str) -> Value {
        json!({"ok": true, "app": "mathlens", "version": version, "data_id": "401fad31", "pid": pid, "nonce": nonce})
    }

    #[test]
    fn accepts_matching_sources() {
        let s = server(65844, N);
        let v = verify(
            &s,
            Some(&s),
            &health(65844, N, "0.10.0"),
            |p| p == 65844,
            N,
            "0.10.0",
        )
        .unwrap();
        assert_eq!(v.port, 9318);
        assert_eq!(v.origin, "http://127.0.0.1:9318");
    }

    #[test]
    fn rejects_every_mismatch() {
        let s = server(65844, N);
        let owns = |p| p == 65844;
        let h = health(65844, N, "0.10.0");
        assert_eq!(
            verify(&s, None, &h, |_| false, N, "0.10.0"),
            Err(VerifyError::PidMismatch)
        );
        let stale = server(111, &"0".repeat(64));
        assert_eq!(
            verify(&s, Some(&stale), &h, owns, N, "0.10.0"),
            Err(VerifyError::PidMismatch)
        );
        assert_eq!(
            verify(
                &s,
                None,
                &health(65844, &"1".repeat(64), "0.10.0"),
                owns,
                N,
                "0.10.0"
            ),
            Err(VerifyError::NonceMismatch)
        );
        assert!(matches!(
            verify(&s, None, &h, owns, N, "0.11.0"),
            Err(VerifyError::VersionMismatch { .. })
        ));
        let mut lan = server(65844, N);
        lan.url = "http://0.0.0.0:9318/".into();
        assert!(matches!(
            verify(&lan, None, &h, owns, N, "0.10.0"),
            Err(VerifyError::BadUrl(_))
        ));
        let not_ok = json!({"ok": false, "pid": 65844, "nonce": N, "version": "0.10.0", "data_id": "401fad31"});
        assert_eq!(
            verify(&s, None, &not_ok, owns, N, "0.10.0"),
            Err(VerifyError::HealthNotOk)
        );
    }

    #[test]
    fn loopback_url_rules() {
        assert_eq!(loopback_port("http://127.0.0.1:9318/"), Ok(9318));
        assert_eq!(loopback_port("http://127.0.0.1:9318"), Ok(9318));
        for bad in [
            "https://127.0.0.1:9318/",
            "http://localhost:9318/",
            "http://127.0.0.1:0/",
            "http://127.0.0.1:99999/",
            "http://127.0.0.1:93a/",
            "http://127.0.0.1:9318/x",
        ] {
            assert!(loopback_port(bad).is_err(), "{bad}");
        }
    }

    #[test]
    fn parses_plain_and_chunked_responses() {
        let plain = b"HTTP/1.1 200 OK\r\ncontent-length: 11\r\n\r\n{\"ok\":true}";
        assert_eq!(
            parse_response(plain).unwrap(),
            (200, "{\"ok\":true}".into())
        );
        let chunked =
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n4\r\n{\"ok\r\n7\r\n\":true}\r\n0\r\n\r\n";
        assert_eq!(
            parse_response(chunked).unwrap(),
            (200, "{\"ok\":true}".into())
        );
    }
}
