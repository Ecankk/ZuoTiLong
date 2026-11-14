//! 外壳状态机（DESKTOP-SHELL 第 2 节）。
//!
//! 一个工作线程独占 sidecar，按 定位 → 选位置 → prepare → serve → 核对 → 同源导航 的顺序推进；
//! 界面命令只往通道里投消息（取消/退出另设标志，进行中的流程能立刻看到）。每次状态变化都把
//! 整份 [`Snapshot`] 推给内嵌加载页（事件 `boot://state`）。

use crate::environment::Environment;
use crate::shelllog::log;
use desktop_core::config::{self, DesktopConfig, Load};
use desktop_core::logs::{self, shared, Ring, RotatingFile, Sink};
use desktop_core::paths::{self, Layout, RootKind};
use desktop_core::protocol::{ErrorInfo, Progress, ServerInfo};
use desktop_core::sidecar::{Message, Sidecar, SpawnSpec};
use desktop_core::ui::{self, ServeFailure, UiError};
use desktop_core::{envpath, health, nonce, timefmt, VERSION};
use serde::Serialize;
use std::collections::HashMap;
use std::ffi::OsString;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError, Sender};
use std::sync::{Arc, Condvar, Mutex};
use std::time::{Duration, Instant};
use tauri::ipc::CapabilityBuilder;
use tauri::{AppHandle, Emitter, Manager, Url};

pub const MAIN: &str = "main";
pub const STATE_EVENT: &str = "boot://state";
const GRACE: Duration = Duration::from_secs(10);
const START_TIMEOUT: Duration = Duration::from_secs(180);
const SLOW_AFTER: Duration = Duration::from_secs(120);
const PICK_TTL: Duration = Duration::from_secs(300);

/// 给 React 用的命令（健康核对后按确切 origin 授权）。
pub const DESKTOP_PERMISSIONS: &[&str] = &[
    "allow-desktop-info",
    "allow-desktop-open-folder",
    "allow-desktop-pick-codex",
    "allow-desktop-save-codex",
    "allow-desktop-restart-backend",
    "allow-desktop-relocate",
];

#[derive(Serialize, Clone, Copy, Debug, PartialEq, Eq, Default)]
#[serde(rename_all = "snake_case")]
pub enum Stage {
    #[default]
    Booting,
    ChooseLocation,
    Preparing,
    PrepareFailed,
    Starting,
    StartFailed,
    Ready,
    Crashed,
    Restarting,
    Stopping,
}

#[derive(Serialize, Clone, Debug, PartialEq)]
pub struct CandidateView {
    pub path: String,
    /// fresh / partial / existing / unusable
    pub kind: &'static str,
    pub is_default: bool,
    pub usable: bool,
    pub message: Option<String>,
}

#[derive(Serialize, Clone, Debug, PartialEq)]
pub struct LocationView {
    pub root: String,
    pub workspace: String,
    pub library: String,
}

#[derive(Serialize, Clone, Debug, Default, PartialEq)]
pub struct Snapshot {
    pub stage: Stage,
    pub app_version: &'static str,
    pub default_root: String,
    pub candidate: Option<CandidateView>,
    /// 从设置页“更改数据位置”进入时为 true（可取消回到原位置）。
    pub relocating: bool,
    /// 选位置页顶部的提示（例如上次的位置找不到了）。
    pub notice: Option<String>,
    pub location: Option<LocationView>,
    pub phase: Option<String>,
    pub message: Option<String>,
    pub progress: Option<Progress>,
    pub slow: bool,
    pub error: Option<UiError>,
}

pub enum Cmd {
    Candidate(PathBuf),
    UseDefault,
    Confirm,
    ChooseLocation,
    Cancel,
    Retry,
    Restart,
    Relocate,
    Exit,
}

pub struct Pick {
    pub path: PathBuf,
    pub ok: bool,
    pub created: Instant,
}

/// 线程间共享的状态（命令线程只读或设置标志，流程由工作线程推进）。
pub struct Shared {
    pub env: Environment,
    pub snapshot: Mutex<Snapshot>,
    pub config: Mutex<Option<DesktopConfig>>,
    /// 当前已核对的后端端口；0 表示没有。
    pub backend_port: AtomicU32,
    pub cancel: AtomicBool,
    pub exiting: AtomicBool,
    pub picks: Mutex<HashMap<String, Pick>>,
    pub loader_url: Mutex<Option<Url>>,
    /// 加载页第一次加载完成（之前不做任何导航，避免与初始加载互相覆盖）。
    pub loader_loaded: (Mutex<bool>, Condvar),
    tx: Mutex<Sender<Cmd>>,
}

