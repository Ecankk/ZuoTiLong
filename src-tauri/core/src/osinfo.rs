//! “关于”页显示的系统版本（RtlGetVersion 不受兼容性清单影响）。

#[cfg(windows)]
pub fn os_description() -> String {
    use std::mem::{size_of, zeroed};
    use windows_sys::Wdk::System::SystemServices::RtlGetVersion;
    use windows_sys::Win32::System::SystemInformation::OSVERSIONINFOW;

    // SAFETY: dwOSVersionInfoSize 预先设置，RtlGetVersion 总是成功。
    let mut info: OSVERSIONINFOW = unsafe { zeroed() };
    info.dwOSVersionInfoSize = size_of::<OSVERSIONINFOW>() as u32;
    unsafe { RtlGetVersion(&mut info) };
    let name = if info.dwMajorVersion == 10 && info.dwBuildNumber >= 22000 {
        "Windows 11"
    } else if info.dwMajorVersion == 10 {
        "Windows 10"
    } else {
        "Windows"
    };
    format!(
        "{name} ({}.{}.{})",
        info.dwMajorVersion, info.dwMinorVersion, info.dwBuildNumber
    )
}

#[cfg(not(windows))]
pub fn os_description() -> String {
    std::env::consts::OS.to_string()
}

#[cfg(test)]
mod tests {
    #[test]
    fn describes_windows() {
        let text = super::os_description();
        assert!(text.starts_with("Windows"), "{text}");
    }
}
