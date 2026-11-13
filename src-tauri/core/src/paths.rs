//! 默认数据根、数据根检查与可写探测。
//!
//! 外壳不读 `LOCALAPPDATA`、`MATHLENS_DATA_DIR`、`MATHLENS_LIBRARY_DIR` 等环境变量：
//! 默认位置来自 Windows 已知文件夹 API。

use crate::{nonce, workspace};
use std::fs;
use std::io;
use std::path::{Path, PathBuf};

pub const APP_DIR: &str = "ZuoTiLong";
pub const SHELL_LOG_DIR: &str = "shell-logs";

/// 数据根下的固定布局。
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Layout {
    pub root: PathBuf,
    pub workspace: PathBuf,
    pub library: PathBuf,
}

impl Layout {
    /// 新位置：`root\workspaces\default` 与 `root\library`。
    pub fn fresh(root: &Path) -> Self {
        Self {
            root: root.to_path_buf(),
            workspace: root.join("workspaces").join("default"),
            library: root.join("library"),
        }
    }
}

/// `<LocalAppData>`（SHGetKnownFolderPath(FOLDERID_LocalAppData)）。
#[cfg(windows)]
pub fn local_app_data() -> io::Result<PathBuf> {
    use std::ffi::OsString;
    use std::os::windows::ffi::OsStringExt;
    use windows_sys::Win32::System::Com::CoTaskMemFree;
    use windows_sys::Win32::UI::Shell::{FOLDERID_LocalAppData, SHGetKnownFolderPath};

    let mut raw: *mut u16 = std::ptr::null_mut();
    // SAFETY: 输出指针由系统分配，成功或失败都要用 CoTaskMemFree 释放。
    let hr =
        unsafe { SHGetKnownFolderPath(&FOLDERID_LocalAppData, 0, std::ptr::null_mut(), &mut raw) };
    let result = if hr >= 0 && !raw.is_null() {
        let mut len = 0usize;
        // SAFETY: 系统返回以 NUL 结尾的 UTF-16 字符串。
        unsafe {
            while *raw.add(len) != 0 {
                len += 1;
            }
            Ok(PathBuf::from(OsString::from_wide(
                std::slice::from_raw_parts(raw, len),
            )))
        }
    } else {
        Err(io::Error::other(format!(
            "SHGetKnownFolderPath 失败 0x{hr:08x}"
        )))
    };
    // SAFETY: raw 来自 SHGetKnownFolderPath。
    unsafe { CoTaskMemFree(raw as *const _) };
    result
}

#[cfg(not(windows))]
pub fn local_app_data() -> io::Result<PathBuf> {
    Err(io::Error::other("仅支持 Windows"))
}

