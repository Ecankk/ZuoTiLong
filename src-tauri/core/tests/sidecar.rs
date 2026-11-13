//! 真实子进程 + Job Object 的集成测试（假 sidecar）。

#![cfg(windows)]

use desktop_core::health;
use desktop_core::job;
use desktop_core::logs::{self, shared, RotatingFile, Sink};
use desktop_core::nonce::launch_nonce;
use desktop_core::protocol::Event;
use desktop_core::sidecar::{Message, Outcome, Sidecar, SpawnSpec};
use std::ffi::OsString;
use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

const FAKE: &str = env!("CARGO_BIN_EXE_fake-sidecar");

struct Dirs {
    _tmp: tempfile::TempDir,
    resources: PathBuf,
    workspace: PathBuf,
    library: PathBuf,
}

fn dirs() -> Dirs {
    let tmp = tempfile::tempdir().unwrap();
    let base = tmp.path().join("用户 数据 & 测试");
    let resources = tmp.path().join("只读 资源");
    std::fs::create_dir_all(&resources).unwrap();
    Dirs {
        workspace: base.join("workspaces").join("default"),
        library: base.join("library"),
        resources,
        _tmp: tmp,
    }
}

fn spec(d: &Dirs, prepare: bool, nonce: &str, scenario: &str) -> SpawnSpec {
    let mut args: Vec<OsString> = vec![
        if prepare {
            "--prepare-desktop"
        } else {
            "--desktop"
        }
        .into(),
        "--resource-root".into(),
        d.resources.clone().into(),
        "--data-dir".into(),
        d.workspace.clone().into(),
        "--library-dir".into(),
        d.library.clone().into(),
        "--launch-nonce".into(),
        nonce.into(),
    ];
    if !prepare {
        args.extend([
            "--host".into(),
            "127.0.0.1".into(),
            "--port".into(),
            "0".into(),
        ]);
    }
    let mut env: Vec<(OsString, OsString)> = std::env::vars_os()
        .filter(|(k, _)| !k.to_string_lossy().starts_with("FAKE_SIDECAR"))
        .collect();
    env.push(("FAKE_SIDECAR_SCENARIO".into(), scenario.into()));
    std::fs::create_dir_all(d.workspace.parent().unwrap()).unwrap();
    SpawnSpec {
        program: PathBuf::from(FAKE),
        args,
        cwd: d.resources.clone(),
        env,
    }
}

fn spawn(d: &Dirs, prepare: bool, scenario: &str) -> (Sidecar, String) {
    let nonce = launch_nonce();
    let s = Sidecar::spawn(
        spec(d, prepare, &nonce, scenario),
        &nonce,
        shared(Sink::Buffer(logs::Ring::new(logs::RING_CAP))),
        shared(Sink::Buffer(logs::Ring::new(logs::RING_CAP))),
    )
    .unwrap();
    (s, nonce)
}

/// 收集事件直到满足条件或超时。
fn collect_until(
    s: &Sidecar,
    timeout: Duration,
    mut done: impl FnMut(&Event) -> bool,
) -> Vec<Event> {
    let deadline = Instant::now() + timeout;
    let mut events = Vec::new();
    while Instant::now() < deadline {
        match s.recv_timeout(Duration::from_millis(100)) {
            Some(Message::Event(e)) => {
                let stop = done(&e);
                events.push(*e);
                if stop {
                    break;
                }
            }
            Some(Message::StdoutClosed) => break,
            _ => {}
        }
    }
    events
}

fn wait_exit(s: &mut Sidecar, secs: u64) -> Option<i32> {
    s.wait_timeout(Duration::from_secs(secs))
        .unwrap()
        .and_then(|st| st.code())
}

#[test]
fn prepare_succeeds_with_ordered_phases() {
    let d = dirs();
    let (mut s, nonce) = spawn(&d, true, "ok");
    let events = collect_until(&s, Duration::from_secs(10), |e| e.event == "prepared");
    assert_eq!(wait_exit(&mut s, 10), Some(0));
    s.finish();
    let phases: Vec<&str> = events.iter().filter_map(|e| e.phase.as_deref()).collect();
    for want in [
        "validate_config",
        "inspect_existing",
        "copy_seed",
        "verify_seed",
        "publish_library",
        "initialize_workspace",
        "complete",
    ] {
        assert!(phases.contains(&want), "缺少阶段 {want}：{phases:?}");
    }
    let seqs: Vec<u64> = events.iter().filter_map(|e| e.seq).collect();
    assert!(seqs.windows(2).all(|w| w[1] == w[0] + 1), "{seqs:?}");
    assert!(events
        .iter()
        .all(|e| e.nonce.as_deref() == Some(nonce.as_str())));
    assert!(d.workspace.join("workspace.json").exists());
    // 第二次准备复用已有题库
    let (mut again, _) = spawn(&d, true, "ok");
    let events = collect_until(&again, Duration::from_secs(10), |e| e.event == "prepared");
    assert_eq!(wait_exit(&mut again, 10), Some(0));
    assert_eq!(events.last().unwrap().reused_library, Some(true));
}

