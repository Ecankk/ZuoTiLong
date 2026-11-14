// Release 构建不弹控制台窗口。
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    if let Err(error) = zuotilong_desktop::run() {
        show_fatal(&error);
        std::process::exit(1);
    }
}

/// 建窗失败（多半是 WebView2 运行时缺失或损坏）时用原生对话框说明，不白屏。
#[cfg(windows)]
fn show_fatal(error: &str) {
    use windows_sys::Win32::UI::WindowsAndMessaging::{MessageBoxW, MB_ICONERROR, MB_OK};
    let text = format!(
        "做题龙没能打开窗口。\n\n通常是电脑缺少或损坏了 Microsoft Edge WebView2 运行时。请从下面的地址安装后重新打开做题龙：\nhttps://go.microsoft.com/fwlink/p/?LinkId=2124703\n\n详细信息：{error}"
    );
    let wide = |s: &str| {
        s.encode_utf16()
            .chain(std::iter::once(0))
            .collect::<Vec<u16>>()
    };
    let (text, title) = (wide(&text), wide("做题龙"));
    // SAFETY: 两个参数都是以 NUL 结尾的 UTF-16 字符串。
    unsafe {
        MessageBoxW(
            std::ptr::null_mut(),
            text.as_ptr(),
            title.as_ptr(),
            MB_OK | MB_ICONERROR,
        );
    }
}

#[cfg(not(windows))]
fn show_fatal(error: &str) {
    eprintln!("{error}");
}
