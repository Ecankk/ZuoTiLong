//! sidecar stdout 协议 `mathlens.desktop/v1`（见 DESKTOP-SIDECAR.md 2.3/3/4）。
//!
//! 每行一个 UTF-8 JSON。外壳忽略未知可选字段；协议主版本不认识则停止本次进程。

use serde::{Deserialize, Serialize};

pub const PROTOCOL: &str = "mathlens.desktop/v1";
const FAMILY: &str = "mathlens.desktop/";

#[derive(Deserialize, Serialize, Clone, Debug, PartialEq)]
pub struct Progress {
    pub unit: String,
    pub completed: u64,
    #[serde(default)]
    pub total: Option<u64>,
}

#[derive(Deserialize, Serialize, Clone, Debug, PartialEq)]
pub struct ErrorInfo {
    pub code: String,
    #[serde(default)]
    pub message: String,
    #[serde(default)]
    pub retryable: bool,
}

#[derive(Deserialize, Serialize, Clone, Debug, PartialEq)]
pub struct ServerInfo {
    pub url: String,
    pub pid: u32,
    pub version: String,
    pub data_id: String,
    #[serde(default)]
    pub nonce: Option<String>,
}

#[derive(Deserialize, Clone, Debug, PartialEq)]
pub struct Event {
    pub protocol: String,
    pub event: String,
    #[serde(default)]
    pub operation: Option<String>,
    #[serde(default)]
    pub seq: Option<u64>,
    #[serde(default)]
    pub nonce: Option<String>,
    #[serde(default)]
    pub pid: Option<u32>,
    #[serde(default)]
    pub phase: Option<String>,
    #[serde(default)]
    pub status: Option<String>,
    #[serde(default)]
    pub message: Option<String>,
    #[serde(default)]
    pub progress: Option<Progress>,
    #[serde(default)]
    pub error: Option<ErrorInfo>,
    #[serde(default)]
    pub server: Option<ServerInfo>,
    #[serde(default)]
    pub reused_library: Option<bool>,
    #[serde(default)]
    pub library_published: Option<bool>,
    #[serde(default)]
    pub workspace_ready: Option<bool>,
}

#[derive(Debug, PartialEq)]
pub enum Parsed {
    Event(Box<Event>),
    /// 不是本协议或不属于本次启动的行：记日志后忽略。
    Ignored(String),
    /// 协议主版本不认识：停止本次进程。
    Fatal(String),
}

/// 解析一行。`nonce` 不符的行一律忽略；仅 `error` 事件允许 nonce 为空（参数解析失败时）。
pub fn parse_line(line: &str, nonce: &str) -> Parsed {
    let trimmed = line.trim();
    if trimmed.is_empty() {
        return Parsed::Ignored("空行".into());
    }
    let value: serde_json::Value = match serde_json::from_str(trimmed) {
        Ok(v) => v,
        Err(e) => return Parsed::Ignored(format!("不是 JSON：{e}")),
    };
    let protocol = value.get("protocol").and_then(|p| p.as_str()).unwrap_or("");
    if protocol != PROTOCOL {
        return if protocol.starts_with(FAMILY) {
            Parsed::Fatal(format!("不支持的协议版本 {protocol}"))
        } else {
            Parsed::Ignored("不是桌面协议行".into())
        };
    }
    let event: Event = match serde_json::from_value(value) {
        Ok(e) => e,
        Err(e) => return Parsed::Ignored(format!("字段不合法：{e}")),
    };
    match event.nonce.as_deref() {
        Some(n) if n == nonce => {}
        None if event.event == "error" => {}
        Some(_) => return Parsed::Ignored("nonce 不属于本次启动".into()),
        None => return Parsed::Ignored("缺少 nonce".into()),
    }
    Parsed::Event(Box::new(event))
}

/// 父进程发给 sidecar 的关闭命令（一行，含换行）。
pub fn shutdown_line(nonce: &str) -> String {
    let mut line = serde_json::json!({
        "protocol": PROTOCOL,
        "command": "shutdown",
        "nonce": nonce,
    })
    .to_string();
    line.push('\n');
    line
}

