//! 多挂载点管理器：把 GUI 的 IPC 调用翻译成对 `selfshare-core` 内核的操作。
//!
//! 设计要点：
//! - 同步/网络是阻塞的（内核用 ureq），一律丢进 spawn_blocking，不阻塞 tokio 运行时；
//! - 注册表用 std::sync::Mutex，且从不在 .await 期间持有，因此没有「锁跨 await」问题；
//! - 后台自动同步复用内核里已测试的 watcher::spawn（轮询 + 去抖 + 定期巡检 + 可选 P2P）；
//! - 监视句柄放在独立的 Mutex 里，回调只更新状态表，避免 drop 句柄 join 线程时又去锁同一把锁。

use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use selfshare_core::client::Client;
use selfshare_core::engine::{SyncOptions, SyncReport, Syncer};
use selfshare_core::state::{LocalState, MountConfig as CoreMountConfig};
use selfshare_core::util;
use selfshare_core::watcher::{self, WatchHandle};

use super::state::{MountConfig, MountInfo, PeerEntry, Settings, Stat, SyncStatus, VersionEntry};

#[derive(Default)]
struct Registry {
    mounts: HashMap<String, MountConfig>,
    last: HashMap<String, SyncStatus>,
    syncing: HashSet<String>,
    paused: bool,
    /// 暂停前处于监控中的挂载，恢复时按原集合重启。
    resume_names: HashSet<String>,
}

pub struct SyncEngine {
    config_dir: PathBuf,
    reg: Arc<Mutex<Registry>>,
    watchers: Arc<Mutex<HashMap<String, WatchHandle>>>,
}

