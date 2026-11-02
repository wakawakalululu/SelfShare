//! 稳定 C ABI，供 Flutter (`dart:ffi`) 调用。
//!
//! 设计原则：
//! - 所有函数都是 `extern "C"`，入参出参只用 `char*`，避免结构体布局差异
//! - 每个 `ss_*` 返回的字符串都由 [`ss_free`] 释放
//! - 同步是阻塞操作，GUI 侧在独立 isolate / 线程里调用，或使用 [`ss_watch_start`]
//! - 进度通过 [`ss_progress`] 拉取 JSON 快照，不做跨语言回调，避免线程亲和问题

use std::ffi::{c_char, CStr, CString};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Mutex, OnceLock};

use serde::Serialize;

use crate::client::Client;
use crate::engine::{Syncer, SyncOptions};
use crate::state::{LocalState, MountConfig};
use crate::util::{atomic_write, find_mount_root};
use crate::watcher::WatchHandle;

// --------------------------------------------------------------------------- //
// 全局运行时
// --------------------------------------------------------------------------- //
#[derive(Serialize, Clone, Default)]
pub struct ProgressSnapshot {
    pub state: String,       // idle | scanning | syncing | paused | error
    pub message: String,
    pub current: usize,
    pub total: usize,
    pub last_report: Option<crate::engine::SyncReport>,
    pub last_error: Option<String>,
    pub last_sync_at: String,
    pub watching: bool,
}

static WATCHER: OnceLock<Mutex<Option<WatchHandle>>> = OnceLock::new();
static PROGRESS: OnceLock<Mutex<ProgressSnapshot>> = OnceLock::new();

fn watcher_slot() -> &'static Mutex<Option<WatchHandle>> {
    WATCHER.get_or_init(|| Mutex::new(None))
}

fn progress_slot() -> &'static Mutex<ProgressSnapshot> {
    PROGRESS.get_or_init(|| Mutex::new(ProgressSnapshot {
        state: "idle".into(),
        ..Default::default()
    }))
}

fn set_progress(f: impl FnOnce(&mut ProgressSnapshot)) {
    if let Ok(mut p) = progress_slot().lock() {
        f(&mut p);
    }
}

fn to_c(s: String) -> *mut c_char {
    match CString::new(s) {
        Ok(c) => c.into_raw(),
        Err(_) => CString::new("{\"error\":\"internal: nul byte\"}")
            .unwrap()
            .into_raw(),
    }
}

unsafe fn from_c<'a>(p: *const c_char) -> Option<&'a str> {
    if p.is_null() {
        return None;
    }
    CStr::from_ptr(p).to_str().ok()
}

fn err_json(msg: impl Into<String>) -> *mut c_char {
    let msg = msg.into();
    let v = serde_json::json!({ "ok": false, "error": msg });
    to_c(v.to_string())
}

fn ok_json<T: Serialize>(value: &T) -> *mut c_char {
    let v = serde_json::json!({ "ok": true, "data": value });
    to_c(v.to_string())
}

// --------------------------------------------------------------------------- //
// 通用
// --------------------------------------------------------------------------- //
/// 释放任何 `ss_*` 返回的字符串。
#[no_mangle]
pub unsafe extern "C" fn ss_free(ptr: *mut c_char) {
    if ptr.is_null() {
        return;
    }
    drop(CString::from_raw(ptr));
}

/// 内核版本号，返回的字符串需要 `ss_free`。
#[no_mangle]
pub extern "C" fn ss_version() -> *mut c_char {
    to_c(json!({"version": crate::VERSION, "host_id": crate::util::host_id()}).to_string())
}

use serde_json::json;

// --------------------------------------------------------------------------- //
// 挂载管理
// --------------------------------------------------------------------------- //
#[derive(serde::Deserialize)]
struct MountRequest {
    folder: String,
    url: String,
    vault: String,
    token: String,
    #[serde(default)]
    host_id: String,
}

