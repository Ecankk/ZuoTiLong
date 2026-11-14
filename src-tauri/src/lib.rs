//! 做题龙 Windows 桌面外壳（Tauri 2）。见 docs/local/plans/DESKTOP-SHELL.md。

mod commands;
mod controller;
mod environment;
mod shelllog;

use controller::MAIN;
use desktop_core::nav::{self, Navigation, NewWindow};
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::Arc;
use tauri::webview::{NewWindowResponse, PageLoadEvent};
use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder, WindowEvent};

static VIEWER_SEQ: AtomicU32 = AtomicU32::new(0);

/// 外部网址交给系统浏览器。
fn open_external(url: &tauri::Url) {
    if let Err(e) = tauri_plugin_opener::open_url(url.as_str(), None::<&str>) {
        shelllog::log(format!("打开外部链接失败：{e}"));
    }
}

/// 同源内容的查看窗口：没有任何 capability（不能调用桥接命令），只能在同一 origin 内浏览。
fn open_viewer(app: &tauri::AppHandle, url: tauri::Url, port: u16) {
    let label = format!("viewer-{}", VIEWER_SEQ.fetch_add(1, Ordering::SeqCst));
    let built = WebviewWindowBuilder::new(app, label, WebviewUrl::External(url))
        .title("做题龙")
        .inner_size(900.0, 700.0)
        .disable_drag_drop_handler()
        .on_navigation(move |u| match nav::decide(u, Some(port)) {
            Navigation::Allow => nav::is_backend(u, Some(port)),
            Navigation::External => {
                open_external(u);
                false
            }
            Navigation::Deny => false,
        })
        .build();
    if let Err(e) = built {
        shelllog::log(format!("打开查看窗口失败：{e}"));
    }
}

pub fn run() -> Result<(), String> {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window(MAIN) {
                let _ = window.unminimize();
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            commands::boot_state,
            commands::boot_use_default,
            commands::boot_choose_folder,
            commands::boot_confirm_location,
            commands::boot_choose_location,
            commands::boot_cancel,
            commands::boot_retry,
            commands::boot_open_logs,
            commands::boot_quit,
            commands::desktop_info,
            commands::desktop_open_folder,
            commands::desktop_pick_codex,
            commands::desktop_save_codex,
            commands::desktop_restart_backend,
            commands::desktop_relocate,
        ])
        .setup(|app| {
            let env = environment::discover(app.handle())?;
            let _ = std::fs::create_dir_all(&env.shell_logs);
            shelllog::init(&env.shell_logs);
            shelllog::log(format!(
                "外壳启动 版本={} 资源={} 定位={}",
                desktop_core::VERSION,
                env.resource_dir.display(),
                env.locator_file.display()
            ));
            let shared = controller::start(app.handle().clone(), env);
            app.manage(shared.clone());

            let nav_shared = shared.clone();
            let popup_shared = shared.clone();
            let popup_app = app.handle().clone();
            let page_shared = shared.clone();
            let window = WebviewWindowBuilder::new(app, MAIN, WebviewUrl::App("index.html".into()))
                .title("做题龙")
                .inner_size(1280.0, 800.0)
                .min_inner_size(960.0, 640.0)
                .center()
                .disable_drag_drop_handler()
                .on_navigation(move |url| match nav::decide(url, nav_shared.port()) {
                    Navigation::Allow => true,
                    Navigation::External => {
                        open_external(url);
                        false
                    }
                    Navigation::Deny => {
                        shelllog::log(format!("拦截导航 {}", url.scheme()));
                        false
                    }
                })
                .on_new_window(move |url, _features| {
                    let port = popup_shared.port();
                    match nav::decide_new_window(&url, port) {
                        NewWindow::Viewer => {
                            let app = popup_app.clone();
                            let port = port.unwrap_or(0);
                            std::thread::spawn(move || open_viewer(&app, url, port));
                        }
                        NewWindow::External => open_external(&url),
                        NewWindow::Deny => shelllog::log("拦截新窗口"),
                    }
                    NewWindowResponse::Deny
                })
                .on_page_load(move |_window, payload| {
                    // 记下内嵌加载页的真实地址（建窗瞬间 url 还是 about:blank）
                    let url = payload.url();
                    if nav::is_loader(url) {
                        if let Ok(mut slot) = page_shared.loader_url.lock() {
                            slot.get_or_insert_with(|| url.clone());
                        }
                        if payload.event() == PageLoadEvent::Finished {
                            page_shared.mark_loader_loaded();
                        }
                    }
                })
                .build()?;
            if let Ok(mut slot) = shared.loader_url.lock() {
                if slot.is_none() {
                    *slot = window.url().ok().filter(nav::is_loader);
                }
            }
            let close_shared = shared.clone();
            window.on_window_event(move |event| {
                if let WindowEvent::CloseRequested { api, .. } = event {
                    if !close_shared.exiting.load(Ordering::SeqCst) {
                        api.prevent_close();
                        close_shared.request_exit();
                    }
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .map_err(|e| e.to_string())?;

    app.run(|handle, event| {
        if let RunEvent::ExitRequested { api, code, .. } = event {
            let shared = handle.state::<Arc<controller::Shared>>();
            // 用户触发（code=None）或系统注销：先优雅关闭后台，再由工作线程 exit(0)
            if code.is_none() && !shared.exiting.load(Ordering::SeqCst) {
                api.prevent_exit();
                shared.request_exit();
            }
        }
    });
    Ok(())
}

#[cfg(test)]
mod tests {
    /// tauri.conf.json、Cargo 包版本与 app/version.py 必须一致。
    #[test]
    fn versions_match_app_version_py() {
        let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"));
        let py = std::fs::read_to_string(root.join("../app/version.py")).unwrap();
        let py_version = py
            .lines()
            .find_map(|l| l.trim().strip_prefix("VERSION = "))
            .map(|v| v.trim().trim_matches('\'').trim_matches('"').to_string())
            .expect("app/version.py 里的 VERSION");
        let conf: serde_json::Value =
            serde_json::from_str(&std::fs::read_to_string(root.join("tauri.conf.json")).unwrap())
                .unwrap();
        assert_eq!(conf["version"], py_version);
        assert_eq!(env!("CARGO_PKG_VERSION"), py_version);
        assert_eq!(desktop_core::VERSION, py_version);
    }

    /// 加载页 capability 不得包含 desktop_* 或任何插件权限；React 那组只在运行时按 origin 授予。
    #[test]
    fn loader_capability_is_minimal() {
        let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"));
        let cap: serde_json::Value = serde_json::from_str(
            &std::fs::read_to_string(root.join("capabilities/loader.json")).unwrap(),
        )
        .unwrap();
        assert_eq!(cap["local"], true);
        assert!(cap.get("remote").is_none());
        for p in cap["permissions"].as_array().unwrap() {
            let p = p.as_str().unwrap();
            assert!(
                p.starts_with("allow-boot-")
                    || p == "core:event:allow-listen"
                    || p == "core:event:allow-unlisten",
                "{p}"
            );
        }
        for p in super::controller::DESKTOP_PERMISSIONS {
            assert!(p.starts_with("allow-desktop-"));
        }
    }
}