impl Shared {
    pub fn mark_loader_loaded(&self) {
        let (lock, cvar) = &self.loader_loaded;
        if let Ok(mut loaded) = lock.lock() {
            if !*loaded {
                *loaded = true;
                cvar.notify_all();
            }
        }
    }

    pub fn send(&self, cmd: Cmd) {
        if let Ok(tx) = self.tx.lock() {
            let _ = tx.send(cmd);
        }
    }

    pub fn port(&self) -> Option<u16> {
        match self.backend_port.load(Ordering::SeqCst) {
            0 => None,
            p => u16::try_from(p).ok(),
        }
    }

    pub fn request_exit(&self) {
        if !self.exiting.swap(true, Ordering::SeqCst) {
            self.cancel.store(true, Ordering::SeqCst);
            self.send(Cmd::Exit);
        }
    }

    pub fn snapshot(&self) -> Snapshot {
        self.snapshot.lock().map(|s| s.clone()).unwrap_or_default()
    }

    pub fn store_pick(&self, path: PathBuf, ok: bool) -> String {
        let id = nonce::short_id();
        if let Ok(mut picks) = self.picks.lock() {
            picks.retain(|_, p| p.created.elapsed() < PICK_TTL);
            picks.insert(
                id.clone(),
                Pick {
                    path,
                    ok,
                    created: Instant::now(),
                },
            );
        }
        id
    }

    /// 取出（并作废）一次选择；过期或探测失败返回 None。
    pub fn take_pick(&self, id: &str) -> Option<PathBuf> {
        let mut picks = self.picks.lock().ok()?;
        let pick = picks.remove(id)?;
        (pick.ok && pick.created.elapsed() < PICK_TTL).then_some(pick.path)
    }

    /// 子进程环境：当前环境去掉 MATHLENS_*，PATH 从注册表重读，必要时注入 Codex 路径。
    pub fn child_env(&self, codex: Option<&Path>) -> Vec<(OsString, OsString)> {
        let codex = codex.or(self.env.dev_codex.as_deref());
        let mut env = envpath::child_env(std::env::vars_os(), envpath::registry_path(), codex);
        env.extend(self.env.backend.extra_env.iter().cloned());
        env
    }
}

enum RetryTarget {
    Prepare(Layout),
    Serve,
}

pub struct Worker {
    app: AppHandle,
    shared: Arc<Shared>,
    rx: Receiver<Cmd>,
    sidecar: Option<Sidecar>,
    candidate: Option<Layout>,
    retry: Option<RetryTarget>,
    /// 更改位置前的配置（取消时回到这里）。
    previous: Option<DesktopConfig>,
}

pub fn start(app: AppHandle, env: Environment) -> Arc<Shared> {
    let (tx, rx) = mpsc::channel();
    let shared = Arc::new(Shared {
        snapshot: Mutex::new(Snapshot {
            app_version: VERSION,
            default_root: env.default_root.display().to_string(),
            ..Default::default()
        }),
        env,
        config: Mutex::new(None),
        backend_port: AtomicU32::new(0),
        cancel: AtomicBool::new(false),
        exiting: AtomicBool::new(false),
        picks: Mutex::new(HashMap::new()),
        loader_url: Mutex::new(None),
        loader_loaded: (Mutex::new(false), Condvar::new()),
        tx: Mutex::new(tx),
    });
    let worker = Worker {
        app,
        shared: shared.clone(),
        rx,
        sidecar: None,
        candidate: None,
        retry: None,
        previous: None,
    };
    std::thread::Builder::new()
        .name("shell-controller".into())
        .spawn(move || worker.run())
        .expect("启动外壳工作线程");
    shared
}

impl Worker {
    fn run(mut self) {
        self.wait_loader();
        self.boot();
        loop {
            match self.rx.recv_timeout(Duration::from_millis(300)) {
                Ok(Cmd::Exit) => {
                    self.exit_app();
                    return;
                }
                Ok(cmd) => self.handle(cmd),
                Err(RecvTimeoutError::Timeout) => {}
                Err(RecvTimeoutError::Disconnected) => return,
            }
            if self.shared.exiting.load(Ordering::SeqCst) {
                self.exit_app();
                return;
            }
            self.tick();
        }
    }