/// 挂载：校验连通性后写入 `.selfshare/config.json`。
/// 入参为 JSON：`{"folder":..,"url":..,"vault":..,"token":..}`
#[no_mangle]
pub unsafe extern "C" fn ss_mount(req_json: *const c_char) -> *mut c_char {
    let Some(raw) = from_c(req_json) else {
        return err_json("缺少参数");
    };
    let req: MountRequest = match serde_json::from_str(raw) {
        Ok(r) => r,
        Err(e) => return err_json(format!("参数解析失败：{}", e)),
    };
    let mut url = req.url.trim().trim_end_matches('/').to_string();
    if !url.starts_with("http://") && !url.starts_with("https://") {
        url = format!("http://{}", url);
    }
    let client = Client::new(&url, &req.vault, &req.token);
    let stats = match client.stat() {
        Ok(s) => s,
        Err(e) => return err_json(format!("连接失败：{}", e)),
    };
    let folder = PathBuf::from(&req.folder);
    let host_id = if req.host_id.trim().is_empty() {
        crate::util::host_id()
    } else {
        req.host_id
    };
    let cfg = MountConfig {
        url: url.clone(),
        vault: req.vault.clone(),
        token: req.token.clone(),
        folder: folder.to_string_lossy().to_string(),
        host_id,
        created: crate::util::now_stamp(),
    };
    match LocalState::init_mount(&folder, cfg) {
        Ok(_) => ok_json(&json!({
            "folder": folder.to_string_lossy(),
            "url": url,
            "vault": req.vault,
            "remote_files": stats.files,
            "remote_bytes": stats.bytes,
        })),
        Err(e) => err_json(e),
    }
}

/// 卸载：删除配置与状态（本地文件保留）。
#[no_mangle]
pub unsafe extern "C" fn ss_unmount(folder: *const c_char) -> *mut c_char {
    let Some(folder) = from_c(folder) else {
        return err_json("缺少目录");
    };
    let dir = PathBuf::from(folder).join(crate::util::STATE_DIR);
    match std::fs::remove_dir_all(&dir) {
        Ok(_) => ok_json(&json!({"removed": dir.to_string_lossy()})),
        Err(e) => err_json(format!("删除状态目录失败：{}", e)),
    }
}

/// 读取某个目录的挂载信息；未挂载返回 ok:false。
#[no_mangle]
pub unsafe extern "C" fn ss_mount_info(folder: *const c_char) -> *mut c_char {
    let Some(folder) = from_c(folder) else {
        return err_json("缺少目录");
    };
    match LocalState::open(&PathBuf::from(folder)) {
        Ok(st) => {
            let cfg = st.config().clone();
            ok_json(&json!({
                "folder": st.folder().to_string_lossy(),
                "url": cfg.url,
                "vault": cfg.vault,
                "host_id": cfg.host_id,
                "created": cfg.created,
                "tracked": st.snapshot().files.len(),
                "head_rev": st.snapshot().head_rev,
                "last_sync": st.snapshot().last_sync,
            }))
        }
        Err(e) => err_json(e),
    }
}

/// 判断给定路径是否落在某个同步目录内，返回挂载根。
#[no_mangle]
pub unsafe extern "C" fn ss_find_mount(path: *const c_char) -> *mut c_char {
    let Some(path) = from_c(path) else {
        return err_json("缺少路径");
    };
    match find_mount_root(&PathBuf::from(path)) {
        Some(root) => ok_json(&json!({"root": root.to_string_lossy()})),
        None => err_json("不在任何同步目录内"),
    }
}

// --------------------------------------------------------------------------- //
// 同步
// --------------------------------------------------------------------------- //
fn make_syncer(folder: &str) -> Result<Syncer, String> {
    let state = LocalState::open(&PathBuf::from(folder))?;
    let cfg = state.config().clone();
    let client = Client::new(&cfg.url, &cfg.vault, &cfg.token);
    let options = SyncOptions::load(state.folder());
    Ok(Syncer::with_options(client, state, options))
}

/// 执行一次同步。可选第二参数 `dry_run_json`：`{"dry_run":true}`。
#[no_mangle]
pub unsafe extern "C" fn ss_sync(
    folder: *const c_char,
    opts_json: *const c_char,
) -> *mut c_char {
    let Some(folder) = from_c(folder) else {
        return err_json("缺少目录");
    };
    let dry_run = from_c(opts_json)
        .and_then(|s| serde_json::from_str::<serde_json::Value>(s).ok())
        .and_then(|v| v.get("dry_run").and_then(|b| b.as_bool()))
        .unwrap_or(false);

    set_progress(|p| {
        p.state = "syncing".into();
        p.message = "同步中".into();
        p.last_error = None;
    });

    let mut syncer = match make_syncer(folder) {
        Ok(s) => s,
        Err(e) => {
            set_progress(|p| {
                p.state = "error".into();
                p.last_error = Some(e.clone());
            });
            return err_json(e);
        }
    };
    syncer.options.dry_run = dry_run;

    let mut cb = |msg: &str, cur: usize, total: usize| {
        set_progress(|p| {
            p.message = msg.to_string();
            p.current = cur;
            p.total = total;
        });
    };
    match syncer.sync_with_progress(Some(&mut cb)) {
        Ok(report) => {
            set_progress(|p| {
                p.state = "idle".into();
                p.message = report.summary();
                p.current = p.total;
                p.last_sync_at = crate::util::now_stamp();
                if !report.errors.is_empty() {
                    p.last_error = Some(report.errors.join("; "));
                } else {
                    p.last_error = None;
                }
                p.last_report = Some(report.clone());
            });
            ok_json(&report)
        }
        Err(e) => {
            set_progress(|p| {
                p.state = "error".into();
                p.last_error = Some(e.clone());
                p.message = e.clone();
            });
            err_json(e)
        }
    }
}

