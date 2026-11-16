//! 加载页的 boot_* 命令与给 React 的 desktop_* 固定命令（DESKTOP-SHELL 第 3 节）。
//!
//! desktop_* 只在健康核对后按确切 origin 授权；命令内部再核对一次调用页面的 origin。
//! 页面不能传任意路径：打开文件夹只收枚举，保存 Codex 只收外壳刚选出并探测通过的 pick_id。

use crate::controller::{Cmd, Shared, Stage};
use crate::shelllog::log;
use desktop_core::config::{self, Load};
use desktop_core::{codex, health, osinfo, VERSION};
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;
use tauri::{AppHandle, State, Webview};
use tauri_plugin_dialog::DialogExt;

type Ctl<'a> = State<'a, Arc<Shared>>;

#[derive(Serialize, Debug)]
pub struct CmdError {
    pub code: &'static str,
    pub message: String,
}

fn error(code: &'static str, message: impl Into<String>) -> CmdError {
    CmdError {
        code,
        message: message.into(),
    }
}

// ---------- 加载页 ----------

#[tauri::command]
pub fn boot_state(ctl: Ctl<'_>) -> crate::controller::Snapshot {
    ctl.snapshot()
}

#[tauri::command]
pub fn boot_use_default(ctl: Ctl<'_>) {
    ctl.send(Cmd::UseDefault);
}

#[tauri::command]
pub async fn boot_choose_folder(app: AppHandle, ctl: Ctl<'_>) -> Result<(), CmdError> {
    let shared = ctl.inner().clone();
    let picked = tauri::async_runtime::spawn_blocking(move || {
        app.dialog()
            .file()
            .set_title("选择做题龙的数据保存位置")
            .blocking_pick_folder()
    })
    .await
    .map_err(|_| error("dialog_failed", "没能打开选择窗口"))?;
    if let Some(path) = picked.and_then(|p| p.into_path().ok()) {
        shared.send(Cmd::Candidate(path));
    }
    Ok(())
}

#[tauri::command]
pub fn boot_confirm_location(ctl: Ctl<'_>) {
    ctl.send(Cmd::Confirm);
}

#[tauri::command]
pub fn boot_choose_location(ctl: Ctl<'_>) {
    ctl.send(Cmd::ChooseLocation);
}

#[tauri::command]
pub fn boot_cancel(ctl: Ctl<'_>) {
    if ctl.snapshot().stage == Stage::Preparing {
        ctl.cancel.store(true, std::sync::atomic::Ordering::SeqCst);
    }
    ctl.send(Cmd::Cancel);
}

#[tauri::command]
pub fn boot_retry(ctl: Ctl<'_>) {
    ctl.send(Cmd::Retry);
}

#[tauri::command]
pub fn boot_open_logs(ctl: Ctl<'_>) -> Result<(), CmdError> {
    let snapshot = ctl.snapshot();
    let workspace = ctl
        .config
        .lock()
        .ok()
        .and_then(|c| c.as_ref().map(|c| c.workspace_dir.clone()));
    let target = match (snapshot.stage, workspace) {
        (Stage::PrepareFailed, _) | (_, None) => ctl.env.shell_logs.clone(),
        (_, Some(ws)) if ws.exists() => ws,
        _ => ctl.env.shell_logs.clone(),
    };
    let _ = std::fs::create_dir_all(&ctl.env.shell_logs);
    open_dir(&target)
}

#[tauri::command]
pub fn boot_quit(ctl: Ctl<'_>) {
    ctl.request_exit();
}

// ---------- React（当前后端 origin） ----------

/// 再核对一次：调用页面必须是当前后端的确切 origin。
fn require_backend(webview: &Webview, ctl: &Shared) -> Result<u16, CmdError> {
    let port = ctl
        .port()
        .ok_or_else(|| error("not_available", "做题龙还没有准备好"))?;
    let url = webview
        .url()
        .map_err(|_| error("not_available", "做题龙还没有准备好"))?;
    if desktop_core::nav::is_backend(&url, Some(port)) {
        Ok(port)
    } else {
        Err(error("not_available", "这个页面不能使用桌面功能"))
    }
}