/// 默认数据根，同时也是定位文件和外壳日志所在目录：`<LocalAppData>\ZuoTiLong`。
pub fn default_root() -> io::Result<PathBuf> {
    Ok(local_app_data()?.join(APP_DIR))
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum RootKind {
    /// 不存在或为空（只有外壳自己的定位文件/日志也算空）。
    Fresh,
    /// 已有 workspaces\default\workspace.json，按它记录的 library 使用。
    Existing {
        workspace: PathBuf,
        library: PathBuf,
    },
    /// 有做题龙的目录但没有 workspace.json（例如上次准备中断）；交给 prepare 判断。
    Partial,
    /// 非空且不像做题龙数据。
    Foreign,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum RootError {
    NotAbsolute,
    /// 位于安装目录或只读资源目录内。
    InsideInstall,
    NotDirectory,
    Unreadable(String),
}

impl RootError {
    pub fn message(&self) -> String {
        match self {
            RootError::NotAbsolute => "请选择一个完整的文件夹位置。".into(),
            RootError::InsideInstall => {
                "不能把数据放在做题龙的安装文件夹里，请选择其他位置。".into()
            }
            RootError::NotDirectory => "这里不是文件夹，请重新选择。".into(),
            RootError::Unreadable(e) => format!("读不了这个文件夹：{e}"),
        }
    }
}

const OWN_ENTRIES: &[&str] = &[
    "library",
    "workspaces",
    "backups",
    crate::config::FILE_NAME,
    SHELL_LOG_DIR,
];

fn is_own_entry(name: &str) -> bool {
    OWN_ENTRIES.iter().any(|e| e.eq_ignore_ascii_case(name))
        || name.starts_with("desktop.json.")
        || name.starts_with("library.staging-")
}

/// 判断一个候选数据根，`forbidden` 为安装目录与资源目录。
pub fn inspect_root(root: &Path, forbidden: &[PathBuf]) -> Result<RootKind, RootError> {
    if !root.is_absolute() {
        return Err(RootError::NotAbsolute);
    }
    let lexical = workspace::normalize(root);
    if forbidden
        .iter()
        .any(|f| is_within(&lexical, &workspace::normalize(f)))
    {
        return Err(RootError::InsideInstall);
    }
    match fs::metadata(root) {
        Err(e) if e.kind() == io::ErrorKind::NotFound => return Ok(RootKind::Fresh),
        Err(e) => return Err(RootError::Unreadable(e.to_string())),
        Ok(meta) if !meta.is_dir() => return Err(RootError::NotDirectory),
        Ok(_) => {}
    }
    let fresh = Layout::fresh(root);
    match workspace::library_of(&fresh.workspace) {
        Ok(Some(library)) => {
            return Ok(RootKind::Existing {
                workspace: fresh.workspace,
                library,
            })
        }
        Ok(None) => {}
        Err(e) => return Err(RootError::Unreadable(e)),
    }
    let entries = fs::read_dir(root).map_err(|e| RootError::Unreadable(e.to_string()))?;
    let mut own = false;
    for entry in entries {
        let entry = entry.map_err(|e| RootError::Unreadable(e.to_string()))?;
        let name = entry.file_name().to_string_lossy().into_owned();
        if !is_own_entry(&name) {
            return Ok(RootKind::Foreign);
        }
        if name.eq_ignore_ascii_case("library") || name.eq_ignore_ascii_case("workspaces") {
            own = true;
        }
    }
    Ok(if own {
        RootKind::Partial
    } else {
        RootKind::Fresh
    })
}

/// 去掉 Windows 扩展长度前缀：`\\?\C:\x` → `C:\x`，`\\?\UNC\srv\x` → `\\srv\x`。
/// Tauri 的 resource_dir 在安装后会返回带前缀的路径；传给后端或做包含判断前先还原。
pub fn simplify(path: &Path) -> PathBuf {
    let text = path.to_string_lossy();
    if let Some(rest) = text.strip_prefix(r"\\?\UNC\") {
        return PathBuf::from(format!(r"\\{rest}"));
    }
    if let Some(rest) = text.strip_prefix(r"\\?\") {
        let bytes = rest.as_bytes();
        if bytes.len() >= 2 && bytes[0].is_ascii_alphabetic() && bytes[1] == b':' {
            return PathBuf::from(rest);
        }
    }
    path.to_path_buf()
}

/// `path` 是否等于或位于 `parent` 之内（不区分大小写的词法比较；先去掉扩展长度前缀）。
pub fn is_within(path: &Path, parent: &Path) -> bool {
    let (path, parent) = (simplify(path), simplify(parent));
    let mut p = path.components();
    for want in parent.components() {
        match p.next() {
            Some(got) => {
                if !got
                    .as_os_str()
                    .to_string_lossy()
                    .eq_ignore_ascii_case(&want.as_os_str().to_string_lossy())
                {
                    return false;
                }
            }
            None => return false,
        }
    }
    true
}

/// 创建目录并写/删一个临时文件，确认确实可写。
pub fn ensure_writable(root: &Path) -> io::Result<()> {
    fs::create_dir_all(root)?;
    let probe = root.join(format!(".zuotilong-write-test-{}", nonce::short_id()));
    fs::write(&probe, b"ok")?;
    fs::remove_file(&probe)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn classifies_roots() {
        let dir = tempfile::tempdir().unwrap();
        let none: Vec<PathBuf> = vec![];
        let root = dir.path().join("数据 根");
        assert_eq!(inspect_root(&root, &none), Ok(RootKind::Fresh));
        fs::create_dir_all(&root).unwrap();
        fs::write(root.join("desktop.json"), "{}").unwrap();
        assert_eq!(inspect_root(&root, &none), Ok(RootKind::Fresh));
        fs::create_dir_all(root.join("workspaces").join("default")).unwrap();
        assert_eq!(inspect_root(&root, &none), Ok(RootKind::Partial));
        fs::write(
            root.join("workspaces")
                .join("default")
                .join("workspace.json"),
            r#"{"database":"learning.db","library":"../../library"}"#,
        )
        .unwrap();
        assert_eq!(
            inspect_root(&root, &none),
            Ok(RootKind::Existing {
                workspace: root.join("workspaces").join("default"),
                library: root.join("library"),
            })
        );
        let other = dir.path().join("其他");
        fs::create_dir_all(&other).unwrap();
        fs::write(other.join("作业.docx"), "x").unwrap();
        assert_eq!(inspect_root(&other, &none), Ok(RootKind::Foreign));
        let file = dir.path().join("a.txt");
        fs::write(&file, "x").unwrap();
        assert_eq!(inspect_root(&file, &none), Err(RootError::NotDirectory));
        assert_eq!(
            inspect_root(Path::new("relative"), &none),
            Err(RootError::NotAbsolute)
        );
    }

    #[test]
    fn rejects_roots_inside_install_dir_case_insensitively() {
        let install = PathBuf::from(r"C:\Users\u\AppData\Local\Programs\做题龙");
        let forbidden = vec![install.clone()];
        assert_eq!(
            inspect_root(
                Path::new(r"c:\users\U\appdata\local\programs\做题龙\data"),
                &forbidden
            ),
            Err(RootError::InsideInstall)
        );
        assert_eq!(
            inspect_root(&install, &forbidden),
            Err(RootError::InsideInstall)
        );
        assert!(!is_within(
            Path::new(r"C:\Users\u\AppData\Local\Programs\做题龙2"),
            &install
        ));
    }

    #[test]
    fn strips_extended_length_prefix() {
        assert_eq!(
            simplify(Path::new(
                r"\\?\C:\Users\u\AppData\Local\Temp\zl-install\app"
            )),
            PathBuf::from(r"C:\Users\u\AppData\Local\Temp\zl-install\app")
        );
        assert_eq!(
            simplify(Path::new(r"\\?\UNC\server\share\x")),
            PathBuf::from(r"\\server\share\x")
        );
        assert_eq!(simplify(Path::new(r"C:\a")), PathBuf::from(r"C:\a"));
        // 带前缀的安装目录也能拦住
        let install = PathBuf::from(r"\\?\C:\Users\u\Programs\做题龙");
        assert_eq!(
            inspect_root(Path::new(r"C:\Users\u\Programs\做题龙\data"), &[install]),
            Err(RootError::InsideInstall)
        );
    }

    #[test]
    fn writable_probe_leaves_nothing() {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path().join("a").join("b");
        ensure_writable(&root).unwrap();
        assert_eq!(fs::read_dir(&root).unwrap().count(), 0);
    }

    #[cfg(windows)]
    #[test]
    fn local_app_data_is_absolute() {
        assert!(local_app_data().unwrap().is_absolute());
    }
}