/// 只规划不落盘。
#[no_mangle]
pub unsafe extern "C" fn ss_plan(folder: *const c_char) -> *mut c_char {
    let Some(folder) = from_c(folder) else {
        return err_json("缺少目录");
    };
    let syncer = match make_syncer(folder) {
        Ok(s) => s,
        Err(e) => return err_json(e),
    };
    match syncer.plan() {
        Ok(actions) => ok_json(&actions),
        Err(e) => err_json(e),
    }
}

/// 拉取进度快照，GUI 定时轮询。
#[no_mangle]
pub extern "C" fn ss_progress() -> *mut c_char {
    match progress_slot().lock() {
        Ok(p) => to_c(serde_json::to_string(&*p).unwrap_or_else(|_| "{}".into())),
        Err(_) => to_c("{}".to_string()),
    }
}

// --------------------------------------------------------------------------- //
// 后台监视
// --------------------------------------------------------------------------- //
#[derive(serde::Deserialize)]
struct WatchRequest {
    folder: String,
    #[serde(default = "default_interval")]
    interval_secs: u64,
    #[serde(default = "default_debounce")]
    debounce_secs: u64,
}

fn default_interval() -> u64 {
    5
}
fn default_debounce() -> u64 {
    2
}

/// 启动后台监视。重复调用会先停止旧任务。
#[no_mangle]
pub unsafe extern "C" fn ss_watch_start(req_json: *const c_char) -> *mut c_char {
    let Some(raw) = from_c(req_json) else {
        return err_json("缺少参数");
    };
    let req: WatchRequest = match serde_json::from_str(raw) {
        Ok(r) => r,
        Err(e) => return err_json(format!("参数解析失败：{}", e)),
    };
    // 先校验挂载配置，避免起线程后才失败
    if let Err(e) = LocalState::open(&PathBuf::from(&req.folder)) {
        return err_json(e);
    }
    let mut slot = match watcher_slot().lock() {
        Ok(g) => g,
        Err(_) => return err_json("内部锁错误"),
    };
    if let Some(mut old) = slot.take() {
        old.stop();
    }
    let folder = req.folder.clone();
    let handle = crate::watcher::spawn(
        PathBuf::from(&folder),
        req.interval_secs,
        req.debounce_secs,
        {
            move |msg, cur, total| {
                set_progress(|p| {
                    p.message = msg.to_string();
                    p.current = cur;
                    p.total = total;
                })
            }
        },
        {
            move |report: &crate::engine::SyncReport| {
                set_progress(|p| {
                    p.state = "idle".into();
                    p.last_sync_at = crate::util::now_stamp();
                    p.last_report = Some(report.clone());
                    p.last_error = if report.errors.is_empty() {
                        None
                    } else {
                        Some(report.errors.join("; "))
                    };
                });
            }
        },
    );
    *slot = Some(handle);
    set_progress(|p| p.watching = true);
    ok_json(&json!({"watching": true, "folder": folder}))
}

/// 停止后台监视。
#[no_mangle]
pub extern "C" fn ss_watch_stop() -> *mut c_char {
    let mut slot = match watcher_slot().lock() {
        Ok(g) => g,
        Err(_) => return err_json("内部锁错误"),
    };
    if let Some(mut h) = slot.take() {
        h.stop();
    }
    set_progress(|p| {
        p.watching = false;
        p.state = "idle".into();
    });
    ok_json(&json!({"watching": false}))
}

/// 查询监视是否在运行。
#[no_mangle]
pub extern "C" fn ss_watch_status() -> *mut c_char {
    let running = watcher_slot()
        .lock()
        .map(|g| g.is_some())
        .unwrap_or(false);
    to_c(json!({"watching": running}).to_string())
}