fn require_idle(port: u16) -> Result<(), CmdError> {
    match health::tasks_active(port, Duration::from_secs(3)) {
        Ok(true) => Err(error("busy", "做题龙正在处理任务，等它完成后再改。")),
        Ok(false) => Ok(()),
        // 后台答不上来时不阻止（多半是后台本身出了问题，重启正好能恢复）
        Err(e) => {
            log(format!("查询任务状态失败：{e}"));
            Ok(())
        }
    }
}

#[derive(Serialize)]
pub struct AppInfo {
    pub name: &'static str,
    pub version: &'static str,
    pub commit: Option<&'static str>,
    pub tauri: &'static str,
    pub webview2: Option<String>,
    pub os: String,
}

#[derive(Serialize)]
pub struct DataInfo {
    pub root: String,
    pub workspace: String,
    pub library: String,
    pub is_default_root: bool,
    pub logs: String,
    pub locator: String,
}

#[derive(Serialize)]
pub struct CodexInfo {
    pub configured_path: Option<String>,
}

#[derive(Serialize)]
pub struct DesktopInfo {
    pub schema: &'static str,
    pub app: AppInfo,
    pub data: DataInfo,
    pub codex: CodexInfo,
}

#[tauri::command]
pub fn desktop_info(webview: Webview, ctl: Ctl<'_>) -> Result<DesktopInfo, CmdError> {
    require_backend(&webview, &ctl)?;
    let cfg = ctl
        .config
        .lock()
        .ok()
        .and_then(|c| c.clone())
        .ok_or_else(|| error("io_error", "读不到数据位置"))?;
    let is_default = desktop_core::paths::is_within(&cfg.data_root, &ctl.env.default_root)
        && desktop_core::paths::is_within(&ctl.env.default_root, &cfg.data_root);
    Ok(DesktopInfo {
        schema: "zuotilong.desktop-info/v1",
        app: AppInfo {
            name: "做题龙",
            version: VERSION,
            commit: option_env!("ZUOTILONG_COMMIT"),
            tauri: tauri::VERSION,
            webview2: tauri::webview_version().ok(),
            os: osinfo::os_description(),
        },
        data: DataInfo {
            root: cfg.data_root.display().to_string(),
            workspace: cfg.workspace_dir.display().to_string(),
            library: cfg.library_dir.display().to_string(),
            is_default_root: is_default,
            logs: cfg.workspace_dir.display().to_string(),
            locator: ctl.env.locator_file.display().to_string(),
        },
        codex: CodexInfo {
            configured_path: cfg.codex_bin.map(|p| p.display().to_string()),
        },
    })
}

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FolderTarget {
    DataRoot,
    Workspace,
    Library,
    Logs,
    Licenses,
}

fn open_dir(path: &std::path::Path) -> Result<(), CmdError> {
    if !path.is_dir() {
        return Err(error("missing", "这个文件夹不存在"));
    }
    tauri_plugin_opener::open_path(path, None::<&str>)
        .map_err(|e| error("io_error", format!("没能打开文件夹：{e}")))
}

#[tauri::command]
pub fn desktop_open_folder(
    webview: Webview,
    ctl: Ctl<'_>,
    target: FolderTarget,
) -> Result<(), CmdError> {
    require_backend(&webview, &ctl)?;
    let cfg = ctl.config.lock().ok().and_then(|c| c.clone());
    let path: PathBuf = match (target, cfg) {
        (FolderTarget::Licenses, _) => ctl.env.licenses_dir(),
        (_, None) => return Err(error("missing", "读不到数据位置")),
        (FolderTarget::DataRoot, Some(c)) => c.data_root,
        (FolderTarget::Workspace | FolderTarget::Logs, Some(c)) => c.workspace_dir,
        (FolderTarget::Library, Some(c)) => c.library_dir,
    };
    open_dir(&path)
}

