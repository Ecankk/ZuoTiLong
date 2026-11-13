//! 主窗口的导航与新窗口决策（纯函数，便于单测）。
//!
//! - 内嵌加载页（tauri://localhost、http(s)://tauri.localhost）、about:blank、当前后端确切
//!   origin：允许。
//! - 其他公网 http/https：交系统浏览器。
//! - 本机其他地址（别的端口、localhost、::1）、file、javascript 等：拒绝。

use url::Url;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Navigation {
    Allow,
    External,
    Deny,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NewWindow {
    /// 同源内容（例如作答照片）：开一个没有任何权限的查看窗口。
    Viewer,
    External,
    Deny,
}

/// 内嵌加载页的地址（Windows 上为 http://tauri.localhost/…）。
pub fn is_loader(url: &Url) -> bool {
    match url.scheme() {
        "tauri" => true,
        "http" | "https" => url.host_str() == Some("tauri.localhost"),
        _ => false,
    }
}

/// 是否为当前后端的确切 origin（http://127.0.0.1:<port>）。
pub fn is_backend(url: &Url, backend_port: Option<u16>) -> bool {
    match backend_port {
        Some(port) => {
            url.scheme() == "http"
                && url.host_str() == Some("127.0.0.1")
                && url.port() == Some(port)
        }
        None => false,
    }
}

fn is_local_host(url: &Url) -> bool {
    match url.host_str() {
        Some(h) => {
            let h = h
                .trim_matches(|c| c == '[' || c == ']')
                .to_ascii_lowercase();
            h == "localhost"
                || h.ends_with(".localhost")
                || h == "::1"
                || h.starts_with("127.")
                || h == "0.0.0.0"
        }
        None => true,
    }
}

pub fn decide(url: &Url, backend_port: Option<u16>) -> Navigation {
    if is_loader(url) || is_backend(url, backend_port) {
        return Navigation::Allow;
    }
    if url.scheme() == "about" && url.path() == "blank" {
        return Navigation::Allow;
    }
    if matches!(url.scheme(), "http" | "https") && !is_local_host(url) {
        return Navigation::External;
    }
    Navigation::Deny
}

pub fn decide_new_window(url: &Url, backend_port: Option<u16>) -> NewWindow {
    if is_backend(url, backend_port) {
        return NewWindow::Viewer;
    }
    match decide(url, backend_port) {
        Navigation::External => NewWindow::External,
        _ => NewWindow::Deny,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn u(s: &str) -> Url {
        Url::parse(s).unwrap()
    }

    #[test]
    fn navigation_rules() {
        let port = Some(9318);
        assert_eq!(
            decide(&u("http://tauri.localhost/index.html"), port),
            Navigation::Allow
        );
        assert_eq!(
            decide(&u("tauri://localhost/index.html"), port),
            Navigation::Allow
        );
        assert_eq!(
            decide(&u("http://127.0.0.1:9318/settings?x=1"), port),
            Navigation::Allow
        );
        assert_eq!(decide(&u("about:blank"), port), Navigation::Allow);
        assert_eq!(
            decide(&u("https://learn.chatgpt.com/docs/cli"), port),
            Navigation::External
        );
        assert_eq!(decide(&u("http://127.0.0.1:4173/"), port), Navigation::Deny);
        assert_eq!(decide(&u("http://localhost:9318/"), port), Navigation::Deny);
        assert_eq!(decide(&u("http://[::1]:9318/"), port), Navigation::Deny);
        assert_eq!(
            decide(&u("https://127.0.0.1:9318/"), port),
            Navigation::Deny
        );
        assert_eq!(
            decide(&u("file:///C:/Windows/win.ini"), port),
            Navigation::Deny
        );
        assert_eq!(decide(&u("javascript:alert(1)"), port), Navigation::Deny);
        assert_eq!(decide(&u("mailto:a@b.c"), port), Navigation::Deny);
        // 后端尚未就绪时 127.0.0.1 一律拒绝
        assert_eq!(decide(&u("http://127.0.0.1:9318/"), None), Navigation::Deny);
    }

    #[test]
    fn new_window_rules() {
        let port = Some(9318);
        assert_eq!(
            decide_new_window(&u("http://127.0.0.1:9318/api/answer-images/a.jpg"), port),
            NewWindow::Viewer
        );
        assert_eq!(
            decide_new_window(&u("https://example.com/"), port),
            NewWindow::External
        );
        assert_eq!(
            decide_new_window(&u("http://127.0.0.1:1/"), port),
            NewWindow::Deny
        );
        assert_eq!(
            decide_new_window(&u("http://tauri.localhost/"), port),
            NewWindow::Deny
        );
    }
}
