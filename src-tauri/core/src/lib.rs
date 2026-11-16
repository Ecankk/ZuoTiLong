//! 做题龙桌面外壳中与 Tauri 无关的部分。
//!
//! - [`config`]：本机定位文件 desktop.json（原子写）。
//! - [`paths`]：默认数据根、数据根检查、可写探测。
//! - [`workspace`]：只读解析已有 workspace.json 的 library 位置。
//! - [`protocol`]：sidecar stdout 的 `mathlens.desktop/v1` JSONL。
//! - [`sidecar`]：带 Job Object 的子进程启动、三路管道、优雅关闭与强制结束。
//! - [`job`]：Windows Job Object（KILL_ON_JOB_CLOSE）。
//! - [`logs`]：5 MiB × 2 历史轮转与 prepare 阶段内存缓冲。
//! - [`health`]：server.json 与 /api/health 的核对、最小 loopback HTTP 客户端。
//! - [`envpath`]：子进程环境清洗与注册表 PATH。
//! - [`nav`]：主窗口导航与新窗口决策。
//! - [`ui`]：退出码/错误码到加载页文案和操作的映射。
//! - [`codex`]：所选 codex.exe 的校验与固定参数版本探测。

pub mod codex;
pub mod config;
pub mod envpath;
pub mod health;
pub mod job;
pub mod logs;
pub mod nav;
pub mod nonce;
pub mod osinfo;
pub mod paths;
pub mod protocol;
pub mod sidecar;
pub mod timefmt;
pub mod ui;
pub mod workspace;

/// 外壳版本：与 app/version.py 的 VERSION 保持一致（app crate 有测试断言）。
pub const VERSION: &str = env!("CARGO_PKG_VERSION");