    fn wait_loader(&self) {
        let (lock, cvar) = &self.shared.loader_loaded;
        let guard = lock.lock().unwrap();
        let (_guard, timeout) = cvar
            .wait_timeout_while(guard, Duration::from_secs(30), |loaded| !*loaded)
            .unwrap();
        if timeout.timed_out() {
            log("等待加载页超时，继续");
        }
    }

    fn handle(&mut self, cmd: Cmd) {
        let stage = self.shared.snapshot().stage;
        match cmd {
            Cmd::Candidate(path) if stage == Stage::ChooseLocation => self.set_candidate(&path),
            Cmd::UseDefault if stage == Stage::ChooseLocation => {
                let root = self.shared.env.default_root.clone();
                self.set_candidate(&root)
            }
            Cmd::Confirm if stage == Stage::ChooseLocation => self.confirm(),
            Cmd::ChooseLocation
                if matches!(
                    stage,
                    Stage::PrepareFailed | Stage::StartFailed | Stage::Crashed
                ) =>
            {
                let root = self.current_root();
                self.enter_choose(&root, None, false)
            }
            Cmd::Cancel if stage == Stage::ChooseLocation => {
                if let Some(old) = self.previous.take() {
                    log("取消更改位置，回到原位置");
                    *self.shared.config.lock().unwrap() = Some(old.clone());
                    self.run_serve(old, None);
                }
            }
            Cmd::Retry
                if matches!(
                    stage,
                    Stage::PrepareFailed | Stage::StartFailed | Stage::Crashed
                ) =>
            {
                match self.retry.take() {
                    Some(RetryTarget::Prepare(layout)) => self.run_prepare(layout),
                    Some(RetryTarget::Serve) => match self.config() {
                        Some(cfg) => self.run_serve(cfg, None),
                        None => self.boot(),
                    },
                    None => self.boot(),
                }
            }
            Cmd::Restart if stage == Stage::Ready => self.restart(),
            Cmd::Relocate if stage == Stage::Ready => self.relocate(),
            _ => {}
        }
    }

    // ---------- 状态推送与导航 ----------

    fn update(&self, f: impl FnOnce(&mut Snapshot)) {
        let snapshot = {
            let mut guard = self.shared.snapshot.lock().unwrap();
            f(&mut guard);
            guard.clone()
        };
        let _ = self.app.emit_to(MAIN, STATE_EVENT, snapshot);
    }

    fn set_stage(&self, stage: Stage) {
        self.update(|s| {
            s.stage = stage;
            s.phase = None;
            s.message = None;
            s.progress = None;
            s.slow = false;
            s.error = None;
        });
    }

    fn fail(&mut self, stage: Stage, error: UiError, retry: Option<RetryTarget>) {
        log(format!(
            "失败 stage={stage:?} code={} exit={:?}",
            error.code, error.exit_code
        ));
        self.retry = retry;
        self.update(|s| {
            s.stage = stage;
            s.progress = None;
            s.slow = false;
            s.error = Some(error);
        });
    }

    fn window(&self) -> Option<tauri::WebviewWindow> {
        self.app.get_webview_window(MAIN)
    }

    /// 让主窗口回到内嵌加载页（后端页面不再发请求）。
    fn show_loader(&self) {
        let Some(window) = self.window() else { return };
        let loader = self
            .shared
            .loader_url
            .lock()
            .unwrap()
            .clone()
            .unwrap_or_else(|| Url::parse("http://tauri.localhost/index.html").expect("固定地址"));
        let on_loader = window
            .url()
            .map(|u| u.origin() == loader.origin())
            .unwrap_or(false);
        if !on_loader {
            let _ = window.navigate(loader);
        }
    }

    /// 后端页面当前的路由（path+query），重启后回到原页。
    fn current_route(&self) -> Option<String> {
        let port = self.shared.port()?;
        let url = self.window()?.url().ok()?;
        if !desktop_core::nav::is_backend(&url, Some(port)) {
            return None;
        }
        let mut route = url.path().to_string();
        if let Some(q) = url.query() {
            route.push('?');
            route.push_str(q);
        }
        Some(route)
    }

    fn config(&self) -> Option<DesktopConfig> {
        self.shared.config.lock().unwrap().clone()
    }

    fn current_root(&self) -> PathBuf {
        self.config()
            .map(|c| c.data_root)
            .or_else(|| self.candidate.as_ref().map(|l| l.root.clone()))
            .unwrap_or_else(|| self.shared.env.default_root.clone())
    }

    fn location_of(cfg: &DesktopConfig) -> LocationView {
        LocationView {
            root: cfg.data_root.display().to_string(),
            workspace: cfg.workspace_dir.display().to_string(),
            library: cfg.library_dir.display().to_string(),
        }
    }

