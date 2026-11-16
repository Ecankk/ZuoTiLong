//! 子进程环境：删掉全部 `MATHLENS_*`（数据/资源路径只走 CLI 参数），PATH 从注册表重组，
//! 其余变量（CODEX_HOME、USERPROFILE、TEMP…）原样继承。

use std::ffi::{OsStr, OsString};
use std::path::Path;

pub const CODEX_ENV: &str = "MATHLENS_CODEX_BIN";

fn key_is(key: &OsStr, name: &str) -> bool {
    key.to_string_lossy().eq_ignore_ascii_case(name)
}

fn is_mathlens(key: &OsStr) -> bool {
    key.to_string_lossy()
        .to_ascii_uppercase()
        .starts_with("MATHLENS_")
}

/// 生成完整子进程环境。`path` 为 `Some` 时替换 PATH（不区分大小写）。
pub fn child_env<I>(
    current: I,
    path: Option<OsString>,
    codex_bin: Option<&Path>,
) -> Vec<(OsString, OsString)>
where
    I: IntoIterator<Item = (OsString, OsString)>,
{
    let mut env: Vec<(OsString, OsString)> = current
        .into_iter()
        .filter(|(k, _)| !is_mathlens(k))
        .filter(|(k, _)| !key_is(k, "PYTHONUTF8") && !key_is(k, "PYTHONIOENCODING"))
        .filter(|(k, _)| path.is_none() || !key_is(k, "PATH"))
        .collect();
    if let Some(path) = path {
        env.push(("PATH".into(), path));
    }
    env.push(("PYTHONUTF8".into(), "1".into()));
    env.push(("PYTHONIOENCODING".into(), "utf-8".into()));
    if let Some(codex) = codex_bin {
        env.push((CODEX_ENV.into(), codex.as_os_str().to_owned()));
    }
    env
}

/// 从注册表读当前的系统 PATH + 用户 PATH 并展开，用户刚装完 Codex 也能找到。
/// 读不到时返回 `None`（调用方沿用当前进程的 PATH）。
#[cfg(windows)]
pub fn registry_path() -> Option<OsString> {
    use windows_sys::Win32::System::Registry::{HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE};
    let system = read_reg_string(
        HKEY_LOCAL_MACHINE,
        r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
        "Path",
    );
    let user = read_reg_string(HKEY_CURRENT_USER, "Environment", "Path");
    let parts: Vec<String> = [system, user]
        .into_iter()
        .flatten()
        .map(|s| expand(&s))
        .filter(|s| !s.trim().is_empty())
        .collect();
    if parts.is_empty() {
        None
    } else {
        Some(OsString::from(parts.join(";")))
    }
}

#[cfg(not(windows))]
pub fn registry_path() -> Option<OsString> {
    None
}

#[cfg(windows)]
fn wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(std::iter::once(0)).collect()
}

#[cfg(windows)]
fn read_reg_string(
    root: windows_sys::Win32::System::Registry::HKEY,
    subkey: &str,
    value: &str,
) -> Option<String> {
    use windows_sys::Win32::System::Registry::{
        RegGetValueW, RRF_NOEXPAND, RRF_RT_REG_EXPAND_SZ, RRF_RT_REG_SZ,
    };
    let subkey = wide(subkey);
    let value = wide(value);
    let flags = RRF_RT_REG_SZ | RRF_RT_REG_EXPAND_SZ | RRF_NOEXPAND;
    let mut size: u32 = 0;
    // SAFETY: 先查询所需字节数。
    let rc = unsafe {
        RegGetValueW(
            root,
            subkey.as_ptr(),
            value.as_ptr(),
            flags,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            &mut size,
        )
    };
    if rc != 0 || size == 0 {
        return None;
    }
    let mut buf = vec![0u16; (size as usize).div_ceil(2) + 1];
    let mut size2 = (buf.len() * 2) as u32;
    // SAFETY: 缓冲大小如实传入。
    let rc = unsafe {
        RegGetValueW(
            root,
            subkey.as_ptr(),
            value.as_ptr(),
            flags,
            std::ptr::null_mut(),
            buf.as_mut_ptr() as *mut _,
            &mut size2,
        )
    };
    if rc != 0 {
        return None;
    }
    let end = buf.iter().position(|&c| c == 0).unwrap_or(buf.len());
    Some(String::from_utf16_lossy(&buf[..end]))
}

#[cfg(windows)]
fn expand(s: &str) -> String {
    use windows_sys::Win32::System::Environment::ExpandEnvironmentStringsW;
    let src = wide(s);
    // SAFETY: 先查询长度再展开。
    let needed = unsafe { ExpandEnvironmentStringsW(src.as_ptr(), std::ptr::null_mut(), 0) };
    if needed == 0 {
        return s.to_string();
    }
    let mut buf = vec![0u16; needed as usize];
    let written = unsafe { ExpandEnvironmentStringsW(src.as_ptr(), buf.as_mut_ptr(), needed) };
    if written == 0 || written > needed {
        return s.to_string();
    }
    let end = buf.iter().position(|&c| c == 0).unwrap_or(buf.len());
    String::from_utf16_lossy(&buf[..end])
}

#[cfg(test)]
mod tests {
    use super::*;

    fn pairs(items: &[(&str, &str)]) -> Vec<(OsString, OsString)> {
        items
            .iter()
            .map(|(k, v)| (OsString::from(k), OsString::from(v)))
            .collect()
    }

    fn get<'a>(env: &'a [(OsString, OsString)], key: &str) -> Vec<&'a OsString> {
        env.iter()
            .filter(|(k, _)| k.to_string_lossy().eq_ignore_ascii_case(key))
            .map(|(_, v)| v)
            .collect()
    }

    #[test]
    fn strips_mathlens_and_sets_python_utf8() {
        let current = pairs(&[
            ("MATHLENS_DATA_DIR", r"F:\kaoyan\ZuoTiLongData"),
            ("mathlens_library_dir", r"F:\x"),
            ("MATHLENS_DEMO", "1"),
            ("MATHLENS_CODEX_BIN", r"C:\old\codex.exe"),
            ("CODEX_HOME", r"C:\Users\u\.codex"),
            ("Path", r"C:\old"),
            ("PYTHONUTF8", "0"),
        ]);
        let env = child_env(current, Some(r"C:\new;C:\codex".into()), None);
        assert!(env.iter().all(|(k, _)| !is_mathlens(k)));
        assert_eq!(get(&env, "PATH"), vec![&OsString::from(r"C:\new;C:\codex")]);
        assert_eq!(
            get(&env, "CODEX_HOME"),
            vec![&OsString::from(r"C:\Users\u\.codex")]
        );
        assert_eq!(get(&env, "PYTHONUTF8"), vec![&OsString::from("1")]);
        assert_eq!(
            get(&env, "PYTHONIOENCODING"),
            vec![&OsString::from("utf-8")]
        );
    }

    #[test]
    fn injects_only_the_configured_codex() {
        let env = child_env(
            pairs(&[("PATH", r"C:\keep")]),
            None,
            Some(Path::new(r"D:\工具 箱\codex.exe")),
        );
        assert_eq!(get(&env, "PATH"), vec![&OsString::from(r"C:\keep")]);
        assert_eq!(
            get(&env, CODEX_ENV),
            vec![&OsString::from(r"D:\工具 箱\codex.exe")]
        );
    }

    #[cfg(windows)]
    #[test]
    fn registry_path_is_readable() {
        let path = registry_path().expect("系统 PATH 应可读");
        assert!(path
            .to_string_lossy()
            .to_ascii_lowercase()
            .contains("windows"));
    }
}