#[derive(Serialize)]
pub struct CodexPick {
    pub pick_id: String,
    pub path: String,
    pub version: Option<String>,
    pub probe: &'static str,
    pub message: Option<String>,
}

#[tauri::command]
pub async fn desktop_pick_codex(
    app: AppHandle,
    webview: Webview,
    ctl: Ctl<'_>,
) -> Result<Option<CodexPick>, CmdError> {
    require_backend(&webview, &ctl)?;
    let shared = ctl.inner().clone();
    let start_dir = codex::default_dir(&shared.env.local_app_data);
    let picked = tauri::async_runtime::spawn_blocking(move || {
        let mut dialog = app
            .dialog()
            .file()
            .set_title("选择 codex.exe")
            .add_filter("codex.exe", &["exe"]);
        if start_dir.is_dir() {
            dialog = dialog.set_directory(&start_dir);
        }
        dialog.blocking_pick_file()
    })
    .await
    .map_err(|_| error("dialog_failed", "没能打开选择窗口"))?;
    let Some(path) = picked.and_then(|p| p.into_path().ok()) else {
        return Ok(None);
    };
    let env = shared.child_env(None);
    let cwd = std::env::temp_dir();
    let probe_path = path.clone();
    let probe = tauri::async_runtime::spawn_blocking(move || {
        codex::probe(&probe_path, &env, &cwd, Duration::from_secs(10))
    })
    .await
    .map_err(|_| error("probe_failed", "没能检查这个程序"))?;
    log(format!("选择 Codex {} ok={}", path.display(), probe.ok));
    let pick_id = shared.store_pick(path.clone(), probe.ok);
    Ok(Some(CodexPick {
        pick_id,
        path: path.display().to_string(),
        version: probe.version,
        probe: if probe.ok { "ok" } else { "failed" },
        message: probe.message,
    }))
}

#[derive(Serialize)]
pub struct Restarting {
    pub status: &'static str,
}

#[tauri::command(rename_all = "snake_case")]
pub fn desktop_save_codex(
    webview: Webview,
    ctl: Ctl<'_>,
    pick_id: Option<String>,
    auto: Option<bool>,
) -> Result<Restarting, CmdError> {
    let port = require_backend(&webview, &ctl)?;
    let new_path = if auto == Some(true) {
        None
    } else {
        let id = pick_id.ok_or_else(|| error("stale_pick", "请重新选择 codex.exe"))?;
        Some(
            ctl.take_pick(&id)
                .ok_or_else(|| error("stale_pick", "请重新选择 codex.exe"))?,
        )
    };
    require_idle(port)?;
    let mut cfg = match config::load(&ctl.env.locator_file) {
        Load::Loaded(cfg) => cfg,
        _ => return Err(error("io_error", "读不到当前设置")),
    };
    cfg.codex_bin = new_path;
    config::save(&ctl.env.locator_file, &cfg)
        .map_err(|e| error("io_error", format!("保存失败：{e}")))?;
    log(format!("已保存 Codex 路径 {:?}，重启后台", cfg.codex_bin));
    if let Ok(mut current) = ctl.config.lock() {
        *current = Some(cfg);
    }
    ctl.send(Cmd::Restart);
    Ok(Restarting {
        status: "restarting",
    })
}

#[tauri::command]
pub fn desktop_restart_backend(webview: Webview, ctl: Ctl<'_>) -> Result<Restarting, CmdError> {
    let port = require_backend(&webview, &ctl)?;
    require_idle(port)?;
    ctl.send(Cmd::Restart);
    Ok(Restarting {
        status: "restarting",
    })
}

#[tauri::command]
pub fn desktop_relocate(webview: Webview, ctl: Ctl<'_>) -> Result<Restarting, CmdError> {
    let port = require_backend(&webview, &ctl)?;
    require_idle(port)?;
    ctl.send(Cmd::Relocate);
    Ok(Restarting { status: "stopping" })
}
