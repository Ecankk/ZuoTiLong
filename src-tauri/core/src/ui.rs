//! 退出码 / 错误码 → 加载页的标题、说明与可选操作（DESKTOP-SHELL 2.4 表）。
//! 文案面向学生：大白话，不出现技术词、错误码或英文。

use crate::protocol::ErrorInfo;
use serde::Serialize;

#[derive(Serialize, Clone, Copy, Debug, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Action {
    Retry,
    ChooseLocation,
    OpenLogs,
    Quit,
}

#[derive(Serialize, Clone, Debug, PartialEq)]
pub struct UiError {
    /// 诊断用（写日志，页面不显示）。
    pub code: String,
    pub title: String,
    pub message: String,
    pub actions: Vec<Action>,
    pub exit_code: Option<i32>,
}

fn err(
    code: &str,
    title: &str,
    message: String,
    actions: &[Action],
    exit_code: Option<i32>,
) -> UiError {
    UiError {
        code: code.into(),
        title: title.into(),
        message,
        actions: actions.to_vec(),
        exit_code,
    }
}

/// 后端给的中文短原因（若有）接在固定说明后面。
fn with_detail(base: &str, info: Option<&ErrorInfo>) -> String {
    match info.map(|i| i.message.trim()).filter(|m| !m.is_empty()) {
        Some(detail) if !base.contains(detail) => format!("{base}（{detail}）"),
        _ => base.to_string(),
    }
}