#[test]
fn prepare_cancel_exits_130_and_seed_errors_carry_codes() {
    let d = dirs();
    let (mut s, _) = spawn(&d, true, "slow_copy");
    collect_until(&s, Duration::from_secs(10), |e| {
        e.phase.as_deref() == Some("copy_seed")
    });
    s.request_shutdown();
    let events = collect_until(&s, Duration::from_secs(10), |e| e.event == "error");
    assert_eq!(wait_exit(&mut s, 10), Some(130));
    assert_eq!(
        events.last().unwrap().error.as_ref().unwrap().code,
        "cancelled"
    );

    let d2 = dirs();
    let (mut bad, _) = spawn(&d2, true, "seed_hash_mismatch");
    let events = collect_until(&bad, Duration::from_secs(10), |e| e.event == "error");
    assert_eq!(wait_exit(&mut bad, 10), Some(11));
    assert_eq!(
        events.last().unwrap().error.as_ref().unwrap().code,
        "seed_hash_mismatch"
    );
    assert!(!d2.library.join("library.db").exists());
}

fn wait_address(s: &Sidecar) -> desktop_core::protocol::ServerInfo {
    collect_until(s, Duration::from_secs(10), |e| {
        e.event == "address_published"
    })
    .into_iter()
    .find_map(|e| e.server)
    .expect("address_published")
}

#[test]
fn serve_verifies_health_then_shuts_down_gracefully() {
    let d = dirs();
    let (mut s, nonce) = spawn(&d, false, "ok");
    let server = wait_address(&s);
    let port = health::loopback_port(&server.url).unwrap();
    let h = health::fetch_health(port, Duration::from_secs(5)).unwrap();
    let file = health::read_server_json(&d.workspace);
    let verified = health::verify(
        &server,
        file.as_ref(),
        &h,
        |p| s.owns_pid(p),
        &nonce,
        desktop_core::VERSION,
    )
    .unwrap();
    assert_eq!(verified.pid, s.pid());
    assert!(!health::tasks_active(port, Duration::from_secs(5)).unwrap());
    let started = Instant::now();
    assert!(
        matches!(s.shutdown(Duration::from_secs(10)), Outcome::Exited(st) if st.code() == Some(0))
    );
    assert!(started.elapsed() < Duration::from_secs(5));
    assert!(
        !d.workspace.join("server.json").exists(),
        "server.json 应由本进程清理"
    );
}

#[test]
fn mismatched_identity_is_rejected() {
    for (scenario, want) in [
        ("bad_nonce", "NonceMismatch"),
        ("wrong_pid_server_json", "PidMismatch"),
        ("version_mismatch", "VersionMismatch"),
    ] {
        let d = dirs();
        let (mut s, nonce) = spawn(&d, false, scenario);
        let server = wait_address(&s);
        let port = health::loopback_port(&server.url).unwrap();
        let h = health::fetch_health(port, Duration::from_secs(5)).unwrap();
        let file = health::read_server_json(&d.workspace);
        let err = health::verify(
            &server,
            file.as_ref(),
            &h,
            |p| s.owns_pid(p),
            &nonce,
            desktop_core::VERSION,
        )
        .unwrap_err();
        assert!(format!("{err:?}").starts_with(want), "{scenario}: {err:?}");
        s.shutdown(Duration::from_secs(5));
    }
}

#[test]
fn ignored_shutdown_is_killed_after_grace() {
    let d = dirs();
    let (mut s, _) = spawn(&d, false, "ignore_shutdown");
    wait_address(&s);
    let started = Instant::now();
    assert!(matches!(
        s.shutdown(Duration::from_millis(1500)),
        Outcome::Killed(_)
    ));
    let took = started.elapsed();
    assert!(
        took >= Duration::from_millis(1400) && took < Duration::from_secs(6),
        "{took:?}"
    );
    assert!(!job::process_alive(s.pid()));
}

