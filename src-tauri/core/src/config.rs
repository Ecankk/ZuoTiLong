//! 本机定位文件 desktop.json：只记数据位置、Codex 路径和准备状态，不放凭据或业务数据。
//!
//! 位置固定为 `<LocalAppData>\ZuoTiLong\desktop.json`（见 [`crate::paths`]）。写入为
//! 同目录临时文件 → 落盘 → 原子替换；只在 prepare 成功后写入新位置。

use crate::{nonce, timefmt};
use serde::{Deserialize, Serialize};
use std::fs;
use std::io::{self, Write};
use std::path::{Path, PathBuf};

pub const SCHEMA: &str = "zuotilong.desktop/v1";
pub const FILE_NAME: &str = "desktop.json";

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq)]
pub struct Prepared {
    pub app_version: String,
    pub workspace_dir: PathBuf,
    pub at: String,
}

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq)]
pub struct DesktopConfig {
    pub schema: String,
    pub data_root: PathBuf,
    pub workspace_dir: PathBuf,
    pub library_dir: PathBuf,
    #[serde(default)]
    pub codex_bin: Option<PathBuf>,
    #[serde(default)]
    pub prepared: Option<Prepared>,
}

impl DesktopConfig {
    pub fn new(data_root: PathBuf, workspace_dir: PathBuf, library_dir: PathBuf) -> Self {
        Self {
            schema: SCHEMA.into(),
            data_root,
            workspace_dir,
            library_dir,
            codex_bin: None,
            prepared: None,
        }
    }

    /// 记录本版本已在该工作区完成一次 prepare。
    pub fn mark_prepared(&mut self, app_version: &str) {
        self.prepared = Some(Prepared {
            app_version: app_version.into(),
            workspace_dir: self.workspace_dir.clone(),
            at: timefmt::utc_now_iso(),
        });
    }

    /// 首次运行之后，只有版本变化、换了工作区或从未成功准备时才需要再跑 prepare。
    pub fn needs_prepare(&self, app_version: &str) -> bool {
        match &self.prepared {
            Some(p) => p.app_version != app_version || p.workspace_dir != self.workspace_dir,
            None => true,
        }
    }

    fn validate(&self) -> Result<(), String> {
        if self.schema != SCHEMA {
            return Err(format!("不认识的格式 {}", self.schema));
        }
        for (name, path) in [
            ("data_root", &self.data_root),
            ("workspace_dir", &self.workspace_dir),
            ("library_dir", &self.library_dir),
        ] {
            if !path.is_absolute() {
                return Err(format!("{name} 不是绝对路径"));
            }
        }
        if let Some(codex) = &self.codex_bin {
            if !codex.is_absolute() {
                return Err("codex_bin 不是绝对路径".into());
            }
        }
        Ok(())
    }
}

#[derive(Debug)]
// 只在启动时读一次，值很小；不为此装箱。
#[allow(clippy::large_enum_variant)]
pub enum Load {
    /// 首次运行：没有定位文件。
    Missing,
    Loaded(DesktopConfig),
    /// 文件存在但无法使用（损坏、未知版本）；调用方应隔离后让用户重新指认位置。
    Invalid(String),
}

pub fn load(path: &Path) -> Load {
    let text = match fs::read_to_string(path) {
        Ok(text) => text,
        Err(e) if e.kind() == io::ErrorKind::NotFound => return Load::Missing,
        Err(e) => return Load::Invalid(format!("读取失败：{e}")),
    };
    let cfg: DesktopConfig = match serde_json::from_str(&text) {
        Ok(cfg) => cfg,
        Err(e) => return Load::Invalid(format!("格式错误：{e}")),
    };
    match cfg.validate() {
        Ok(()) => Load::Loaded(cfg),
        Err(reason) => Load::Invalid(reason),
    }
}

/// 原子写：同目录临时文件 → sync → rename（Windows 上为 MoveFileExW REPLACE_EXISTING）。
pub fn save(path: &Path, cfg: &DesktopConfig) -> io::Result<()> {
    cfg.validate()
        .map_err(|e| io::Error::new(io::ErrorKind::InvalidInput, e))?;
    let dir = path
        .parent()
        .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "定位文件没有父目录"))?;
    fs::create_dir_all(dir)?;
    let tmp = dir.join(format!("{FILE_NAME}.tmp-{}", nonce::short_id()));
    let result = (|| {
        let mut file = fs::File::create(&tmp)?;
        file.write_all(serde_json::to_string_pretty(cfg)?.as_bytes())?;
        file.write_all(b"\n")?;
        file.sync_all()?;
        drop(file);
        fs::rename(&tmp, path)
    })();
    if result.is_err() {
        let _ = fs::remove_file(&tmp);
    }
    result
}

/// 把无法使用的定位文件改名保留，返回新名字。
pub fn quarantine(path: &Path) -> io::Result<PathBuf> {
    let target = path.with_file_name(format!("{FILE_NAME}.bad-{}", timefmt::utc_now_compact()));
    fs::rename(path, &target)?;
    Ok(target)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample(root: &Path) -> DesktopConfig {
        DesktopConfig::new(
            root.to_path_buf(),
            root.join("workspaces").join("default"),
            root.join("library"),
        )
    }

    #[test]
    fn missing_then_save_then_load_roundtrip() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("中文 目录").join(FILE_NAME);
        assert!(matches!(load(&path), Load::Missing));
        let mut cfg = sample(dir.path());
        cfg.codex_bin = Some(dir.path().join("codex.exe"));
        save(&path, &cfg).unwrap();
        match load(&path) {
            Load::Loaded(read) => assert_eq!(read, cfg),
            other => panic!("{other:?}"),
        }
        // 没有残留临时文件
        let leftovers: Vec<_> = fs::read_dir(path.parent().unwrap())
            .unwrap()
            .filter_map(|e| e.ok())
            .filter(|e| e.file_name().to_string_lossy().contains(".tmp-"))
            .collect();
        assert!(leftovers.is_empty());
    }

    #[test]
    fn invalid_files_are_reported_and_quarantined() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join(FILE_NAME);
        fs::write(&path, "{not json").unwrap();
        assert!(matches!(load(&path), Load::Invalid(_)));
        fs::write(
            &path,
            r#"{"schema":"zuotilong.desktop/v2","data_root":"C:\\a","workspace_dir":"C:\\a\\w","library_dir":"C:\\a\\l"}"#,
        )
        .unwrap();
        assert!(matches!(load(&path), Load::Invalid(_)));
        fs::write(
            &path,
            r#"{"schema":"zuotilong.desktop/v1","data_root":"relative","workspace_dir":"C:\\a\\w","library_dir":"C:\\a\\l"}"#,
        )
        .unwrap();
        assert!(matches!(load(&path), Load::Invalid(_)));
        let moved = quarantine(&path).unwrap();
        assert!(moved.exists() && !path.exists());
    }

    #[test]
    fn prepare_needed_only_when_version_or_workspace_changes() {
        let dir = tempfile::tempdir().unwrap();
        let mut cfg = sample(dir.path());
        assert!(cfg.needs_prepare("0.10.0"));
        cfg.mark_prepared("0.10.0");
        assert!(!cfg.needs_prepare("0.10.0"));
        assert!(cfg.needs_prepare("0.11.0"));
        cfg.workspace_dir = dir.path().join("other");
        assert!(cfg.needs_prepare("0.10.0"));
    }
}
