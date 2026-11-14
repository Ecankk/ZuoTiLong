//! 假 sidecar：按 DESKTOP-SIDECAR.md 的 CLI、stdout `mathlens.desktop/v1` JSONL、stdin
//! shutdown/EOF、退出码与 server.json/health 实现，输出与 A 交付的真实样例对齐。
//! 只用于外壳开发与测试，不随安装包发布。
//!
//! 场景由环境变量 `FAKE_SIDECAR_SCENARIO`（逗号分隔）选择：
//! ok、slow_copy、seed_hash_mismatch、disk_full、library_busy、init_fail_after_publish、
//! hang_no_events、ignore_shutdown、crash_after_ready、bad_nonce、wrong_pid_server_json、
//! version_mismatch、hang_serve、spawn_grandchild、stderr_flood、busy_task、slow_start、
//! prepare_crash、workspace_incomplete。
//!
//! 另有两个测试辅助模式：`--grandchild <秒>`（只睡眠）与 `--job-holder <workspace> <resources>`
//! （像外壳一样用 Job 启动一个 serve，打印子进程 pid 后一直等待，供“外壳被强杀”测试）。

use serde_json::{json, Value};
use std::collections::HashSet;
use std::io::{BufRead, Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::exit;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

const PROTOCOL: &str = "mathlens.desktop/v1";

struct Args {
    mode: Mode,
    resource_root: Option<PathBuf>,
    data_dir: Option<PathBuf>,
    library_dir: Option<PathBuf>,
    nonce: Option<String>,
    host: String,
    port: u16,
}

#[derive(PartialEq, Clone, Copy)]
enum Mode {
    Prepare,
    Serve,
}

struct Ctx {
    op: &'static str,
    nonce: Option<String>,
    seq: AtomicU64,
    out: Mutex<std::io::Stdout>,
    scenarios: HashSet<String>,
    stop: Arc<AtomicBool>,
}

impl Ctx {
    fn has(&self, s: &str) -> bool {
        self.scenarios.contains(s)
    }

    fn emit(&self, event: &str, phase: &str, status: &str, extra: Value) {
        let seq = self.seq.fetch_add(1, Ordering::SeqCst) + 1;
        let mut line = json!({
            "protocol": PROTOCOL,
            "event": event,
            "operation": self.op,
            "seq": seq,
            "nonce": self.nonce,
            "pid": std::process::id(),
            "phase": phase,
            "status": status,
        });
        if let (Some(obj), Value::Object(more)) = (line.as_object_mut(), extra) {
            obj.extend(more);
        }
        let mut out = self.out.lock().unwrap();
        let _ = writeln!(out, "{line}");
        let _ = out.flush();
    }

    fn progress(&self, phase: &str, message: &str, progress: Option<(u64, u64)>) {
        let progress = progress.map(|(c, t)| json!({"unit": "bytes", "completed": c, "total": t}));
        self.emit(
            "progress",
            phase,
            "running",
            json!({"message": message, "progress": progress}),
        );
    }

    fn fail(&self, phase: &str, code: &str, message: &str, exit_code: i32, published: bool) -> ! {
        self.emit(
            "error",
            phase,
            "failed",
            json!({
                "error": {"code": code, "message": message, "retryable": exit_code == 13 || exit_code == 20},
                "library_published": published,
                "workspace_ready": false,
            }),
        );
        exit(exit_code)
    }

    fn stopped(&self) -> bool {
        self.stop.load(Ordering::SeqCst)
    }

    /// 等待 `d`，期间若收到关闭则返回 true。
    fn sleep_or_stop(&self, d: Duration) -> bool {
        let deadline = Instant::now() + d;
        while Instant::now() < deadline {
            if self.stopped() {
                return true;
            }
            thread::sleep(Duration::from_millis(20));
        }
        self.stopped()
    }
}

fn parse_args() -> Result<Args, String> {
    let mut mode = None;
    let mut a = Args {
        mode: Mode::Serve,
        resource_root: None,
        data_dir: None,
        library_dir: None,
        nonce: None,
        host: "127.0.0.1".into(),
        port: 0,
    };
    let mut it = std::env::args().skip(1);
    while let Some(arg) = it.next() {
        let mut value = || it.next().ok_or_else(|| format!("{arg} 缺少值"));
        match arg.as_str() {
            "--prepare-desktop" => mode = Some(Mode::Prepare),
            "--desktop" => mode = Some(Mode::Serve),
            "--resource-root" => a.resource_root = Some(PathBuf::from(value()?)),
            "--data-dir" => a.data_dir = Some(PathBuf::from(value()?)),
            "--library-dir" => a.library_dir = Some(PathBuf::from(value()?)),
            "--dist-dir" => {
                value()?;
            }
            "--launch-nonce" => a.nonce = Some(value()?),
            "--host" => a.host = value()?,
            "--port" => a.port = value()?.parse().map_err(|_| "端口不合法".to_string())?,
            other => return Err(format!("不认识的参数 {other}")),
        }
    }
    a.mode = mode.ok_or("缺少 --desktop 或 --prepare-desktop")?;
    Ok(a)
}

fn main() {
    let raw: Vec<String> = std::env::args().collect();
    if raw.get(1).map(String::as_str) == Some("--grandchild") {
        let secs = raw.get(2).and_then(|s| s.parse().ok()).unwrap_or(600);
        thread::sleep(Duration::from_secs(secs));
        return;
    }
    if raw.get(1).map(String::as_str) == Some("--job-holder") {
        job_holder(&raw[2..]);
        return;
    }
    let scenarios: HashSet<String> = std::env::var("FAKE_SIDECAR_SCENARIO")
        .unwrap_or_default()
        .split(',')
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .collect();
    let args = match parse_args() {
        Ok(a) => a,
        Err(message) => {
            let ctx = Ctx {
                op: "prepare",
                nonce: None,
                seq: AtomicU64::new(0),
                out: Mutex::new(std::io::stdout()),
                scenarios,
                stop: Arc::new(AtomicBool::new(false)),
            };
            ctx.fail("validate_config", "invalid_path", &message, 2, false);
        }
    };
    let ctx = Arc::new(Ctx {
        op: if args.mode == Mode::Prepare {
            "prepare"
        } else {
            "serve"
        },
        nonce: args.nonce.clone(),
        seq: AtomicU64::new(0),
        out: Mutex::new(std::io::stdout()),
        scenarios,
        stop: Arc::new(AtomicBool::new(false)),
    });
    let nonce_ok = args
        .nonce
        .as_deref()
        .map(desktop_core::nonce::is_launch_nonce)
        .unwrap_or(false);
    let (Some(resources), Some(data), Some(library), true) = (
        args.resource_root.clone(),
        args.data_dir.clone(),
        args.library_dir.clone(),
        nonce_ok,
    ) else {
        ctx.fail(
            "validate_config",
            "invalid_path",
            "缺少桌面模式必需的参数",
            2,
            false,
        );
    };
    for p in [&resources, &data, &library] {
        if !p.is_absolute() {
            ctx.fail(
                "validate_config",
                "invalid_path",
                "路径必须是绝对路径",
                2,
                false,
            );
        }
    }
    if args.mode == Mode::Serve && (args.host != "127.0.0.1" || args.port != 0) {
        ctx.fail(
            "validate_config",
            "invalid_path",
            "桌面服务只监听 127.0.0.1:0",
            2,
            false,
        );
    }
    start_control(ctx.clone());
    match args.mode {
        Mode::Prepare => prepare(&ctx, &resources, &data, &library),
        Mode::Serve => serve(&ctx, &data),
    }
}

/// stdin：每行一个 JSON；合法 shutdown（nonce 相同）或 EOF 触发关闭。
fn start_control(ctx: Arc<Ctx>) {
    thread::spawn(move || {
        let stdin = std::io::stdin();
        let mut lock = stdin.lock();
        let mut line = String::new();
        loop {
            line.clear();
            match lock.read_line(&mut line) {
                Ok(0) | Err(_) => break,
                Ok(_) => {
                    if line.len() > 4096 {
                        eprintln!("control_invalid: line too long");
                        continue;
                    }
                    let v: Value = serde_json::from_str(line.trim()).unwrap_or(Value::Null);
                    if v["command"] == "shutdown" && v["nonce"].as_str() == ctx.nonce.as_deref() {
                        if !ctx.has("ignore_shutdown") {
                            ctx.stop.store(true, Ordering::SeqCst);
                        }
                    } else {
                        eprintln!("control_invalid: expected shutdown with current nonce");
                    }
                }
            }
        }
        if !ctx.has("ignore_shutdown") {
            ctx.stop.store(true, Ordering::SeqCst);
        }
    });
}

fn cancelled(ctx: &Ctx, phase: &str) -> ! {
    ctx.fail(phase, "cancelled", "已取消准备", 130, false)
}

fn prepare(ctx: &Ctx, resources: &Path, data: &Path, library: &Path) {
    ctx.progress("validate_config", "正在检查数据位置", None);
    if ctx.has("prepare_crash") {
        eprintln!("模拟崩溃");
        exit(3);
    }
    if ctx.has("hang_no_events") {
        while !ctx.sleep_or_stop(Duration::from_secs(1)) {}
        cancelled(ctx, "validate_config");
    }
    if ctx.has("library_busy") {
        ctx.fail(
            "validate_config",
            "library_busy",
            "另一个准备过程正在使用这份数据",
            13,
            false,
        );
    }
    if ctx.sleep_or_stop(Duration::from_millis(50)) {
        cancelled(ctx, "validate_config");
    }
    ctx.progress("inspect_existing", "正在检查已有本地题库", None);
    let reuse = library.join("library.db").exists();
    if ctx.has("workspace_incomplete") {
        ctx.fail(
            "inspect_existing",
            "workspace_incomplete",
            "已有数据不完整",
            12,
            false,
        );
    }
    if !reuse {
        ctx.progress("validate_seed", "正在检查发行题库", None);
        if ctx.has("disk_full") {
            ctx.fail("validate_seed", "disk_full", "可用空间不足", 10, false);
        }
        let total: u64 = 385_100;
        ctx.progress("validate_seed", "正在校验本地题库", Some((total, total)));
        ctx.progress("copy_seed", "正在准备本地题库", None);
        let steps = if ctx.has("slow_copy") { 40 } else { 2 };
        for i in 1..=steps {
            if ctx.sleep_or_stop(Duration::from_millis(if steps > 2 { 100 } else { 10 })) {
                cancelled(ctx, "copy_seed");
            }
            ctx.progress(
                "copy_seed",
                "正在准备本地题库",
                Some((total * i / steps, total)),
            );
        }
        ctx.progress("verify_seed", "正在校验复制的题库", None);
        if ctx.has("seed_hash_mismatch") {
            ctx.fail(
                "verify_seed",
                "seed_hash_mismatch",
                "题库文件校验失败，请重新安装",
                11,
                false,
            );
        }
        ctx.progress("verify_seed", "正在校验本地题库", Some((total, total)));
        ctx.progress("publish_library", "正在保存已校验的题库", None);
        let _ = std::fs::create_dir_all(library);
        let _ = std::fs::write(library.join("library.db"), b"fake library");
        let _ = resources;
    } else {
        ctx.emit(
            "progress",
            "inspect_existing",
            "completed",
            json!({"message": "已有本地题库，直接使用", "reused_library": true, "progress": null}),
        );
    }
    ctx.progress("initialize_workspace", "正在准备个人工作区", None);
    if ctx.has("init_fail_after_publish") {
        ctx.fail(
            "initialize_workspace",
            "initialization_failed",
            "个人工作区没能建立",
            20,
            true,
        );
    }
    let _ = std::fs::create_dir_all(data);
    let marker = json!({"database": "learning.db", "library": library});
    let _ = std::fs::write(data.join("workspace.json"), marker.to_string());
    ctx.emit(
        "prepared",
        "complete",
        "completed",
        json!({
            "reused_library": reuse,
            "library_published": true,
            "workspace_ready": true,
            "data_dir": data,
            "library_dir": library,
            "library_id": "library-fake",
            "seed_release_id": "fake-1",
        }),
    );
    exit(0);
}

fn serve(ctx: &Arc<Ctx>, data: &Path) {
    let _ = std::fs::create_dir_all(data);
    // 供外壳测试核对：子进程实际看到的 MATHLENS_* 变量
    let seen: Vec<(String, String)> = std::env::vars()
        .filter(|(k, _)| k.to_ascii_uppercase().starts_with("MATHLENS_"))
        .collect();
    let _ = std::fs::write(data.join("env-check.json"), json!(seen).to_string());
    let version = if ctx.has("version_mismatch") {
        "0.0.1".to_string()
    } else {
        std::env::var("FAKE_SIDECAR_VERSION").unwrap_or_else(|_| desktop_core::VERSION.into())
    };
    let phases = [
        ("validate_config", "正在检查数据位置"),
        ("initialize_storage", "正在打开本地数据"),
        ("prepare_navigation", "正在准备题库索引"),
        ("recover_tasks", "正在核对已有任务状态"),
        ("start_services", "正在启动本地服务"),
    ];
    for (phase, message) in phases {
        ctx.progress(phase, message, None);
        let wait = if ctx.has("slow_start") { 1000 } else { 20 };
        if ctx.sleep_or_stop(Duration::from_millis(wait)) {
            finish_serve(ctx, data, None);
        }
    }
    if ctx.has("stderr_flood") {
        let line = "x".repeat(1000);
        let mut err = std::io::stderr();
        for i in 0..8_000 {
            let _ = writeln!(err, "{i:05} {line}");
        }
    }
    if ctx.has("spawn_grandchild") {
        if let Ok(me) = std::env::current_exe() {
            if let Ok(child) = std::process::Command::new(me)
                .args(["--grandchild", "600"])
                .stdin(std::process::Stdio::null())
                .stdout(std::process::Stdio::null())
                .stderr(std::process::Stdio::null())
                .spawn()
            {
                let _ = std::fs::write(data.join("grandchild.pid"), child.id().to_string());
            }
        }
    }
    if ctx.has("hang_serve") {
        while !ctx.sleep_or_stop(Duration::from_secs(1)) {}
        finish_serve(ctx, data, None);
    }
    let listener = TcpListener::bind("127.0.0.1:0").expect("bind");
    let port = listener.local_addr().unwrap().port();
    let pid = std::process::id();
    let nonce = ctx.nonce.clone().unwrap_or_default();
    let data_id = desktop_core::health::estimated_data_id(data);
    let reported_pid = if ctx.has("wrong_pid_server_json") {
        4
    } else {
        pid
    };
    let server = json!({
        "url": format!("http://127.0.0.1:{port}/"),
        "pid": reported_pid,
        "version": version,
        "data_id": data_id,
        "nonce": nonce,
    });
    let tmp = data.join("server.json.tmp");
    let _ = std::fs::write(&tmp, server.to_string());
    let _ = std::fs::rename(&tmp, data.join("server.json"));
    let health_nonce = if ctx.has("bad_nonce") {
        "0".repeat(64)
    } else {
        nonce.clone()
    };
    let health = json!({
        "ok": true, "app": "mathlens", "version": version, "data_id": data_id,
        "pid": pid, "nonce": health_nonce,
    });
    let busy = ctx.has("busy_task");
    thread::spawn(move || http_loop(listener, health, busy));
    ctx.emit(
        "address_published",
        "address_published",
        "completed",
        json!({"server": server}),
    );
    let started = Instant::now();
    loop {
        if ctx.sleep_or_stop(Duration::from_millis(50)) {
            break;
        }
        if ctx.has("crash_after_ready") && started.elapsed() > Duration::from_secs(2) {
            eprintln!("模拟后台崩溃");
            exit(3);
        }
    }
    finish_serve(ctx, data, Some(pid));
}

fn finish_serve(ctx: &Ctx, data: &Path, pid: Option<u32>) -> ! {
    ctx.progress("stopping", "正在关闭本地服务", None);
    if let Some(pid) = pid {
        let path = data.join("server.json");
        if let Ok(text) = std::fs::read_to_string(&path) {
            let v: Value = serde_json::from_str(&text).unwrap_or(Value::Null);
            if v["pid"].as_u64() == Some(pid as u64) && v["nonce"].as_str() == ctx.nonce.as_deref()
            {
                let _ = std::fs::remove_file(path);
            }
        }
    }
    ctx.emit("stopped", "stopped", "completed", json!({}));
    exit(0)
}

fn http_loop(listener: TcpListener, health: Value, busy: bool) {
    for stream in listener.incoming().flatten() {
        let health = health.clone();
        thread::spawn(move || {
            let _ = respond(stream, &health, busy);
        });
    }
}

fn respond(mut stream: TcpStream, health: &Value, busy: bool) -> std::io::Result<()> {
    stream.set_read_timeout(Some(Duration::from_secs(5)))?;
    // 读完整个请求头再回应，避免带着未读数据关闭连接触发 RST
    let mut buf = Vec::new();
    let mut chunk = [0u8; 4096];
    while !buf.windows(4).any(|w| w == b"\r\n\r\n") && buf.len() < 64 * 1024 {
        let n = stream.read(&mut chunk)?;
        if n == 0 {
            break;
        }
        buf.extend_from_slice(&chunk[..n]);
    }
    let request = String::from_utf8_lossy(&buf);
    let path = request
        .lines()
        .next()
        .and_then(|l| l.split_whitespace().nth(1))
        .unwrap_or("/")
        .to_string();
    let (ctype, body) = if path.starts_with("/api/health") {
        ("application/json", health.to_string())
    } else if path.starts_with("/api/tasks") {
        let active = if busy {
            json!({"id": "job-fake", "kind": "analyze_paper", "status": "running"})
        } else {
            Value::Null
        };
        (
            "application/json",
            json!({"items": [], "active": active, "availability": {"status": "unavailable", "reason": "not_installed", "message": "未安装学习服务，请先安装。"}}).to_string(),
        )
    } else if path.starts_with("/api/") {
        ("application/json", "{}".to_string())
    } else {
        ("text/html; charset=utf-8", TEST_PAGE.to_string())
    };
    let head = format!(
        "HTTP/1.1 200 OK\r\nContent-Type: {ctype}\r\nContent-Length: {}\r\nX-Content-Type-Options: nosniff\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n",
        body.len()
    );
    stream.write_all(head.as_bytes())?;
    stream.write_all(body.as_bytes())?;
    stream.flush()
}

/// 外壳 Ready 后显示的测试页：验证桥接命令只在当前后端 origin 可用。
const TEST_PAGE: &str = r#"<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>做题龙（假后台）</title>
<style>body{font:15px/1.6 system-ui,"Microsoft YaHei";margin:32px;color:#1f2a44}button{margin:4px 8px 4px 0;padding:6px 12px}
pre{background:#f4f5f8;padding:12px;border-radius:8px;white-space:pre-wrap;word-break:break-all}</style></head>
<body><h1>做题龙 · 假后台测试页</h1><p id="where"></p>
<p><button data-c="desktop_info">desktop_info</button><button data-c="desktop_open_folder" data-a='{"target":"workspace"}'>打开工作区</button>
<button data-c="desktop_pick_codex">选择 codex.exe</button><button data-c="desktop_restart_backend">重启后台</button>
<button data-c="desktop_relocate">更改数据位置</button><a href="https://learn.chatgpt.com/docs/cli">外部链接</a>
<a href="/api/health" target="_blank">同源新窗口</a></p><pre id="out">（结果显示在这里）</pre>
<script>
document.getElementById('where').textContent = location.href + ' · ' + ('__TAURI_INTERNALS__' in window ? '有桥接' : '无桥接');
const out = document.getElementById('out');
for (const b of document.querySelectorAll('button[data-c]')) b.onclick = async () => {
  try { const r = await window.__TAURI_INTERNALS__.invoke(b.dataset.c, JSON.parse(b.dataset.a || '{}'));
    out.textContent = JSON.stringify(r, null, 2); }
  catch (e) { out.textContent = '错误：' + JSON.stringify(e); }
};
</script></body></html>"#;

/// 测试辅助：像外壳一样把一个 serve 放进 Job，打印 `child=<pid>` 后一直等待。
fn job_holder(args: &[String]) {
    use desktop_core::logs::{shared, Sink};
    use desktop_core::sidecar::{Sidecar, SpawnSpec};
    let workspace = PathBuf::from(&args[0]);
    let resources = PathBuf::from(&args[1]);
    let nonce = desktop_core::nonce::launch_nonce();
    let me = std::env::current_exe().unwrap();
    let spec = SpawnSpec {
        program: me,
        args: vec![
            "--desktop".into(),
            "--resource-root".into(),
            resources.into(),
            "--data-dir".into(),
            workspace.clone().into(),
            "--library-dir".into(),
            workspace.join("library").into(),
            "--launch-nonce".into(),
            nonce.clone().into(),
            "--host".into(),
            "127.0.0.1".into(),
            "--port".into(),
            "0".into(),
        ],
        cwd: workspace.clone(),
        env: std::env::vars_os().collect(),
    };
    let sidecar = Sidecar::spawn(spec, &nonce, shared(Sink::Null), shared(Sink::Null)).unwrap();
    println!("child={}", sidecar.pid());
    let _ = std::io::stdout().flush();
    loop {
        thread::sleep(Duration::from_secs(60));
    }
}