#[cfg(test)]
mod tests {
    use super::*;

    const N: &str = "4ddc73b05326e40fb418d87d029c34752bdb08d7c37a2299ef44252f567ead6d";

    /// A 交付的真实 CLI 输出（desktop.jsonl 第 6 行）。
    const REAL_ADDRESS: &str = r#"{"protocol": "mathlens.desktop/v1", "event": "address_published", "operation": "serve", "seq": 6, "nonce": "4ddc73b05326e40fb418d87d029c34752bdb08d7c37a2299ef44252f567ead6d", "pid": 65844, "phase": "address_published", "status": "completed", "server": {"url": "http://127.0.0.1:9318/", "pid": 65844, "version": "0.10.0", "data_id": "401fad314e33ed1f0920a866efe31db33dca2890799ef797172aa5d07b0d234f", "nonce": "4ddc73b05326e40fb418d87d029c34752bdb08d7c37a2299ef44252f567ead6d"}}"#;
    /// prepare-desktop.jsonl 第 4 行（字节进度）。
    const REAL_PROGRESS: &str = r#"{"protocol": "mathlens.desktop/v1", "event": "progress", "operation": "prepare", "seq": 4, "nonce": "4ddc73b05326e40fb418d87d029c34752bdb08d7c37a2299ef44252f567ead6d", "pid": 61952, "phase": "validate_seed", "status": "running", "message": "正在校验本地题库", "progress": {"unit": "bytes", "completed": 385024, "total": 385100}}"#;

    #[test]
    fn parses_real_sidecar_lines() {
        let Parsed::Event(e) = parse_line(REAL_ADDRESS, N) else {
            panic!()
        };
        let server = e.server.unwrap();
        assert_eq!(server.url, "http://127.0.0.1:9318/");
        assert_eq!(server.pid, 65844);
        assert_eq!(server.nonce.as_deref(), Some(N));
        let Parsed::Event(p) = parse_line(REAL_PROGRESS, N) else {
            panic!()
        };
        assert_eq!(p.progress.unwrap().total, Some(385100));
        assert_eq!(p.message.as_deref(), Some("正在校验本地题库"));
    }

    #[test]
    fn rejects_foreign_and_unknown_lines() {
        assert!(matches!(parse_line("hello", N), Parsed::Ignored(_)));
        assert!(matches!(parse_line("{\"a\":1}", N), Parsed::Ignored(_)));
        let other_nonce = REAL_ADDRESS.replace(N, &"0".repeat(64));
        assert!(matches!(parse_line(&other_nonce, N), Parsed::Ignored(_)));
        let v2 = REAL_ADDRESS.replace("mathlens.desktop/v1", "mathlens.desktop/v2");
        assert!(matches!(parse_line(&v2, N), Parsed::Fatal(_)));
        // 未知可选字段被忽略
        let extra = REAL_PROGRESS.replace("\"seq\": 4", "\"seq\": 4, \"future\": [1,2]");
        assert!(matches!(parse_line(&extra, N), Parsed::Event(_)));
    }

    #[test]
    fn error_events_may_lack_nonce() {
        let line = r#"{"protocol":"mathlens.desktop/v1","event":"error","operation":"prepare","seq":1,"nonce":null,"pid":1,"phase":"validate_config","status":"failed","error":{"code":"invalid_path","message":"路径不对","retryable":false}}"#;
        let Parsed::Event(e) = parse_line(line, N) else {
            panic!()
        };
        assert_eq!(e.error.unwrap().code, "invalid_path");
        let progress_without_nonce = line.replace("\"error\",", "\"progress\",");
        assert!(matches!(
            parse_line(&progress_without_nonce, N),
            Parsed::Ignored(_)
        ));
    }

    #[test]
    fn shutdown_line_is_single_json_line() {
        let line = shutdown_line(N);
        assert!(line.ends_with('\n') && !line.trim_end().contains('\n'));
        let v: serde_json::Value = serde_json::from_str(line.trim()).unwrap();
        assert_eq!(v["command"], "shutdown");
        assert_eq!(v["nonce"], N);
    }
}