// --------------------------------------------------------------------------- //
// 历史与恢复
// --------------------------------------------------------------------------- //
/// 历史：`ss_history(folder, path_or_null, limit)`
#[no_mangle]
pub unsafe extern "C" fn ss_history(
    folder: *const c_char,
    path: *const c_char,
    limit: i32,
) -> *mut c_char {
    let Some(folder) = from_c(folder) else {
        return err_json("缺少目录");
    };
    let state = match LocalState::open(&PathBuf::from(folder)) {
        Ok(s) => s,
        Err(e) => return err_json(e),
    };
    let cfg = state.config().clone();
    let client = Client::new(&cfg.url, &cfg.vault, &cfg.token);
    let path = from_c(path).filter(|p| !p.trim().is_empty());
    match client.history(path, limit.clamp(1, 500) as usize) {
        Ok(items) => ok_json(&items),
        Err(e) => err_json(e.to_string()),
    }
}

#[derive(serde::Deserialize)]
struct RestoreRequest {
    folder: String,
    hash: String,
    #[serde(default)]
    path: String,
    #[serde(default)]
    output: String,
    #[serde(default)]
    overwrite: bool,
}

/// 把某个历史版本写回本地。
#[no_mangle]
pub unsafe extern "C" fn ss_restore(req_json: *const c_char) -> *mut c_char {
    let Some(raw) = from_c(req_json) else {
        return err_json("缺少参数");
    };
    let req: RestoreRequest = match serde_json::from_str(raw) {
        Ok(r) => r,
        Err(e) => return err_json(format!("参数解析失败：{}", e)),
    };
    let state = match LocalState::open(&PathBuf::from(&req.folder)) {
        Ok(s) => s,
        Err(e) => return err_json(e),
    };
    let cfg = state.config().clone();
    let client = Client::new(&cfg.url, &cfg.vault, &cfg.token);
    let data = match client.get_blob_bytes(&req.hash) {
        Ok(d) => d,
        Err(e) => return err_json(format!("下载历史版本失败：{}", e)),
    };
    let rel = if req.output.trim().is_empty() {
        req.path.clone()
    } else {
        req.output.clone()
    };
    if rel.trim().is_empty() {
        return err_json("缺少目标路径");
    }
    let dest = match crate::util::abs_path(state.folder(), &rel) {
        Ok(p) => p,
        Err(e) => return err_json(e),
    };
    let mut final_path = dest.clone();
    if dest.exists() && !req.overwrite {
        let stem = dest.file_stem().map(|s| s.to_string_lossy().to_string()).unwrap_or_default();
        let ext = dest.extension().map(|s| s.to_string_lossy().to_string()).unwrap_or_default();
        let name = if ext.is_empty() {
            format!("{} (恢复 {})", stem, crate::util::now_stamp())
        } else {
            format!("{} (恢复 {}).{}", stem, crate::util::now_stamp(), ext)
        };
        final_path = dest.with_file_name(name);
    }
    match atomic_write(&final_path, &data) {
        Ok(_) => ok_json(&json!({
            "path": final_path.to_string_lossy(),
            "size": data.len(),
        })),
        Err(e) => err_json(format!("写入失败：{}", e)),
    }
}

/// 服务端统计，GUI 首页用。
#[no_mangle]
pub unsafe extern "C" fn ss_remote_stat(folder: *const c_char) -> *mut c_char {
    let Some(folder) = from_c(folder) else {
        return err_json("缺少目录");
    };
    let state = match LocalState::open(&PathBuf::from(folder)) {
        Ok(s) => s,
        Err(e) => return err_json(e),
    };
    let cfg = state.config().clone();
    let client = Client::new(&cfg.url, &cfg.vault, &cfg.token);
    match client.stat() {
        Ok(s) => ok_json(&s),
        Err(e) => err_json(e.to_string()),
    }
}

/// 全局开关：停止一切后台任务（应用退出前调用）。
#[no_mangle]
pub extern "C" fn ss_shutdown() -> *mut c_char {
    if let Ok(mut slot) = watcher_slot().lock() {
        if let Some(mut h) = slot.take() {
            h.stop();
        }
    }
    set_progress(|p| p.watching = false);
    ok_json(&json!({"shutdown": true}))
}

static INIT: AtomicBool = AtomicBool::new(false);

/// 幂等初始化，Dart 侧在 `main()` 里调用一次。
#[no_mangle]
pub extern "C" fn ss_init() -> *mut c_char {
    if !INIT.swap(true, Ordering::SeqCst) {
        let _ = progress_slot();
    }
    ok_json(&json!({"version": crate::VERSION}))
}
