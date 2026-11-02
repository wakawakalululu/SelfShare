//! SelfShare 同步内核。
//!
//! 与 Python 版服务端协议完全一致（`/api/v/<vault>/{manifest,commit,blob,history,stat}`），
//! 因此 GUI 客户端可以与已验证的 Python CLI 客户端、甚至第三台主机混用同一同步库。
//!
//! 分层：
//! - [`client`]  HTTP 传输
//! - [`state`]   本地 base 快照（JSON，避免 SQLite 的 C 依赖）
//! - [`engine`]  三方合并与冲突副本
//! - [`ffi`]     稳定 C ABI，供 Flutter 通过 dart:ffi 调用
//! - [`watcher`] 后台自动同步线程

pub mod client;
pub mod engine;
pub mod ffi;
pub mod peer;
pub mod state;
pub mod util;
pub mod watcher;

pub use client::{Client, RemoteError};
pub use engine::{SyncOptions, SyncReport, Syncer};
pub use peer::PeerServer;
pub use state::LocalState;

/// 内核版本，GUI 里显示用。
pub const VERSION: &str = env!("CARGO_PKG_VERSION");
