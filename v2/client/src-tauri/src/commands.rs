use serde::{Deserialize, Serialize};
use tauri::State;
use tokio::sync::Mutex;
use std::sync::Arc;

use crate::sync::{MountConfig, PeerEntry, Settings, SyncEngine, SyncStatus};

pub struct AppState {
    pub engine: Arc<Mutex<SyncEngine>>,
}

#[derive(Serialize)]
pub struct VersionInfo {
    pub version: String,
    pub name: String,
}

#[tauri::command]
pub fn get_version() -> VersionInfo {
    VersionInfo {
        version: env!("CARGO_PKG_VERSION").to_string(),
        name: "SelfShare".to_string(),
    }
}

#[derive(Deserialize)]
pub struct ProbeRequest {
    pub url: String,
}

#[derive(Serialize)]
pub struct ProbeResponse {
    pub ok: bool,
    pub service: String,
    pub version: String,
    pub vaults: u32,
}

#[tauri::command]
pub async fn probe_server(req: ProbeRequest) -> Result<ProbeResponse, String> {
    let client = crate::sync::SyncClient::new(&req.url, "");
    let resp = client.ping().await.map_err(|e| e.to_string())?;
    Ok(ProbeResponse {
        ok: resp.ok,
        service: resp.service,
        version: resp.version,
        vaults: resp.vaults,
    })
}

#[derive(Deserialize)]
pub struct PairRequest {
    pub url: String,
    pub code: String,
}

#[derive(Serialize)]
pub struct PairResponse {
    pub vault: String,
    pub token: String,
    pub note: String,
}

#[tauri::command]
pub async fn pair_with_code(req: PairRequest) -> Result<PairResponse, String> {
    let client = crate::sync::SyncClient::new(&req.url, "");
    let resp = client.pair(&req.code).await.map_err(|e| e.to_string())?;
    Ok(PairResponse {
        vault: resp.vault,
        token: resp.token,
        note: resp.note,
    })
}

#[derive(Deserialize)]
pub struct AddMountRequest {
    pub name: String,
    pub local_path: String,
    pub server_url: String,
    pub vault_id: String,
    pub token: String,
}

