//! 只读解析已有工作区的 workspace.json，得到它真实使用的 library 位置。
//!
//! 与 app/config.py 的 resolve_library_dir 同义：library 为绝对路径则直接用，相对路径
//! 按工作区目录解析。外壳绝不写这个文件（归后端 split 维护）。

use serde::Deserialize;
use std::fs;
use std::io;
use std::path::{Component, Path, PathBuf};

pub const FILE_NAME: &str = "workspace.json";

#[derive(Deserialize)]
struct Marker {
    library: Option<String>,
}

/// `Ok(None)`：没有 workspace.json；`Err`：存在但读不出 library。
pub fn library_of(workspace_dir: &Path) -> Result<Option<PathBuf>, String> {
    let path = workspace_dir.join(FILE_NAME);
    let text = match fs::read_to_string(&path) {
        Ok(text) => text,
        Err(e) if e.kind() == io::ErrorKind::NotFound => return Ok(None),
        Err(e) => return Err(format!("读取 {} 失败：{e}", path.display())),
    };
    let marker: Marker =
        serde_json::from_str(&text).map_err(|e| format!("{} 格式错误：{e}", path.display()))?;
    let library = marker
        .library
        .filter(|s| !s.trim().is_empty())
        .ok_or_else(|| format!("{} 没有 library 位置", path.display()))?;
    let candidate = PathBuf::from(library);
    let joined = if candidate.is_absolute() {
        candidate
    } else {
        workspace_dir.join(candidate)
    };
    Ok(Some(normalize(&joined)))
}

/// 词法规范化（去掉 `.`、折叠 `..`），不访问文件系统、不解析符号链接。
pub fn normalize(path: &Path) -> PathBuf {
    let mut out = PathBuf::new();
    for comp in path.components() {
        match comp {
            Component::CurDir => {}
            Component::ParentDir => {
                if !out.pop() {
                    out.push("..");
                }
            }
            other => out.push(other.as_os_str()),
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resolves_relative_and_absolute_library() {
        let dir = tempfile::tempdir().unwrap();
        let ws = dir.path().join("workspaces").join("default");
        fs::create_dir_all(&ws).unwrap();
        assert_eq!(library_of(&ws).unwrap(), None);

        fs::write(
            ws.join(FILE_NAME),
            r#"{"database":"learning.db","library":"../../library"}"#,
        )
        .unwrap();
        assert_eq!(library_of(&ws).unwrap(), Some(dir.path().join("library")));

        let abs = dir.path().join("别处 题库");
        fs::write(
            ws.join(FILE_NAME),
            serde_json::json!({"database":"learning.db","library": abs}).to_string(),
        )
        .unwrap();
        assert_eq!(library_of(&ws).unwrap(), Some(abs));

        fs::write(ws.join(FILE_NAME), r#"{"database":"learning.db"}"#).unwrap();
        assert!(library_of(&ws).is_err());
    }
}
