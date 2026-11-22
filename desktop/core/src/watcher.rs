//! 后台自动同步线程。
//!
//! 用轮询而非系统通知：在 Windows、SMB 网络盘、Linux 上行为一致，且空转时
//! 只做 `(size, mtime)` 比对，不做哈希。

use std::collections::BTreeMap;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

use serde::Serialize;

use crate::engine::{SyncReport, Syncer};
use crate::state::LocalState;
use crate::util::scan_dir_strict;

/// 本机 P2P 节点快照：watcher 线程在 `PeerServer::start` 成功后写入，
/// 供 GUI 侧只读查询（节点 id 与监听地址）。
#[derive(Debug, Clone, Serialize)]
pub struct PeerNodeInfo {
    pub peer_id: String,
    pub listen: String,
}

pub struct WatchHandle {
    stop: Arc<AtomicBool>,
    join: Option<JoinHandle<()>>,
    peer_node: Arc<Mutex<Option<PeerNodeInfo>>>,
    /// watcher 正在执行同步（run_once）——供引擎侧手动同步互斥，避免
    /// 手动同步与后台巡检对同一 mount 并发双跑（state.json 丢更新）。
    syncing: Arc<AtomicBool>,
}

impl WatchHandle {
    pub fn stop(&mut self) {
        self.stop.store(true, Ordering::SeqCst);
        if let Some(h) = self.join.take() {
            let _ = h.join();
        }
    }

    pub fn is_running(&self) -> bool {
        self.join.is_some() && !self.stop.load(Ordering::SeqCst)
    }

    /// 本机 P2P 节点信息；`None` = 未启用 P2P 或节点尚未启动成功。
    pub fn peer_node(&self) -> Option<PeerNodeInfo> {
        self.peer_node.lock().ok().and_then(|g| g.clone())
    }

    /// 后台巡检同步是否进行中（手动同步据此互斥）。
    pub fn is_syncing(&self) -> bool {
        self.syncing.load(Ordering::SeqCst)
    }
}

impl Drop for WatchHandle {
    fn drop(&mut self) {
        self.stop();
    }
}

type Snapshot = BTreeMap<String, (u64, f64)>;

/// 严格扫描快照：扫描失败（瞬时不可读）时返回 Err——调用方按「本轮无变化」
/// 跳过，绝不把不可读子树当成删除触发同步（数据安全，LOOP-20261123-06）。
fn take_snapshot(folder: &PathBuf, patterns: &[String]) -> Result<Snapshot, String> {
    scan_dir_strict(folder, patterns)
        .map(|items| items.into_iter().map(|(p, s, m)| (p, (s, m))).collect())
}

