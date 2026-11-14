//! 构建：只为下列命令生成 allow-* 权限（React 与加载页各自只拿到自己那一组），
//! 并在可用时注入 git 短哈希供“关于”页显示。

const COMMANDS: &[&str] = &[
    "boot_state",
    "boot_use_default",
    "boot_choose_folder",
    "boot_confirm_location",
    "boot_choose_location",
    "boot_cancel",
    "boot_retry",
    "boot_open_logs",
    "boot_quit",
    "desktop_info",
    "desktop_open_folder",
    "desktop_pick_codex",
    "desktop_save_codex",
    "desktop_restart_backend",
    "desktop_relocate",
];

fn main() {
    if let Ok(out) = std::process::Command::new("git")
        .args(["rev-parse", "--short", "HEAD"])
        .output()
    {
        if out.status.success() {
            let hash = String::from_utf8_lossy(&out.stdout).trim().to_string();
            if !hash.is_empty() {
                println!("cargo:rustc-env=ZUOTILONG_COMMIT={hash}");
            }
        }
    }
    println!("cargo:rerun-if-changed=../.git/HEAD");
    tauri_build::try_build(
        tauri_build::Attributes::new()
            .app_manifest(tauri_build::AppManifest::new().commands(COMMANDS)),
    )
    .expect("tauri build");
}
