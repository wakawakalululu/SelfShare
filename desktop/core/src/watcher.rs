//! 后台自动同步线程。
//!
//! 用轮询而非系统通知：在 Windows、SMB 网络盘、Linux 上行为一致，且空转时
//! 只做 `(size, mtime)` 比对，不做哈希。

use std::collections::BTreeMap;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

use crate::engine::{SyncReport, Syncer};
use crate::state::LocalState;
use crate::util::scan_dir;

pub struct WatchHandle {
    stop: Arc<AtomicBool>,
    join: Option<JoinHandle<()>>,
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
}

impl Drop for WatchHandle {
    fn drop(&mut self) {
        self.stop();
    }
}

type Snapshot = BTreeMap<String, (u64, f64)>;

fn take_snapshot(folder: &PathBuf, patterns: &[String]) -> Snapshot {
    match scan_dir(folder, patterns) {
        Ok(items) => items.into_iter().map(|(p, s, m)| (p, (s, m))).collect(),
        Err(_) => Snapshot::new(),
    }
}

/// 启动监视线程。
pub fn spawn<M, R>(
    folder: PathBuf,
    interval_secs: u64,
    debounce_secs: u64,
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

    let join = std::thread::Builder::new()
        .name("selfshare-watch".into())
        .spawn(move || {
            let patterns = crate::util::load_ignore_patterns(&folder);
            let mut last;
            let mut pending_since: Option<Instant> = None;
            let mut last_full = Instant::now();

            // 启动即做一次同步，让界面立刻收敛；完成后清除待处理标记，
            // 否则 debounce 到期会无故再跑一次。
            run_once(&folder, &mut on_message, &mut on_report);
            last = take_snapshot(&folder, &patterns);

            while !stop_flag.load(Ordering::SeqCst) {
                std::thread::sleep(interval);
                if stop_flag.load(Ordering::SeqCst) {
                    break;
                }
                let current = take_snapshot(&folder, &patterns);
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
                    run_once(&folder, &mut on_message, &mut on_report);
                    last = take_snapshot(&folder, &patterns);
                    last_full = Instant::now();
                } else if last_full.elapsed() >= Duration::from_secs(120) {
                    // 无本地变更时也定期巡检，拉取其他主机的更新
                    run_once(&folder, &mut on_message, &mut on_report);
                    last = take_snapshot(&folder, &patterns);
                    last_full = Instant::now();
                }
            }
        })
        .expect("无法创建监视线程");

    WatchHandle { stop, join: Some(join) }
}

fn run_once<M, R>(folder: &PathBuf, on_message: &mut M, on_report: &mut R)
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
    on_message("同步中…", 0, 0);
    let mut cb = |msg: &str, cur: usize, total: usize| on_message(msg, cur, total);
    match syncer.sync_with_progress(Some(&mut cb)) {
        Ok(report) => on_report(&report),
        Err(e) => on_message(&format!("同步失败：{}", e), 0, 0),
    }
}