    // ---------- 定位与选位置 ----------

    fn boot(&mut self) {
        let file = self.shared.env.locator_file.clone();
        match config::load(&file) {
            Load::Missing => {
                log("首次运行：没有定位文件");
                let root = self.shared.env.default_root.clone();
                self.enter_choose(&root, None, false);
            }
            Load::Invalid(reason) => {
                let moved = config::quarantine(&file);
                log(format!("定位文件不可用（{reason}），已另存为 {moved:?}"));
                let root = self.shared.env.default_root.clone();
                self.enter_choose(
                    &root,
                    Some("原来的设置文件读不出来，已另外保存。请重新确认数据保存位置。".into()),
                    false,
                );
            }
            Load::Loaded(cfg) => {
                if !cfg
                    .workspace_dir
                    .join(desktop_core::workspace::FILE_NAME)
                    .exists()
                    && !cfg.workspace_dir.exists()
                {
                    log(format!("找不到上次的数据位置 {}", cfg.data_root.display()));
                    *self.shared.config.lock().unwrap() = Some(cfg.clone());
                    let notice = format!(
                        "找不到上次的数据文件夹：{}。如果移动过它，请重新选择那个文件夹；也可以在别的位置重新开始（原来的记录不会被删除）。",
                        cfg.data_root.display()
                    );
                    let root = self.shared.env.default_root.clone();
                    self.enter_choose(&root, Some(notice), false);
                    return;
                }
                *self.shared.config.lock().unwrap() = Some(cfg.clone());
                if cfg.needs_prepare(VERSION) {
                    self.run_prepare(Layout {
                        root: cfg.data_root.clone(),
                        workspace: cfg.workspace_dir.clone(),
                        library: cfg.library_dir.clone(),
                    });
                } else {
                    self.run_serve(cfg, None);
                }
            }
        }
    }

    fn enter_choose(&mut self, root: &Path, notice: Option<String>, relocating: bool) {
        self.set_stage(Stage::ChooseLocation);
        self.update(|s| {
            s.notice = notice;
            s.relocating = relocating;
        });
        self.set_candidate(root);
    }

    fn set_candidate(&mut self, root: &Path) {
        let is_default = paths::is_within(root, &self.shared.env.default_root)
            && paths::is_within(&self.shared.env.default_root, root);
        let (kind, usable, message, layout) =
            match paths::inspect_root(root, &self.shared.env.forbidden) {
                Ok(RootKind::Fresh) => ("fresh", true, None, Some(Layout::fresh(root))),
                Ok(RootKind::Partial) => (
                    "partial",
                    true,
                    Some("这里有上次没准备完的数据，会接着准备。".to_string()),
                    Some(Layout::fresh(root)),
                ),
                Ok(RootKind::Existing { workspace, library }) => (
                    "existing",
                    true,
                    Some("这里已经有做题龙的记录，会直接使用。".to_string()),
                    Some(Layout {
                        root: root.to_path_buf(),
                        workspace,
                        library,
                    }),
                ),
                Ok(RootKind::Foreign) => (
                    "unusable",
                    false,
                    Some(
                        "这个文件夹里有其他文件。请选择一个空文件夹，或原来的做题龙数据文件夹。"
                            .to_string(),
                    ),
                    None,
                ),
                Err(e) => ("unusable", false, Some(e.message()), None),
            };
        self.candidate = layout;
        let view = CandidateView {
            path: root.display().to_string(),
            kind,
            is_default,
            usable,
            message,
        };
        self.update(|s| s.candidate = Some(view));
    }

    fn confirm(&mut self) {
        let Some(layout) = self.candidate.clone() else {
            return;
        };
        if let Err(e) = paths::ensure_writable(&layout.root) {
            log(format!("位置不可写 {}：{e}", layout.root.display()));
            self.update(|s| {
                if let Some(c) = s.candidate.as_mut() {
                    c.usable = false;
                    c.kind = "unusable";
                    c.message = Some("做题龙没法在这里保存文件，请换一个文件夹。".into());
                }
            });
            return;
        }
        log(format!("确认数据位置 {}", layout.root.display()));
        self.run_prepare(layout);
    }

    // ---------- prepare ----------

    fn spec(&self, args: Vec<OsString>, layout: &Layout, codex: Option<&Path>) -> SpawnSpec {
        let backend = &self.shared.env.backend;
        let mut all = backend.prefix.clone();
        all.extend(args);
        let cwd = if layout.workspace.exists() {
            layout.workspace.clone()
        } else {
            layout.root.clone()
        };
        SpawnSpec {
            program: backend.program.clone(),
            args: all,
            cwd,
            env: self.shared.child_env(codex),
        }
    }

