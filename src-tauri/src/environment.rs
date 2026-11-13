//! 外壳运行环境：定位文件位置、默认数据根、安装资源与后端程序。
//!
//! Release 构建只用 Windows 已知文件夹与 Tauri resource_dir，不读任何环境变量。
//! Debug 构建允许以下开发开关（编译期剔除，不进安装包）：
//! - `ZUOTILONG_DEV_LOCATOR_DIR`：定位文件、外壳日志与默认数据根都改到这里（放 TEMP）。
//! - `ZUOTILONG_DEV_RESOURCE_DIR`：含 `backend\` 与 `resources\` 的目录（假 sidecar 或合成资源）。
//! - `ZUOTILONG_DEV_SIDECAR` + `ZUOTILONG_DEV_PYTHONPATH`：用 `python.exe -m app` 跑源码后端。

use desktop_core::paths;
use std::ffi::OsString;
use std::path::PathBuf;
use tauri::{AppHandle, Manager};

#[derive(Clone, Debug)]
pub struct Backend {
    pub program: PathBuf,
    /// 固定前缀参数（源码后端为 `-m app`）。
    pub prefix: Vec<OsString>,
    /// 追加的环境变量（源码后端的 PYTHONPATH）。
    pub extra_env: Vec<(OsString, OsString)>,
}

#[derive(Clone, Debug)]
pub struct Environment {
    pub locator_file: PathBuf,
    pub shell_logs: PathBuf,
    pub default_root: PathBuf,
    pub local_app_data: PathBuf,
    pub resource_dir: PathBuf,
    pub resources_root: PathBuf,
    pub licenses_dir: PathBuf,
    pub backend: Backend,
    /// 数据根不能落在这些目录内（安装目录、资源目录）。
    pub forbidden: Vec<PathBuf>,
}

#[cfg(debug_assertions)]
fn dev(name: &str) -> Option<PathBuf> {
    std::env::var_os(name)
        .filter(|v| !v.is_empty())
        .map(PathBuf::from)
}

#[cfg(not(debug_assertions))]
fn dev(_name: &str) -> Option<PathBuf> {
    None
}

pub fn discover(app: &AppHandle) -> Result<Environment, String> {
    let local_app_data = paths::local_app_data().map_err(|e| e.to_string())?;
    let default_root =
        dev("ZUOTILONG_DEV_LOCATOR_DIR").unwrap_or_else(|| local_app_data.join(paths::APP_DIR));
    let locator_dir = default_root.clone();
    let resource_dir = match dev("ZUOTILONG_DEV_RESOURCE_DIR") {
        Some(dir) => dir,
        None => app.path().resource_dir().map_err(|e| e.to_string())?,
    };
    // 安装后 resource_dir 带扩展长度前缀：还原成普通路径再传给后端、做包含判断
    let resource_dir = paths::simplify(&resource_dir);
    let resources_root = resource_dir.join("resources");
    let backend = match dev("ZUOTILONG_DEV_SIDECAR") {
        Some(python) => Backend {
            program: python,
            prefix: vec!["-m".into(), "app".into()],
            extra_env: dev("ZUOTILONG_DEV_PYTHONPATH")
                .map(|p| vec![("PYTHONPATH".into(), p.into_os_string())])
                .unwrap_or_default(),
        },
        None => Backend {
            program: resource_dir.join("backend").join("mathlens-backend.exe"),
            prefix: vec![],
            extra_env: vec![],
        },
    };
    let mut forbidden = vec![resource_dir.clone()];
    if let Some(exe_dir) = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(paths::simplify))
    {
        forbidden.push(exe_dir);
    }
    Ok(Environment {
        locator_file: locator_dir.join(desktop_core::config::FILE_NAME),
        shell_logs: locator_dir.join(paths::SHELL_LOG_DIR),
        licenses_dir: resources_root.join("licenses"),
        default_root,
        local_app_data,
        resource_dir,
        resources_root,
        backend,
        forbidden,
    })
}