#[tauri::command]
pub async fn add_mount(state: State<'_, AppState>, req: AddMountRequest) -> Result<(), String> {
    let engine = state.engine.lock().await;
    let config = MountConfig {
        name: req.name,
        local_path: req.local_path,
        server_url: req.server_url,
        vault_id: req.vault_id,
        token: req.token,
    };
    engine.add_mount(config).await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn remove_mount(state: State<'_, AppState>, name: String) -> Result<(), String> {
    let engine = state.engine.lock().await;
    engine.remove_mount(&name).await.map_err(|e| e.to_string())
}

#[derive(Serialize)]
pub struct MountListEntry {
    pub name: String,
    pub local_path: String,
    pub server_url: String,
    pub vault_id: String,
    pub status: String,
}

#[tauri::command]
pub async fn list_mounts(state: State<'_, AppState>) -> Result<Vec<MountListEntry>, String> {
    let engine = state.engine.lock().await;
    let mounts = engine.list_mounts().await.map_err(|e| e.to_string())?;
    Ok(mounts
        .into_iter()
        .map(|m| MountListEntry {
            name: m.name,
            local_path: m.local_path,
            server_url: m.server_url,
            vault_id: m.vault_id,
            status: m.status,
        })
        .collect())
}

#[tauri::command]
pub async fn sync_mount(state: State<'_, AppState>, name: String) -> Result<SyncStatus, String> {
    let engine = state.engine.lock().await;
    engine.sync_once(&name).await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn get_sync_status(state: State<'_, AppState>, name: String) -> Result<SyncStatus, String> {
    let engine = state.engine.lock().await;
    engine.get_status(&name).await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn start_watching(state: State<'_, AppState>, name: String) -> Result<(), String> {
    let engine = state.engine.lock().await;
    engine.start_watch(&name).await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn stop_watching(state: State<'_, AppState>, name: String) -> Result<(), String> {
    let engine = state.engine.lock().await;
    engine.stop_watch(&name).await.map_err(|e| e.to_string())
}

#[derive(Deserialize)]
pub struct HistoryRequest {
    pub mount_name: String,
    pub path: Option<String>,
    pub limit: Option<u32>,
}

#[derive(Serialize)]
pub struct HistoryEntry {
    pub path: String,
    pub hash: Option<String>,
    pub size: Option<u64>,
    pub rev: u64,
    pub time: String,
    pub origin: String,
    pub action: String,
}

#[tauri::command]
pub async fn get_history(state: State<'_, AppState>, req: HistoryRequest) -> Result<Vec<HistoryEntry>, String> {
    let engine = state.engine.lock().await;
    let entries = engine
        .get_history(&req.mount_name, req.path.as_deref(), req.limit.unwrap_or(50))
        .await
        .map_err(|e| e.to_string())?;
    Ok(entries
        .into_iter()
        .map(|e| HistoryEntry {
            path: e.path,
            hash: e.hash,
            size: e.size,
            rev: e.rev,
            time: e.time,
            origin: e.origin,
            action: e.action,
        })
        .collect())
}

#[derive(Deserialize)]
pub struct RestoreRequest {
    pub mount_name: String,
    pub path: String,
    pub rev: u64,
}

#[tauri::command]
pub async fn restore_version(state: State<'_, AppState>, req: RestoreRequest) -> Result<(), String> {
    let engine = state.engine.lock().await;
    engine
        .restore_version(&req.mount_name, &req.path, req.rev)
        .await
        .map_err(|e| e.to_string())
}

#[derive(Serialize)]
pub struct VaultStat {
    pub files: u64,
    pub bytes: u64,
    pub versions: u64,
    pub blobs: u64,
    pub blob_bytes: u64,
    pub head_rev: u64,
}

#[tauri::command]
pub async fn get_vault_stat(state: State<'_, AppState>, mount_name: String) -> Result<VaultStat, String> {
    let engine = state.engine.lock().await;
    let stat = engine.get_stat(&mount_name).await.map_err(|e| e.to_string())?;
    Ok(VaultStat {
        files: stat.files,
        bytes: stat.bytes,
        versions: stat.versions,
        blobs: stat.blobs,
        blob_bytes: stat.blob_bytes,
        head_rev: stat.head_rev,
    })
}

// ---- 设置、托盘控制与在线节点 ---- //

#[tauri::command]
pub async fn get_settings(state: State<'_, AppState>) -> Result<Settings, String> {
    let engine = state.engine.lock().await;
    Ok(engine.load_settings())
}

#[tauri::command]
pub async fn save_settings(state: State<'_, AppState>, settings: Settings) -> Result<(), String> {
    let engine = state.engine.lock().await;
    engine.save_settings(&settings)
}

#[tauri::command]
pub async fn pause_sync_all(state: State<'_, AppState>) -> Result<(), String> {
    let engine = state.engine.lock().await;
    engine.pause_all().await
}

#[tauri::command]
pub async fn resume_sync_all(state: State<'_, AppState>) -> Result<(), String> {
    let engine = state.engine.lock().await;
    engine.resume_all().await
}

#[tauri::command]
pub async fn is_sync_paused(state: State<'_, AppState>) -> Result<bool, String> {
    let engine = state.engine.lock().await;
    Ok(engine.is_paused())
}

/// 托盘「立即同步全部」。
#[tauri::command]
pub async fn sync_all_mounts(state: State<'_, AppState>) -> Result<Vec<SyncStatus>, String> {
    let engine = state.engine.lock().await;
    Ok(engine.sync_all().await)
}

/// 在线 P2P 节点（参考 syncthingtray 的设备列表）。
#[tauri::command]
pub async fn list_peers(
    state: State<'_, AppState>,
    mount_name: String,
) -> Result<Vec<PeerEntry>, String> {
    let engine = state.engine.lock().await;
    engine.list_peers(&mount_name).await
}