    fn common_args(&self, mode: &str, layout: &Layout, nonce: &str) -> Vec<OsString> {
        vec![
            mode.into(),
            "--resource-root".into(),
            self.shared.env.resources_root.clone().into(),
            "--data-dir".into(),
            layout.workspace.clone().into(),
            "--library-dir".into(),
            layout.library.clone().into(),
            "--launch-nonce".into(),
            nonce.into(),
        ]
    }

    fn run_prepare(&mut self, layout: Layout) {
        self.shared.cancel.store(false, Ordering::SeqCst);
        self.set_stage(Stage::Preparing);
        self.update(|s| {
            s.message = Some("正在检查数据位置".into());
            s.location = Some(LocationView {
                root: layout.root.display().to_string(),
                workspace: layout.workspace.display().to_string(),
                library: layout.library.display().to_string(),
            });
        });
        if let Err(e) = std::fs::create_dir_all(&layout.root) {
            let err = ui::prepare_failure(
                Some(10),
                Some(&ErrorInfo {
                    code: "permission_denied".into(),
                    message: e.to_string(),
                    retryable: false,
                }),
                false,
            );
            return self.fail(
                Stage::PrepareFailed,
                err,
                Some(RetryTarget::Prepare(layout)),
            );
        }
        let codex = self.config().and_then(|c| c.codex_bin);
        let nonce = nonce::launch_nonce();
        let args = self.common_args("--prepare-desktop", &layout, &nonce);
        let spec = self.spec(args, &layout, codex.as_deref());
        log(format!("prepare 开始 root={}", layout.root.display()));
        let mut sidecar = match Sidecar::spawn(
            spec,
            &nonce,
            shared(Sink::Buffer(Ring::new(logs::RING_CAP))),
            shared(Sink::Buffer(Ring::new(logs::RING_CAP))),
        ) {
            Ok(s) => s,
            Err(e) => {
                log(format!("prepare 启动失败：{e}"));
                return self.fail(
                    Stage::PrepareFailed,
                    ui::serve_failure(&ServeFailure::SpawnFailed(e.to_string())),
                    Some(RetryTarget::Prepare(layout)),
                );
            }
        };

        let mut prepared = false;
        let mut last_error: Option<ErrorInfo> = None;
        let mut published = false;
        let mut fatal = false;
        let mut cancel_sent = false;
        let mut last_event = Instant::now();
        let status = loop {
            if self.shared.cancel.load(Ordering::SeqCst) && !cancel_sent {
                log("prepare 取消：发送 shutdown");
                sidecar.request_shutdown();
                cancel_sent = true;
                self.update(|s| s.message = Some("正在取消…".into()));
                let killed_after = Instant::now() + GRACE;
                while Instant::now() < killed_after {
                    if let Ok(Some(_)) = sidecar.try_wait() {
                        break;
                    }
                    std::thread::sleep(Duration::from_millis(50));
                }
                if let Ok(None) = sidecar.try_wait() {
                    log("prepare 取消超时：结束进程树");
                    sidecar.kill_tree();
                }
            }
            match sidecar.recv_timeout(Duration::from_millis(100)) {
                Some(Message::Event(event)) => {
                    last_event = Instant::now();
                    if event.library_published == Some(true) {
                        published = true;
                    }
                    match event.event.as_str() {
                        "progress" => self.update(|s| {
                            s.phase = event.phase.clone();
                            if let Some(m) = event.message.clone() {
                                s.message = Some(m);
                            }
                            s.progress = event.progress.clone();
                            s.slow = false;
                        }),
                        "prepared" => prepared = true,
                        "error" => last_error = event.error.clone(),
                        _ => {}
                    }
                }
                Some(Message::Fatal(reason)) => {
                    log(format!("prepare 协议不兼容：{reason}"));
                    fatal = true;
                    sidecar.kill_tree();
                }
                Some(Message::Ignored(reason)) => log(format!("prepare 忽略一行：{reason}")),
                Some(Message::StdoutClosed) | None => {}
            }
            if last_event.elapsed() > SLOW_AFTER {
                self.update(|s| s.slow = true);
            }
            match sidecar.try_wait() {
                Ok(Some(status)) => break status.code(),
                Ok(None) => {}
                Err(_) => break None,
            }
        };
        sidecar.finish();
        for msg in sidecar.drain() {
            if let Message::Event(event) = msg {
                if event.event == "prepared" {
                    prepared = true;
                }
                if event.event == "error" {
                    last_error = event.error.clone();
                }
            }
        }
        log(format!("prepare 结束 exit={status:?} prepared={prepared}"));

        if status == Some(0) && prepared && !fatal {
            let previous = self.config();
            let mut cfg = DesktopConfig::new(
                layout.root.clone(),
                layout.workspace.clone(),
                layout.library.clone(),
            );
            cfg.codex_bin = previous.and_then(|p| p.codex_bin);
            cfg.mark_prepared(VERSION);
            if let Err(e) = config::save(&self.shared.env.locator_file, &cfg) {
                log(format!("写定位文件失败：{e}"));
                let err = ui::prepare_failure(
                    Some(10),
                    Some(&ErrorInfo {
                        code: "permission_denied".into(),
                        message: "保存设置失败".into(),
                        retryable: true,
                    }),
                    true,
                );
                return self.fail(
                    Stage::PrepareFailed,
                    err,
                    Some(RetryTarget::Prepare(layout)),
                );
            }
            write_rings_to_workspace(&sidecar, &layout.workspace);
            self.previous = None;
            *self.shared.config.lock().unwrap() = Some(cfg.clone());
            return self.run_serve(cfg, None);
        }

        dump_failed_prepare(&sidecar, &self.shared.env.shell_logs);
        if self.shared.exiting.load(Ordering::SeqCst) {
            return;
        }
        let cancelled = cancel_sent || status == Some(130);
        if cancelled && self.config().is_none() {
            let root = layout.root.clone();
            return self.enter_choose(
                &root,
                Some("已取消准备，没有保存任何半成品。".into()),
                false,
            );
        }
        let error = if fatal {
            ui::serve_failure(&ServeFailure::ProtocolUnsupported)
        } else {
            ui::prepare_failure(status, last_error.as_ref(), published)
        };
        self.fail(
            Stage::PrepareFailed,
            error,
            Some(RetryTarget::Prepare(layout)),
        );
    }