#[test]
fn grandchildren_die_with_the_job() {
    let d = dirs();
    let (mut s, _) = spawn(&d, false, "spawn_grandchild");
    wait_address(&s);
    let pid_file = d.workspace.join("grandchild.pid");
    let grandchild: u32 = std::fs::read_to_string(&pid_file)
        .unwrap()
        .trim()
        .parse()
        .unwrap();
    assert!(job::process_alive(grandchild));
    assert!(s.owns_pid(grandchild), "孙进程应在同一个 Job 内");
    s.shutdown(Duration::from_secs(5));
    let deadline = Instant::now() + Duration::from_secs(5);
    while job::process_alive(grandchild) && Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(50));
    }
    assert!(!job::process_alive(grandchild), "关闭后孙进程仍在");
}

#[test]
fn killing_the_shell_takes_the_whole_tree() {
    let d = dirs();
    std::fs::create_dir_all(&d.workspace).unwrap();
    let mut holder = Command::new(FAKE)
        .arg("--job-holder")
        .arg(&d.workspace)
        .arg(&d.resources)
        .env("FAKE_SIDECAR_SCENARIO", "spawn_grandchild")
        .stdout(Stdio::piped())
        .stdin(Stdio::null())
        .spawn()
        .unwrap();
    let mut line = String::new();
    BufReader::new(holder.stdout.take().unwrap())
        .read_line(&mut line)
        .unwrap();
    let child: u32 = line.trim().strip_prefix("child=").unwrap().parse().unwrap();
    let pid_file = d.workspace.join("grandchild.pid");
    let deadline = Instant::now() + Duration::from_secs(10);
    while !pid_file.exists() && Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(50));
    }
    let grandchild: u32 = std::fs::read_to_string(&pid_file)
        .unwrap()
        .trim()
        .parse()
        .unwrap();
    assert!(job::process_alive(child) && job::process_alive(grandchild));
    holder.kill().unwrap(); // TerminateProcess：模拟外壳被强杀
    holder.wait().unwrap();
    let deadline = Instant::now() + Duration::from_secs(5);
    while (job::process_alive(child) || job::process_alive(grandchild)) && Instant::now() < deadline
    {
        std::thread::sleep(Duration::from_millis(50));
    }
    assert!(!job::process_alive(child), "外壳被强杀后 sidecar 仍在");
    assert!(!job::process_alive(grandchild), "外壳被强杀后孙进程仍在");
}

#[test]
fn stderr_flood_does_not_block_and_rotates() {
    let d = dirs();
    let logs_dir = d.workspace.clone();
    std::fs::create_dir_all(&logs_dir).unwrap();
    let out_path = logs_dir.join(logs::STDOUT_LOG);
    let err_path = logs_dir.join(logs::STDERR_LOG);
    let nonce = launch_nonce();
    let mut s = Sidecar::spawn(
        spec(&d, false, &nonce, "stderr_flood"),
        &nonce,
        shared(Sink::File(
            RotatingFile::open(&out_path, logs::SERVER_LOG_MAX, logs::SERVER_LOG_KEEP).unwrap(),
        )),
        shared(Sink::File(
            RotatingFile::open(&err_path, 1024 * 1024, logs::SERVER_LOG_KEEP).unwrap(),
        )),
    )
    .unwrap();
    // 8 MB stderr 之后仍能拿到地址
    let started = Instant::now();
    wait_address(&s);
    assert!(started.elapsed() < Duration::from_secs(20));
    s.shutdown(Duration::from_secs(5));
    let rotated: Vec<PathBuf> = [
        err_path.clone(),
        logs::numbered(&err_path, 1),
        logs::numbered(&err_path, 2),
    ]
    .into_iter()
    .filter(|p| p.exists())
    .collect();
    assert_eq!(rotated.len(), 3);
    assert!(!logs::numbered(&err_path, 3).exists());
    for p in &rotated {
        assert!(std::fs::metadata(p).unwrap().len() <= 1024 * 1024);
    }
    let stdout_log = std::fs::read_to_string(&out_path).unwrap();
    assert!(stdout_log.contains("address_published"));
}

#[test]
fn prepare_buffer_can_be_written_to_workspace_after_success() {
    let d = dirs();
    let (mut s, _) = spawn(&d, true, "ok");
    collect_until(&s, Duration::from_secs(10), |e| e.event == "prepared");
    wait_exit(&mut s, 10);
    s.finish();
    let mut file =
        RotatingFile::open(&d.workspace.join(logs::STDOUT_LOG), logs::SERVER_LOG_MAX, 2).unwrap();
    let sink = s.stdout_sink().lock().unwrap();
    let Sink::Buffer(ring) = &*sink else { panic!() };
    logs::drain_ring_to(ring, &mut file).unwrap();
    let text = std::fs::read_to_string(d.workspace.join(logs::STDOUT_LOG)).unwrap();
    assert!(text.contains("\"prepared\""));
    assert_eq!(text.lines().count(), ring.lines().count());
}