impl SyncEngine {
    pub fn new(config_dir: PathBuf) -> Self {
        let _ = std::fs::create_dir_all(&config_dir);
        let mut reg = Registry::default();
        let path = config_dir.join("registry.json");
        if let Ok(raw) = std::fs::read_to_string(&path) {
            if let Ok(list) = serde_json::from_str::<Vec<MountConfig>>(&raw) {
                for m in list {
                    reg.mounts.insert(m.name.clone(), m);
                }
            }
        }
        SyncEngine {
            config_dir,
            reg: Arc::new(Mutex::new(reg)),
            watchers: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    fn persist(&self) -> Result<(), String> {
        let snapshot: Vec<MountConfig> =
            self.reg.lock().unwrap().mounts.values().cloned().collect();
        let raw = serde_json::to_vec_pretty(&snapshot).map_err(|e| e.to_string())?;
        let path = self.config_dir.join("registry.json");
        // 与 save_settings 对齐：原子写同目录临时文件后 rename；落盘失败不再被吞，
        // 由 add_mount / remove_mount 的 `?` 传播到 IPC，避免前端误报成功。
        util::atomic_write(&path, &raw).map_err(|e| e.to_string())
    }

    fn mount(&self, name: &str) -> Result<MountConfig, String> {
        self.reg
            .lock()
            .unwrap()
            .mounts
            .get(name)
            .cloned()
            .ok_or_else(|| format!("未找到同步文件夹：{}", name))
    }

    // ---- 设置（持久化到 config_dir/settings.json） ---- //

    fn settings_path(&self) -> PathBuf {
        self.config_dir.join("settings.json")
    }

    pub fn load_settings(&self) -> Settings {
        std::fs::read_to_string(self.settings_path())
            .ok()
            .and_then(|raw| serde_json::from_str::<Settings>(&raw).ok())
            .unwrap_or_default()
    }

    pub fn save_settings(&self, s: &Settings) -> Result<(), String> {
        let raw = serde_json::to_vec_pretty(s).map_err(|e| e.to_string())?;
        let path = self.settings_path();
        util::atomic_write(&path, &raw).map_err(|e| e.to_string())
    }

    pub fn is_paused(&self) -> bool {
        self.reg.lock().unwrap().paused
    }

    /// 托盘状态摘要：(已暂停, 同步中数量, 监控中数量)。
    pub fn tray_state(&self) -> (bool, usize, usize) {
        let g = self.reg.lock().unwrap();
        let syncing = g.last.values().filter(|s| s.state == "syncing").count();
        let watching = self.watchers.lock().unwrap().len();
        (g.paused, syncing, watching)
    }

    /// 暂停全部监控；记录暂停前在跑的挂载，恢复时原样重启。
    ///
    /// 幂等：仅首次暂停（!paused）置位并记录 `resume_names`。
    /// 已暂停时直接返回，避免第二次调用时 `watchers` 已空、`names` 为空
    /// 而把首次记录的集合覆盖掉，导致 `resume_all` 无 watcher 可重启。
    pub async fn pause_all(&self) -> Result<(), String> {
        let (names, handles): (Vec<String>, Vec<WatchHandle>) = {
            let mut w = self.watchers.lock().unwrap();
            let names: Vec<String> = w.keys().cloned().collect();
            let handles = names.iter().filter_map(|n| w.remove(n)).collect();
            (names, handles)
        };
        drop(handles); // 锁外 join，避免与回调争锁
        let mut g = self.reg.lock().unwrap();
        if g.paused {
            return Ok(()); // 保留首次记录的 resume_names，不覆盖为空集合
        }
        g.paused = true;
        g.resume_names = names.iter().cloned().collect();
        for n in &names {
            if let Some(s) = g.last.get_mut(n) {
                s.state = "paused".to_string();
            }
        }
        Ok(())
    }

    pub async fn resume_all(&self) -> Result<(), String> {
        let names: Vec<String> = {
            let mut g = self.reg.lock().unwrap();
            g.paused = false;
            g.resume_names.drain().collect()
        };
        for n in &names {
            let _ = self.start_watch(n).await;
        }
        Ok(())
    }

    /// 在线 P2P 节点列表，复用共享内核的 `/peers` 解析（含 Bearer 令牌）。
    pub async fn list_peers(&self, name: &str) -> Result<Vec<PeerEntry>, String> {
        let m = self.mount(name)?;
        let (url, vault, token) = (m.server_url, m.vault_id, m.token);
        let out = tokio::task::spawn_blocking(move || -> Result<Vec<PeerEntry>, String> {
            let peers = Client::new(&url, &vault, &token)
                .peers(None)
                .map_err(|e| e.to_string())?;
            Ok(peers
                .into_iter()
                .map(|p| PeerEntry {
                    peer_id: p.peer_id,
                    listen: p.listen,
                    host_id: p.host_id,
                    blob_count: p.blob_count.max(0) as u64,
                })
                .collect())
        })
        .await
        .map_err(|e| e.to_string())??;
        Ok(out)
    }

    // ---- 挂载管理 ---- //

    pub async fn add_mount(&self, m: MountConfig) -> Result<(), String> {
        let folder = PathBuf::from(&m.local_path);
        let ccfg = CoreMountConfig {
            url: m.server_url.clone(),
            vault: m.vault_id.clone(),
            token: m.token.clone(),
            folder: m.local_path.clone(),
            host_id: util::host_id(),
            created: util::now_stamp(),
        };
        tokio::task::spawn_blocking(move || LocalState::init_mount(&folder, ccfg).map(|_| ()))
            .await
            .map_err(|e| e.to_string())??;

        self.reg.lock().unwrap().mounts.insert(m.name.clone(), m);
        self.persist()?;
        Ok(())
    }

    pub async fn remove_mount(&self, name: &str) -> Result<(), String> {
        // 先取出并释放句柄（在锁外 join 线程），再从注册表删除。
        let handle = self.watchers.lock().unwrap().remove(name);
        drop(handle);
        {
            let mut g = self.reg.lock().unwrap();
            g.mounts.remove(name);
            g.last.remove(name);
            g.syncing.remove(name);
        }
        self.persist()?;
        Ok(())
    }

    pub async fn list_mounts(&self) -> Result<Vec<MountInfo>, String> {
        let g = self.reg.lock().unwrap();
        let w = self.watchers.lock().unwrap();
        let mut out: Vec<MountInfo> = g
            .mounts
            .values()
            .map(|m| {
                let running = w.get(&m.name).map(|h| h.is_running()).unwrap_or(false);
                let status = if g.paused {
                    "paused"
                } else if running {
                    "watching"
                } else if g.syncing.contains(&m.name) {
                    "syncing"
                } else {
                    "idle"
                }
                .to_string();
                MountInfo {
                    name: m.name.clone(),
                    local_path: m.local_path.clone(),
                    server_url: m.server_url.clone(),
                    vault_id: m.vault_id.clone(),
                    status,
                }
            })
            .collect();
        drop(w);
        drop(g);
        out.sort_by(|a, b| a.name.cmp(&b.name));
        Ok(out)
    }

    // ---- 同步 ---- //

    async fn run_sync(folder: PathBuf) -> Result<SyncReport, String> {
        tokio::task::spawn_blocking(move || {
            let state = LocalState::open(&folder).map_err(|e| e.to_string())?;
            let cfg = state.config().clone();
            let client = Client::new(&cfg.url, &cfg.vault, &cfg.token);
            let options = SyncOptions::load(state.folder());
            let mut syncer = Syncer::with_options(client, state, options);
            syncer.sync()
        })
        .await
        .map_err(|e| e.to_string())?
    }

    pub async fn sync_once(&self, name: &str) -> Result<SyncStatus, String> {
        let m = self.mount(name)?;
        let folder = PathBuf::from(&m.local_path);
        self.reg.lock().unwrap().syncing.insert(name.to_string());

        let status = match Self::run_sync(folder).await {
            Ok(rep) => status_from_report(name, &rep),
            Err(e) => SyncStatus {
                mount_name: name.to_string(),
                state: "error".to_string(),
                last_sync: Some(util::now_stamp()),
                files_synced: 0,
                bytes_synced: 0,
                errors: vec![e],
                progress: 0.0,
            },
        };

        {
            let mut g = self.reg.lock().unwrap();
            g.syncing.remove(name);
            g.last.insert(name.to_string(), status.clone());
        }
        Ok(status)
    }

    /// 依次同步所有挂载（托盘「立即同步全部」）。单项失败不影响其它挂载。
    pub async fn sync_all(&self) -> Vec<SyncStatus> {
        let names: Vec<String> = self.reg.lock().unwrap().mounts.keys().cloned().collect();
        let mut out = Vec::with_capacity(names.len());
        for n in &names {
            if let Ok(s) = self.sync_once(n).await {
                out.push(s);
            }
        }
        out
    }

    pub async fn get_status(&self, name: &str) -> Result<SyncStatus, String> {
        let g = self.reg.lock().unwrap();
        Ok(g
            .last
            .get(name)
            .cloned()
            .unwrap_or_else(|| SyncStatus::idle(name)))
    }

    pub async fn start_watch(&self, name: &str) -> Result<(), String> {
        if self.is_paused() {
            return Err("同步已暂停，请先在托盘菜单恢复".to_string());
        }
        let m = self.mount(name)?;
        let already = self
            .watchers
            .lock()
            .unwrap()
            .get(name)
            .map(|h| h.is_running())
            .unwrap_or(false);
        if already {
            return Ok(());
        }
        let folder = PathBuf::from(&m.local_path);

        let reg = Arc::clone(&self.reg);
        let n1 = name.to_string();
        let on_message = move |_msg: &str, _cur: usize, _tot: usize| {
            let mut g = reg.lock().unwrap();
            let e = g
                .last
                .entry(n1.clone())
                .or_insert_with(|| SyncStatus::idle(&n1));
            e.state = "syncing".to_string();
        };

        let reg2 = Arc::clone(&self.reg);
        let n2 = name.to_string();
        let on_report = move |rep: &SyncReport| {
            let mut g = reg2.lock().unwrap();
            g.last.insert(n2.clone(), status_from_report(&n2, rep));
        };

        // 与 v1 行为对齐：轮询间隔/去抖可取配置，P2P 由设置开关控制。
        let settings = self.load_settings();
        let interval = settings.sync_interval_secs.clamp(5, 3600);
        let handle = watcher::spawn(folder, interval, 3, settings.enable_p2p, on_message, on_report);
        self.watchers.lock().unwrap().insert(name.to_string(), handle);
        Ok(())
    }

    pub async fn stop_watch(&self, name: &str) -> Result<(), String> {
        let handle = self.watchers.lock().unwrap().remove(name);
        drop(handle); // 锁外 join 监视线程
        let mut g = self.reg.lock().unwrap();
        if let Some(s) = g.last.get_mut(name) {
            s.state = "idle".to_string();
        }
        Ok(())
    }

    // ---- 只读远端数据 ---- //

    pub async fn get_history(
        &self,
        name: &str,
        path: Option<&str>,
        limit: u32,
    ) -> Result<Vec<VersionEntry>, String> {
        let m = self.mount(name)?;
        let (url, vault, token) = (m.server_url, m.vault_id, m.token);
        let path = path.map(|s| s.to_string());
        let out = tokio::task::spawn_blocking(move || -> Result<Vec<VersionEntry>, String> {
            let client = Client::new(&url, &vault, &token);
            let items = client
                .history(path.as_deref(), limit as usize)
                .map_err(|e| e.to_string())?;
            Ok(items
                .into_iter()
                .map(|h| VersionEntry {
                    path: h.path,
                    hash: h.hash,
                    size: h.size.map(|v| v.max(0) as u64),
                    rev: h.rev.max(0) as u64,
                    time: h.time,
                    origin: h.origin,
                    action: h.action,
                })
                .collect())
        })
        .await
        .map_err(|e| e.to_string())??;
        Ok(out)
    }

    pub async fn restore_version(&self, name: &str, path: &str, rev: u64) -> Result<(), String> {
        let m = self.mount(name)?;
        let folder = PathBuf::from(&m.local_path);
        let (url, vault, token) = (m.server_url, m.vault_id, m.token);
        let path_s = path.to_string();
        tokio::task::spawn_blocking(move || -> Result<(), String> {
            let client = Client::new(&url, &vault, &token);
            let items = client.history(Some(&path_s), 500).map_err(|e| e.to_string())?;
            let digest = items
                .iter()
                .find(|h| h.rev.max(0) as u64 == rev && h.hash.is_some())
                .and_then(|h| h.hash.clone())
                .ok_or_else(|| format!("找不到 {} 的 rev {} 版本", path_s, rev))?;
            let data = client.get_blob_bytes(&digest).map_err(|e| e.to_string())?;
            let target = util::abs_path(&folder, &path_s)?; // 拒绝 .. 越界
            // 与 v1 `ss_restore` 默认不覆盖对齐：本地同名文件存在时写恢复副本。
            SyncEngine::write_restored_bytes(&target, &data)?;
            Ok(())
        })
        .await
        .map_err(|e| e.to_string())??;
        // 恢复后本地内容变回旧版本，下一次同步会把它作为新版本推上去（不篡改历史）。
        Ok(())
    }

    /// 历史版本落地（不触网，供 `restore_version` 与本地测试共用）。
    ///
    /// 对齐 v1 `ss_restore`（desktop/core/src/ffi.rs:596-607）的默认不覆盖语义：
    /// 目标已存在时写到同目录的「stem (恢复 YYYYMMDD-HHMMSS).ext」恢复副本，
    /// 保护本地未同步编辑；目标不存在时仍写原路径。
    /// 这不是 IPC 命令、不新增参数，仅把下载 blob 之后的写入段抽成可直调纯函数。
    #[doc(hidden)]
    pub fn write_restored_bytes(target: &Path, data: &[u8]) -> Result<PathBuf, String> {
        util::ensure_parent(target).map_err(|e| e.to_string())?;
        let final_path = if target.exists() {
            let stem = target
                .file_stem()
                .map(|s| s.to_string_lossy().to_string())
                .unwrap_or_default();
            let ext = target
                .extension()
                .map(|s| s.to_string_lossy().to_string())
                .unwrap_or_default();
            let name = if ext.is_empty() {
                format!("{} (恢复 {})", stem, util::now_stamp())
            } else {
                format!("{} (恢复 {}).{}", stem, util::now_stamp(), ext)
            };
            target.with_file_name(name)
        } else {
            target.to_path_buf()
        };
        util::atomic_write(&final_path, data).map_err(|e| e.to_string())?;
        Ok(final_path)
    }

    pub async fn get_stat(&self, name: &str) -> Result<Stat, String> {
        let m = self.mount(name)?;
        let (url, vault, token) = (m.server_url, m.vault_id, m.token);
        let s = tokio::task::spawn_blocking(move || -> Result<Stat, String> {
            let st = Client::new(&url, &vault, &token)
                .stat()
                .map_err(|e| e.to_string())?;
            Ok(Stat {
                files: st.files.max(0) as u64,
                bytes: st.bytes.max(0) as u64,
                versions: st.versions.max(0) as u64,
                blobs: st.blobs.max(0) as u64,
                blob_bytes: st.blob_bytes.max(0) as u64,
                head_rev: st.head_rev.max(0) as u64,
            })
        })
        .await
        .map_err(|e| e.to_string())??;
        Ok(s)
    }
}

fn status_from_report(name: &str, rep: &SyncReport) -> SyncStatus {
    let files = (rep.pulls.len()
        + rep.pushes.len()
        + rep.deletes_local.len()
        + rep.deletes_remote.len()) as u64;
    let bytes = rep.bytes_up.max(0) as u64 + rep.bytes_down.max(0) as u64;
    SyncStatus {
        mount_name: name.to_string(),
        state: "idle".to_string(),
        last_sync: Some(util::now_stamp()),
        files_synced: files,
        bytes_synced: bytes,
        errors: rep.errors.clone(),
        progress: 1.0,
    }
}