    // ---------- serve ----------

    fn run_serve(&mut self, cfg: DesktopConfig, route: Option<String>) {
        self.shared.cancel.store(false, Ordering::SeqCst);
        self.shared.backend_port.store(0, Ordering::SeqCst);
        self.show_loader();
        self.set_stage(Stage::Starting);
        self.update(|s| {
            s.message = Some("正在启动做题龙".into());
            s.location = Some(Self::location_of(&cfg));
            s.relocating = false;
            s.notice = None;
        });
        let layout = Layout {
            root: cfg.data_root.clone(),
            workspace: cfg.workspace_dir.clone(),
            library: cfg.library_dir.clone(),
        };
        let open = |name: &str| match RotatingFile::open(
            &cfg.workspace_dir.join(name),
            logs::SERVER_LOG_MAX,
            logs::SERVER_LOG_KEEP,
        ) {
            Ok(file) => Sink::File(file),
            Err(e) => {
                log(format!("打不开日志 {name}：{e}"));
                Sink::Null
            }
        };
        let nonce = nonce::launch_nonce();
        let mut args = self.common_args("--desktop", &layout, &nonce);
        args.extend([
            "--host".into(),
            "127.0.0.1".into(),
            "--port".into(),
            "0".into(),
        ]);
        let spec = self.spec(args, &layout, cfg.codex_bin.as_deref());
        log(format!(
            "serve 启动 workspace={} codex={:?}",
            cfg.workspace_dir.display(),
            cfg.codex_bin
        ));
        let mut sidecar = match Sidecar::spawn(
            spec,
            &nonce,
            shared(open(logs::STDOUT_LOG)),
            shared(open(logs::STDERR_LOG)),
        ) {
            Ok(s) => s,
            Err(e) => {
                log(format!("serve 启动失败：{e}"));
                return self.fail(
                    Stage::StartFailed,
                    ui::serve_failure(&ServeFailure::SpawnFailed(e.to_string())),
                    Some(RetryTarget::Serve),
                );
            }
        };

        let deadline = Instant::now() + START_TIMEOUT;
        let mut address: Option<ServerInfo> = None;
        let mut last_error: Option<ErrorInfo> = None;
        let outcome: Result<health::Verified, ServeFailure> = loop {
            if self.shared.exiting.load(Ordering::SeqCst) {
                sidecar.shutdown(GRACE);
                return;
            }
            if Instant::now() > deadline {
                log("serve 超时：关闭本次进程");
                sidecar.shutdown(GRACE);
                break Err(ServeFailure::Timeout);
            }
            match sidecar.recv_timeout(Duration::from_millis(100)) {
                Some(Message::Event(event)) => match event.event.as_str() {
                    "progress" => self.update(|s| {
                        s.phase = event.phase.clone();
                        if let Some(m) = event.message.clone() {
                            s.message = Some(m);
                        }
                        s.progress = event.progress.clone();
                    }),
                    "address_published" => address = event.server.clone(),
                    "error" => last_error = event.error.clone(),
                    _ => {}
                },
                Some(Message::Fatal(reason)) => {
                    log(format!("serve 协议不兼容：{reason}"));
                    sidecar.kill_tree();
                    break Err(ServeFailure::ProtocolUnsupported);
                }
                Some(Message::Ignored(reason)) => log(format!("serve 忽略一行：{reason}")),
                Some(Message::StdoutClosed) | None => {}
            }
            if let Some(server) = address.as_ref() {
                let port = match health::loopback_port(&server.url) {
                    Ok(p) => p,
                    Err(e) => {
                        sidecar.shutdown(GRACE);
                        break Err(ServeFailure::Verify(e.to_string()));
                    }
                };
                match health::fetch_health(port, Duration::from_secs(2)) {
                    Ok(h) => {
                        let file = health::read_server_json(&cfg.workspace_dir);
                        match health::verify(
                            server,
                            file.as_ref(),
                            &h,
                            |p| sidecar.owns_pid(p),
                            &nonce,
                            VERSION,
                        ) {
                            Ok(v) => break Ok(v),
                            Err(health::VerifyError::VersionMismatch { got, want }) => {
                                log(format!("版本不一致 后台={got} 外壳={want}"));
                                sidecar.shutdown(GRACE);
                                break Err(ServeFailure::VersionMismatch);
                            }
                            Err(e) => {
                                log(format!("核对失败：{e}"));
                                sidecar.shutdown(GRACE);
                                break Err(ServeFailure::Verify(e.to_string()));
                            }
                        }
                    }
                    Err(e) => log(format!("health 暂不可用：{e}")),
                }
            }
            if let Ok(Some(status)) = sidecar.try_wait() {
                sidecar.finish();
                for msg in sidecar.drain() {
                    if let Message::Event(event) = msg {
                        if event.event == "error" {
                            last_error = event.error.clone();
                        }
                    }
                }
                log(format!("serve 提前退出 exit={:?}", status.code()));
                break Err(ServeFailure::Exited {
                    exit_code: status.code(),
                    error: last_error.clone(),
                });
            }
        };

        match outcome {
            Ok(verified) => {
                let estimate = health::estimated_data_id(&cfg.workspace_dir);
                log(format!(
                    "核对通过 port={} pid={} data_id={} 外壳估算{}",
                    verified.port,
                    verified.pid,
                    verified.data_id,
                    if estimate == verified.data_id {
                        "一致"
                    } else {
                        "不同（仅记录）"
                    }
                ));
                self.grant(verified.port);
                self.shared
                    .backend_port
                    .store(verified.port as u32, Ordering::SeqCst);
                self.sidecar = Some(sidecar);
                self.retry = None;
                let route = route
                    .filter(|r| r.starts_with('/'))
                    .unwrap_or_else(|| "/".into());
                let target = format!("{}{}", verified.origin, route);
                match (self.window(), Url::parse(&target)) {
                    (Some(window), Ok(url)) => {
                        let _ = window.navigate(url);
                    }
                    _ => log("无法导航到后端页面"),
                }
                self.set_stage(Stage::Ready);
            }
            Err(failure) => {
                let error = ui::serve_failure(&failure);
                let retry = if error.actions.contains(&ui::Action::Retry) {
                    Some(RetryTarget::Serve)
                } else {
                    None
                };
                self.fail(Stage::StartFailed, error, retry);
            }
        }
    }