/// 启动监视线程。
pub fn spawn<M, R>(
    folder: PathBuf,
    interval_secs: u64,
    debounce_secs: u64,
    enable_p2p: bool,
    mut on_message: M,
    mut on_report: R,
) -> WatchHandle
where
    M: FnMut(&str, usize, usize) + Send + 'static,
    R: FnMut(&SyncReport) + Send + 'static,
{
    let stop = Arc::new(AtomicBool::new(false));
    let stop_flag = Arc::clone(&stop);
    let interval = Duration::from_secs(interval_secs.max(1));
    let debounce = Duration::from_secs(debounce_secs);
    let peer_node_slot: Arc<Mutex<Option<PeerNodeInfo>>> = Arc::new(Mutex::new(None));
    let slot_in_thread = Arc::clone(&peer_node_slot);
    let syncing_slot = Arc::new(AtomicBool::new(false));
    let syncing_in_thread = Arc::clone(&syncing_slot);

    let join = std::thread::Builder::new()
        .name("selfshare-watch".into())
        .spawn(move || {
            let patterns = crate::util::load_ignore_patterns(&folder);

            // P2P：先起节点服务，再让所有同步优先走 peer。
            let mut peer_node: Option<(crate::peer::PeerServer, String)> = None;
            if enable_p2p {
                if let Ok(st) = LocalState::open(&folder) {
                    let cfg = st.config().clone();
                    let pid = crate::peer::make_peer_id(&format!(
                        "rust-{}", crate::util::host_id()
                    ));
                    match crate::peer::PeerServer::start(
                        folder.clone(), cfg.vault.clone(), cfg.token.clone(), pid.clone(), 0,
                    ) {
                        Ok(n) => {
                            let _ = crate::client::Client::new(&cfg.url, &cfg.vault, &cfg.token)
                                .peer_register(&pid, &n.listen, &[], &cfg.host_id);
                            on_message(&format!("P2P 节点已启动：{}", n.listen), 0, 0);
                            // 节点信息写入共享槽，供 WatchHandle::peer_node() 只读查询
                            if let Ok(mut slot) = slot_in_thread.lock() {
                                *slot = Some(PeerNodeInfo {
                                    peer_id: pid.clone(),
                                    listen: n.listen.clone(),
                                });
                            }
                            peer_node = Some((n, pid));
                        }
                        Err(e) => on_message(&format!("P2P 启动失败：{}", e), 0, 0),
                    }
                }
            }
            let peer_id = peer_node.as_ref().map(|(_, p)| p.clone());
            let mut last;
            let mut pending_since: Option<Instant> = None;
            let mut last_full = Instant::now();

            // 启动即做一次同步，让界面立刻收敛；完成后清除待处理标记，
            // 否则 debounce 到期会无故再跑一次。
            syncing_in_thread.store(true, Ordering::SeqCst);
            run_once(&folder, peer_id.as_deref(), &mut on_message, &mut on_report);
            syncing_in_thread.store(false, Ordering::SeqCst);
            last = match take_snapshot(&folder, &patterns) {
                Ok(snap) => snap,
                Err(e) => {
                    on_message(&format!("本地目录扫描失败，本轮跳过：{}", e), 0, 0);
                    Snapshot::new()
                }
            };

            while !stop_flag.load(Ordering::SeqCst) {
                std::thread::sleep(interval);
                if stop_flag.load(Ordering::SeqCst) {
                    break;
                }
                let current = match take_snapshot(&folder, &patterns) {
                    Ok(snap) => snap,
                    Err(e) => {
                        on_message(&format!("本地目录扫描失败，本轮按无变化跳过：{}", e), 0, 0);
                        continue;
                    }
                };
                if current != last {
                    last = current;
                    pending_since = Some(Instant::now());
                    on_message("检测到本地变更", 0, 0);
                }
                let should_sync = pending_since
                    .map(|t| t.elapsed() >= debounce)
                    .unwrap_or(false);
                if should_sync {
                    pending_since = None;
                    syncing_in_thread.store(true, Ordering::SeqCst);
                    run_once(&folder, peer_id.as_deref(), &mut on_message, &mut on_report);
                    syncing_in_thread.store(false, Ordering::SeqCst);
                    // 同步成功后的快照若扫描失败，保留旧快照（下轮重检，安全不误删）
                    match take_snapshot(&folder, &patterns) {
                        Ok(snap) => last = snap,
                        Err(e) => on_message(&format!("同步后快照失败，保留旧快照：{}", e), 0, 0),
                    }
                    last_full = Instant::now();
                } else if last_full.elapsed() >= Duration::from_secs(120) {
                    // 无本地变更时也定期巡检，拉取其他主机的更新
                    syncing_in_thread.store(true, Ordering::SeqCst);
                    run_once(&folder, peer_id.as_deref(), &mut on_message, &mut on_report);
                    syncing_in_thread.store(false, Ordering::SeqCst);
                    // 同步成功后的快照若扫描失败，保留旧快照（下轮重检，安全不误删）
                    match take_snapshot(&folder, &patterns) {
                        Ok(snap) => last = snap,
                        Err(e) => on_message(&format!("同步后快照失败，保留旧快照：{}", e), 0, 0),
                    }
                    last_full = Instant::now();
                }
            }
            if let Some((mut n, _)) = peer_node {
                n.stop();
            }
        })
        .expect("无法创建监视线程");

    WatchHandle { stop, join: Some(join), peer_node: peer_node_slot, syncing: syncing_slot }
}

fn run_once<M, R>(
    folder: &PathBuf,
    peer_id: Option<&str>,
    on_message: &mut M,
    on_report: &mut R,
)
where
    M: FnMut(&str, usize, usize),
    R: FnMut(&SyncReport),
{
    let state = match LocalState::open(folder) {
        Ok(s) => s,
        Err(e) => {
            on_message(&format!("挂载失效：{}", e), 0, 0);
            return;
        }
    };
    let cfg = state.config().clone();
    let client = crate::client::Client::new(&cfg.url, &cfg.vault, &cfg.token);
    let options = crate::engine::SyncOptions::load(state.folder());
    let mut syncer = Syncer::with_options(client, state, options);
    syncer.peer_id = peer_id.map(|s| s.to_string());
    on_message("同步中…", 0, 0);
    let mut cb = |msg: &str, cur: usize, total: usize| on_message(msg, cur, total);
    match syncer.sync_with_progress(Some(&mut cb)) {
        Ok(report) => on_report(&report),
        Err(e) => on_message(&format!("同步失败：{}", e), 0, 0),
    }
}
