//! Tauri 侧的 IPC 数据结构（前端契约）。
//!
//! 真正的同步逻辑全部委托给 `selfshare-core`；这里只保留 GUI 需要的 DTO，
//! 字段名与 Svelte 页面读取的一致，因此替换内部实现不动前端。

use serde::{Deserialize, Serialize};

/// 「添加同步文件夹」表单，对应 `commands::AddMountRequest`。
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MountConfig {
    pub name: String,
    pub local_path: String,
    pub server_url: String,
    pub vault_id: String,
    pub token: String,
}

/// `list_mounts` 的一项；`status` 取值为 idle | watching | syncing | error。
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MountInfo {
    pub name: String,
    pub local_path: String,
    pub server_url: String,
    pub vault_id: String,
    pub status: String,
}

/// 单次同步的状态快照。
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SyncStatus {
    pub mount_name: String,
    pub state: String,
    pub last_sync: Option<String>,
    pub files_synced: u64,
    pub bytes_synced: u64,
    pub errors: Vec<String>,
    pub progress: f64,
}

impl SyncStatus {
    pub fn idle(mount_name: &str) -> Self {
        Self {
            mount_name: mount_name.to_string(),
            state: "idle".to_string(),
            last_sync: None,
            files_synced: 0,
            bytes_synced: 0,
            errors: vec![],
            progress: 0.0,
        }
    }
}

/// 版本历史的一行（`get_history` 返回，`commands` 再映射成 HistoryEntry）。
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VersionEntry {
    pub path: String,
    pub hash: Option<String>,
    pub size: Option<u64>,
    pub rev: u64,
    pub time: String,
    pub origin: String,
    pub action: String,
}

/// 同步库统计（`get_stat` 返回，字段名与前端 VaultStat 一致）。
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Stat {
    pub files: u64,
    pub bytes: u64,
    pub versions: u64,
    pub blobs: u64,
    pub blob_bytes: u64,
    pub head_rev: u64,
}

/// GUI 设置，持久化到 `config_dir/settings.json`。
/// 与 v1 的行为对齐：同步间隔、P2P 开关、默认服务端地址都从这里读取。
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct Settings {
    pub default_server_url: String,
    pub sync_interval_secs: u64,
    pub enable_p2p: bool,
    pub auto_start: bool,
    pub theme: String,
    pub show_notifications: bool,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            default_server_url: "http://127.0.0.1:8484".to_string(),
            sync_interval_secs: 10,
            enable_p2p: false,
            auto_start: false,
            theme: "system".to_string(),
            show_notifications: true,
        }
    }
}

/// 在线 P2P 节点（来自中心服务端 `/peers`，由共享内核解析）。
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PeerEntry {
    pub peer_id: String,
    pub listen: String,
    pub host_id: String,
    pub blob_count: u64,
}