    /// 给当前后端确切 origin 授权六个 desktop_* 命令（不含任何插件权限）。
    fn grant(&self, port: u16) {
        let mut cap = CapabilityBuilder::new(format!("backend-{port}"))
            .remote(format!("http://127.0.0.1:{port}/*"))
            .local(false)
            .window(MAIN);
        for p in DESKTOP_PERMISSIONS {
            cap = cap.permission(*p);
        }
        if let Err(e) = self.app.add_capability(cap) {
            log(format!("授权桥接命令失败：{e}"));
        }
    }

    // ---------- 运行中 ----------

    fn tick(&mut self) {
        let Some(sidecar) = self.sidecar.as_mut() else {
            return;
        };
        for msg in sidecar.drain() {
            match msg {
                Message::Ignored(reason) => log(format!("运行中忽略一行：{reason}")),
                Message::Fatal(reason) => log(format!("运行中协议错误：{reason}")),
                _ => {}
            }
        }
        if let Ok(Some(status)) = sidecar.try_wait() {
            log(format!("后台意外退出 exit={:?}", status.code()));
            sidecar.finish();
            self.sidecar = None;
            self.shared.backend_port.store(0, Ordering::SeqCst);
            self.show_loader();
            self.fail(
                Stage::Crashed,
                ui::crashed(status.code()),
                Some(RetryTarget::Serve),
            );
        }
    }