/// prepare 失败。`library_published`：题库已发布、只差建工作区。
pub fn prepare_failure(
    exit_code: Option<i32>,
    info: Option<&ErrorInfo>,
    library_published: bool,
) -> UiError {
    use Action::*;
    let code = info.map(|i| i.code.as_str()).unwrap_or("");
    match (exit_code, code) {
        (Some(130), _) | (_, "cancelled") => err(
            "cancelled",
            "已取消准备",
            "没有保存任何半成品。可以重新开始，或换一个位置。".into(),
            &[Retry, ChooseLocation, Quit],
            exit_code,
        ),
        (_, "disk_full") => err(
            "disk_full",
            "空间不够",
            with_detail("这个位置剩余空间不足以放下本地题库。请清理一些空间后重试，或换一个位置。", info),
            &[Retry, ChooseLocation, OpenLogs],
            exit_code,
        ),
        (Some(10), _) | (_, "permission_denied") | (_, "invalid_path") | (Some(2), _) => err(
            if code.is_empty() { "location_unusable" } else { code },
            "这个位置用不了",
            with_detail("做题龙没法在这里保存数据。请换一个文件夹。", info),
            &[ChooseLocation, OpenLogs],
            exit_code,
        ),
        (Some(11), _) | (_, "seed_invalid" | "seed_hash_mismatch" | "seed_db_invalid" | "seed_incompatible" | "resource_missing") => err(
            if code.is_empty() { "install_incomplete" } else { code },
            "安装文件不完整",
            "做题龙自带的题库或程序文件不完整，请重新安装做题龙。你的学习记录不会受影响。".into(),
            &[OpenLogs, Quit],
            exit_code,
        ),
        (Some(12), _) | (_, "library_incomplete" | "workspace_incomplete" | "workspace_location_mismatch") => err(
            if code.is_empty() { "location_conflict" } else { code },
            "这里的数据不完整",
            with_detail(
                "这个文件夹里的做题龙数据和记录对不上。为了不弄丢记录，请重新选择原来的数据文件夹。",
                info,
            ),
            &[ChooseLocation, OpenLogs],
            exit_code,
        ),
        (Some(13), _) | (_, "library_busy") => err(
            "library_busy",
            "这份数据正在被使用",
            "可能有另一个做题龙正在准备同一份数据。请稍后重试。".into(),
            &[Retry, Quit],
            exit_code,
        ),
        _ => {
            let message = if library_published {
                "题库已经准备好了，只差最后一步。请重试。".to_string()
            } else {
                with_detail("准备过程中出了问题。可以重试；如果反复出现，请打开日志发给我们。", info)
            };
            err(
                if code.is_empty() { "prepare_failed" } else { code },
                "准备没有完成",
                message,
                &[Retry, OpenLogs, Quit],
                exit_code,
            )
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub enum ServeFailure {
    SpawnFailed(String),
    Timeout,
    Exited {
        exit_code: Option<i32>,
        error: Option<ErrorInfo>,
    },
    Verify(String),
    VersionMismatch,
    ProtocolUnsupported,
}

pub fn serve_failure(failure: &ServeFailure) -> UiError {
    use Action::*;
    match failure {
        ServeFailure::SpawnFailed(_) => err(
            "spawn_failed",
            "做题龙没能启动",
            "后台程序打不开，可能被安全软件拦截，或安装文件不完整。请重试或重新安装。".into(),
            &[Retry, OpenLogs, Quit],
            None,
        ),
        ServeFailure::Timeout => err(
            "start_timeout",
            "启动时间太长",
            "做题龙等了 3 分钟还没准备好。可以重试；如果反复出现，请打开日志发给我们。".into(),
            &[Retry, OpenLogs, Quit],
            None,
        ),
        ServeFailure::VersionMismatch | ServeFailure::ProtocolUnsupported => err(
            "install_incomplete",
            "安装文件不完整",
            "做题龙的程序文件版本对不上，请重新安装做题龙。你的学习记录不会受影响。".into(),
            &[OpenLogs, Quit],
            None,
        ),
        ServeFailure::Verify(_) => err(
            "verify_failed",
            "做题龙没能启动",
            "后台启动了，但核对没有通过。请重试。".into(),
            &[Retry, OpenLogs, Quit],
            None,
        ),
        ServeFailure::Exited { exit_code, error } => {
            let code = error.as_ref().map(|e| e.code.as_str()).unwrap_or("");
            if matches!(
                code,
                "workspace_incomplete" | "workspace_location_mismatch" | "library_incomplete"
            ) || *exit_code == Some(12)
            {
                return prepare_failure(Some(12), error.as_ref(), false);
            }
            if matches!(code, "resource_missing") || *exit_code == Some(11) {
                return prepare_failure(Some(11), error.as_ref(), false);
            }
            if matches!(code, "permission_denied" | "invalid_path") || *exit_code == Some(10) {
                return prepare_failure(Some(10), error.as_ref(), false);
            }
            err(
                if code.is_empty() {
                    "start_failed"
                } else {
                    code
                },
                "做题龙没能启动",
                with_detail(
                    "后台启动时出了问题。可以重试；如果反复出现，请打开日志发给我们。",
                    error.as_ref(),
                ),
                &[Retry, OpenLogs, Quit],
                *exit_code,
            )
        }
    }
}

/// 运行中后台意外退出。
pub fn crashed(exit_code: Option<i32>) -> UiError {
    err(
        "backend_exited",
        "做题龙后台停止了",
        "后台意外停止。已经保存的记录不会丢失，点“重新启动”即可继续。".into(),
        &[Action::Retry, Action::OpenLogs, Action::Quit],
        exit_code,
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn info(code: &str) -> ErrorInfo {
        ErrorInfo {
            code: code.into(),
            message: "题库文件校验失败，请重新安装".into(),
            retryable: false,
        }
    }

    #[test]
    fn maps_each_documented_exit_code() {
        assert_eq!(prepare_failure(Some(130), None, false).code, "cancelled");
        let seed = prepare_failure(Some(11), Some(&info("seed_hash_mismatch")), false);
        assert_eq!(seed.title, "安装文件不完整");
        assert!(!seed.actions.contains(&Action::Retry));
        let full = prepare_failure(Some(10), Some(&info("disk_full")), false);
        assert!(full.actions.contains(&Action::Retry));
        assert!(full.actions.contains(&Action::ChooseLocation));
        let perm = prepare_failure(Some(10), Some(&info("permission_denied")), false);
        assert_eq!(perm.actions, vec![Action::ChooseLocation, Action::OpenLogs]);
        assert_eq!(
            prepare_failure(Some(12), Some(&info("workspace_location_mismatch")), false).title,
            "这里的数据不完整"
        );
        assert_eq!(prepare_failure(Some(13), None, false).code, "library_busy");
        let late = prepare_failure(Some(20), Some(&info("initialization_failed")), true);
        assert!(late.message.contains("只差最后一步"));
        assert!(prepare_failure(Some(9), None, false)
            .actions
            .contains(&Action::Retry));
    }

    #[test]
    fn serve_failures_reuse_location_mapping() {
        let e = serve_failure(&ServeFailure::Exited {
            exit_code: Some(12),
            error: Some(info("workspace_incomplete")),
        });
        assert!(e.actions.contains(&Action::ChooseLocation));
        assert_eq!(serve_failure(&ServeFailure::Timeout).code, "start_timeout");
        assert!(!serve_failure(&ServeFailure::VersionMismatch)
            .actions
            .contains(&Action::Retry));
    }

    #[test]
    fn student_text_has_no_codes() {
        for e in [
            prepare_failure(Some(11), Some(&info("seed_hash_mismatch")), false),
            serve_failure(&ServeFailure::Timeout),
            crashed(Some(3)),
        ] {
            assert!(!e.message.contains("seed_") && !e.title.contains('_'));
        }
    }
}