    fn stop_backend(&mut self) {
        if let Some(mut sidecar) = self.sidecar.take() {
            let started = Instant::now();
            let outcome = sidecar.shutdown(GRACE);
            log(format!(
                "后台已停止（{}，{} ms）",
                match outcome {
                    desktop_core::sidecar::Outcome::Exited(_) => "正常退出",
                    desktop_core::sidecar::Outcome::Killed(_) => "超时后结束进程树",
                },
                started.elapsed().as_millis()
            ));
        }
        self.shared.backend_port.store(0, Ordering::SeqCst);
    }

    fn restart(&mut self) {
        let route = self.current_route();
        log(format!("重启后台，回到 {route:?}"));
        self.show_loader();
        self.set_stage(Stage::Restarting);
        self.update(|s| s.message = Some("正在重新启动做题龙后台…".into()));
        self.stop_backend();
        match config::load(&self.shared.env.locator_file) {
            Load::Loaded(cfg) => {
                *self.shared.config.lock().unwrap() = Some(cfg.clone());
                self.run_serve(cfg, route);
            }
            _ => self.boot(),
        }
    }

    fn relocate(&mut self) {
        log("用户要求更改数据位置");
        let current = self.config();
        self.show_loader();
        self.set_stage(Stage::Stopping);
        self.update(|s| s.message = Some("正在关闭后台…".into()));
        self.stop_backend();
        self.previous = current.clone();
        let root = current
            .map(|c| c.data_root)
            .unwrap_or_else(|| self.shared.env.default_root.clone());
        self.enter_choose(
            &root,
            Some("请先退出做题龙，把整个数据文件夹复制到新位置，再在这里选择新位置。原位置的文件会保留，核对无误后可自行删除。".into()),
            true,
        );
    }

    fn exit_app(&mut self) {
        log("退出");
        self.set_stage(Stage::Stopping);
        self.update(|s| s.message = Some("正在保存并退出…".into()));
        self.show_loader();
        self.stop_backend();
        self.app.exit(0);
    }
}

/// prepare 成功：把缓冲的输出追加到工作区日志。
fn write_rings_to_workspace(sidecar: &Sidecar, workspace: &Path) {
    for (sink, name) in [
        (sidecar.stdout_sink(), logs::STDOUT_LOG),
        (sidecar.stderr_sink(), logs::STDERR_LOG),
    ] {
        if let (Ok(guard), Ok(mut file)) = (
            sink.lock(),
            RotatingFile::open(
                &workspace.join(name),
                logs::SERVER_LOG_MAX,
                logs::SERVER_LOG_KEEP,
            ),
        ) {
            if let Sink::Buffer(ring) = &*guard {
                let _ = logs::drain_ring_to(ring, &mut file);
            }
        }
    }
}

/// prepare 失败/取消：缓冲写到外壳日志目录，不在可能尚未发布的目标目录建文件。
fn dump_failed_prepare(sidecar: &Sidecar, shell_logs: &Path) {
    let path = shell_logs.join(format!("prepare-failed-{}.log", timefmt::utc_now_compact()));
    let Ok(mut file) = RotatingFile::open(&path, 8 * 1024 * 1024, 0) else {
        return;
    };
    for (sink, title) in [
        (sidecar.stdout_sink(), "== stdout =="),
        (sidecar.stderr_sink(), "== stderr =="),
    ] {
        let _ = file.write_line(title.as_bytes());
        if let Ok(guard) = sink.lock() {
            if let Sink::Buffer(ring) = &*guard {
                let _ = logs::drain_ring_to(ring, &mut file);
            }
        }
    }
    let _ = logs::prune_files(shell_logs, "prepare-failed-", 5);
    log(format!("prepare 输出已保存到 {}", path.display()));
}
