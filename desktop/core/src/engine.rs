//! 三方合并同步引擎。
//!
//! 合并规则与 Python 版 `selfshare/sync.py` 完全一致：
//!
//! | 本地 vs base | 远端 vs base | 行为 |
//! |---|---|---|
//! | 未变 | 未变 | 无操作 |
//! | 有改动 | 未变 | 上传 |
//! | 未变 | 有改动 | 下载 |
//! | 都改、内容相同 | | 收敛 |
//! | 都改、内容不同 | | 冲突副本 + 下载 |
//! | 本地删除 | 远端未变 | 服务端删除 |
//! | 本地删除 | 远端有改动 | 保留远端 |
//! | 未变 | 远端删除 | 本地删除 |
//! | 有改动 | 远端删除 | 保留本地并重新上传 |

use std::fs;
use std::path::Path;

use serde::{Deserialize, Serialize};

use crate::client::{Client, Entry, Op};
use crate::state::{BaseEntry, LocalState};
use crate::util::{
    abs_path, atomic_write, ensure_parent, load_ignore_patterns, mtime_secs, now_stamp, scan_dir,
    sha256_file,
};

pub const CONFLICT_TAG: &str = "冲突副本";

#[derive(Debug, Clone)]
pub struct SyncOptions {
    pub dry_run: bool,
    pub patterns: Vec<String>,
}

impl SyncOptions {
    pub fn load(folder: &Path) -> Self {
        SyncOptions { dry_run: false, patterns: load_ignore_patterns(folder) }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ActionKind {
    Push,
    Pull,
    DeleteLocal,
    DeleteRemote,
    Conflict,
    Converge,
    Skip,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PlannedAction {
    pub kind: ActionKind,
    pub path: String,
    pub reason: String,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct SyncReport {
    pub pulls: Vec<String>,
    pub pushes: Vec<String>,
    pub deletes_local: Vec<String>,
    pub deletes_remote: Vec<String>,
    pub conflicts: Vec<String>,
    pub errors: Vec<String>,
    pub bytes_down: i64,
    pub bytes_up: i64,
    pub head_rev: i64,
    pub dry_run: bool,
    pub duration_ms: u64,
}

impl SyncReport {
    pub fn changed(&self) -> bool {
        !(self.pulls.is_empty()
            && self.pushes.is_empty()
            && self.deletes_local.is_empty()
            && self.deletes_remote.is_empty())
    }

    pub fn summary(&self) -> String {
        let mut s = format!(
            "拉取 {}, 上传 {}, 本地删除 {}, 远端删除 {}, 冲突 {}",
            self.pulls.len(),
            self.pushes.len(),
            self.deletes_local.len(),
            self.deletes_remote.len(),
            self.conflicts.len()
        );
        if !self.errors.is_empty() {
            s.push_str(&format!(", 错误 {}", self.errors.len()));
        }
        if self.dry_run {
            s = format!("[预演] {}", s);
        }
        s
    }
}

/// 同步进度回调，GUI 用它更新界面。
pub type ProgressFn<'a> = &'a mut dyn FnMut(&str, usize, usize);

pub struct Syncer {
    pub client: Client,
    pub state: LocalState,
    pub options: SyncOptions,
    /// 启用 P2P 时填本节点 peer_id；None 表示只走中心服务器。
    pub peer_id: Option<String>,
    /// 每个文件的实际来源，便于界面/日志显示"peer 直连"还是"服务器"。
    pub sources: std::collections::BTreeMap<String, String>,
}

impl Syncer {
    pub fn new(client: Client, state: LocalState) -> Self {
        let options = SyncOptions::load(state.folder());
        Syncer { client, state, options, peer_id: None, sources: Default::default() }
    }

    pub fn with_options(client: Client, state: LocalState, options: SyncOptions) -> Self {
        Syncer { client, state, options, peer_id: None, sources: Default::default() }
    }

    /// 只规划不执行，供 GUI 的「预演」按钮使用。
    pub fn plan(&self) -> Result<Vec<PlannedAction>, String> {
        let local = scan_dir(self.state.folder(), &self.options.patterns)
            .map_err(|e| format!("扫描本地失败：{}", e))?;
        let manifest = self.client.manifest(0).map_err(|e| e.to_string())?;
        let remote: std::collections::BTreeMap<String, Entry> =
            manifest.entries.into_iter().map(|e| (e.path.clone(), e)).collect();
        Ok(self.plan_with(&local, &remote))
    }

    fn plan_with(
        &self,
        local: &[(String, u64, f64)],
        remote: &std::collections::BTreeMap<String, Entry>,
    ) -> Vec<PlannedAction> {
        let snapshot = self.state.snapshot();
        let mut paths: Vec<String> = snapshot.files.keys().cloned().collect();
        paths.extend(remote.keys().cloned());
        paths.extend(local.iter().map(|(p, _, _)| p.clone()));
        paths.sort();
        paths.dedup();

        let local_map: std::collections::BTreeMap<&str, (u64, f64)> =
            local.iter().map(|(p, s, m)| (p.as_str(), (*s, *m))).collect();

        let mut out = Vec::new();
        for rel in paths {
            let base = snapshot.files.get(&rel);
            let r = remote.get(&rel);
            let base_hash = base.and_then(|b| if b.deleted { None } else { b.hash.clone() });
            let remote_hash = r.and_then(|e| if e.deleted { None } else { e.hash.clone() });
            let local_stat = local_map.get(rel.as_str()).copied();

            let local_hash: Option<String> = match local_stat {
                None => None,
                Some((size, mtime)) => {
                    let reuse = base
                        .filter(|b| !b.deleted)
                        .map(|b| b.size == Some(size as i64) && (b.mtime.unwrap_or(-1.0) - mtime).abs() < 1e-6)
                        .unwrap_or(false);
                    if reuse {
                        base_hash.clone()
                    } else {
                        match abs_path(self.state.folder(), &rel).and_then(|p| {
                            sha256_file(&p).map_err(|e| e.to_string())
                        }) {
                            Ok(h) => Some(h),
                            Err(e) => {
                                out.push(PlannedAction {
                                    kind: ActionKind::Skip,
                                    path: rel.clone(),
                                    reason: format!("读取失败：{}", e),
                                });
                                continue;
                            }
                        }
                    }
                }
            };

            if local_hash.is_none() && remote_hash.is_none() {
                if base.map(|b| !b.deleted).unwrap_or(false) {
                    out.push(PlannedAction {
                        kind: ActionKind::Converge,
                        path: rel,
                        reason: "双方已删除".into(),
                    });
                }
                continue;
            }

            if local_hash.is_none() {
                match (base_hash.as_ref(), remote_hash.as_ref()) {
                    (Some(b), Some(r)) if b == r => out.push(PlannedAction {
                        kind: ActionKind::DeleteRemote,
                        path: rel,
                        reason: "本地已删，远端未变 → 同步删除".into(),
                    }),
                    (Some(_), Some(_)) => out.push(PlannedAction {
                        kind: ActionKind::Pull,
                        path: rel,
                        reason: "本地已删但远端有改动 → 保留远端".into(),
                    }),
                    _ => out.push(PlannedAction {
                        kind: ActionKind::Pull,
                        path: rel,
                        reason: "远端新增".into(),
                    }),
                }
                continue;
            }

            if remote_hash.is_none() {
                match base_hash.as_ref() {
                    Some(b) if Some(b) == local_hash.as_ref() => out.push(PlannedAction {
                        kind: ActionKind::DeleteLocal,
                        path: rel,
                        reason: "远端已删，本地未变 → 同步删除".into(),
                    }),
                    Some(_) => out.push(PlannedAction {
                        kind: ActionKind::Push,
                        path: rel,
                        reason: "本地有改动但远端已删 → 保留本地".into(),
                    }),
                    None => out.push(PlannedAction {
                        kind: ActionKind::Push,
                        path: rel,
                        reason: "本地新增".into(),
                    }),
                }
                continue;
            }

            let lh = local_hash.as_ref().unwrap();
            let rh = remote_hash.as_ref().unwrap();
            if lh == rh {
                out.push(PlannedAction {
                    kind: ActionKind::Converge,
                    path: rel,
                    reason: "内容一致".into(),
                });
                continue;
            }
            let local_changed = Some(lh) != base_hash.as_ref();
            let remote_changed = Some(rh) != base_hash.as_ref();
            let kind = match (local_changed, remote_changed) {
                (true, false) => ActionKind::Push,
                (false, true) => ActionKind::Pull,
                (false, false) => ActionKind::Converge,
                (true, true) => ActionKind::Conflict,
            };
            let reason = match kind {
                ActionKind::Push => "本地改动",
                ActionKind::Pull => "远端改动",
                ActionKind::Converge => "无变化",
                _ => "双方都改动",
            };
            out.push(PlannedAction { kind, path: rel, reason: reason.into() });
        }
        out
    }

    pub fn sync(&mut self) -> Result<SyncReport, String> {
        self.sync_with_progress(None)
    }

    pub fn sync_with_progress(
        &mut self,
        progress: Option<&mut dyn FnMut(&str, usize, usize)>,
    ) -> Result<SyncReport, String> {
        let started = std::time::Instant::now();
        let mut report = SyncReport { dry_run: self.options.dry_run, ..Default::default() };
        let mut progress = progress;

        let local = scan_dir(self.state.folder(), &self.options.patterns)
            .map_err(|e| format!("扫描本地失败：{}", e))?;
        let manifest = self.client.manifest(0).map_err(|e| e.to_string())?;
        report.head_rev = manifest.head_rev;
        let remote: std::collections::BTreeMap<String, Entry> =
            manifest.entries.into_iter().map(|e| (e.path.clone(), e)).collect();
        let actions = self.plan_with(&local, &remote);

        let total = actions.len();
        if let Some(cb) = progress.as_deref_mut() {
            cb("规划完成", 0, total);
        }

        let mut ops: Vec<Op> = Vec::new();
        let mut pending_entries: Vec<(String, BaseEntry)> = Vec::new();
        let mut pulls: Vec<String> = Vec::new();
        let mut conflicts: Vec<(String, String)> = Vec::new(); // (原路径, 副本路径)

        for (idx, act) in actions.iter().enumerate() {
            match act.kind {
                ActionKind::Skip => {
                    report.errors.push(format!("{}: {}", act.path, act.reason));
                }
                ActionKind::Converge => {
                    if let Some(r) = remote.get(&act.path) {
                        let local_mtime = local
                            .iter()
                            .find(|(p, _, _)| p == &act.path)
                            .map(|(_, _, m)| *m)
                            .or(r.mtime);
                        self.state.set_base(
                            &act.path,
                            BaseEntry {
                                hash: r.hash.clone(),
                                size: r.size,
                                mtime: local_mtime,
                                rev: r.rev,
                                deleted: false,
                            },
                        );
                    }
                }
                ActionKind::Pull => pulls.push(act.path.clone()),
                ActionKind::DeleteLocal => {
                    report.deletes_local.push(act.path.clone());
                    if !self.options.dry_run {
                        let full = abs_path(self.state.folder(), &act.path)?;
                        if let Err(e) = fs::remove_file(&full) {
                            report.errors.push(format!("删除失败 {}：{}", act.path, e));
                            continue;
                        }
                        let rev = remote.get(&act.path).map(|e| e.rev).unwrap_or(0);
                        self.state.set_base(
                            &act.path,
                            BaseEntry { hash: None, size: None, mtime: None, rev, deleted: true },
                        );
                    }
                }
                ActionKind::DeleteRemote => {
                    report.deletes_remote.push(act.path.clone());
                    ops.push(Op {
                        op: "del",
                        path: act.path.clone(),
                        hash: None,
                        size: None,
                        mtime: None,
                        base_hash: self.state.base_of(&act.path).and_then(|b| b.hash.clone()),
                        force: false,
                    });
                }
                ActionKind::Push => {
                    report.pushes.push(act.path.clone());
                    if self.options.dry_run {
                        if let Some((_, size, _)) = local.iter().find(|(p, _, _)| p == &act.path) {
                            report.bytes_up += *size as i64;
                        }
                        continue;
                    }
                    let Some((size, mtime)) = local
                        .iter()
                        .find(|(p, _, _)| p == &act.path)
                        .map(|(_, s, m)| (*s, *m))
                    else {
                        continue;
                    };
                    let full = abs_path(self.state.folder(), &act.path)?;
                    let digest = match sha256_file(&full) {
                        Ok(d) => d,
                        Err(e) => {
                            report.errors.push(format!("读取失败 {}：{}", act.path, e));
                            continue;
                        }
                    };
                    if let Err(e) = self.upload_blob(&full, &digest, size) {
                        report.errors.push(format!("上传失败 {}：{}", act.path, e));
                        continue;
                    }
                    report.bytes_up += size as i64;
                    let force = act.reason.contains("远端已删");
                    ops.push(Op {
                        op: "put",
                        path: act.path.clone(),
                        hash: Some(digest.clone()),
                        size: Some(size as i64),
                        mtime: Some(mtime),
                        base_hash: self.state.base_of(&act.path).and_then(|b| b.hash.clone()),
                        force,
                    });
                    pending_entries.push((
                        act.path.clone(),
                        BaseEntry {
                            hash: Some(digest),
                            size: Some(size as i64),
                            mtime: Some(mtime),
                            rev: 0,
                            deleted: false,
                        },
                    ));
                }
                ActionKind::Conflict => {
                    report.conflicts.push(act.path.clone());
                    if self.options.dry_run {
                        continue;
                    }
                    let copy_rel = self.conflict_name(&act.path);
                    let src = abs_path(self.state.folder(), &act.path)?;
                    let dst = abs_path(self.state.folder(), &copy_rel)?;
                    ensure_parent(&dst).map_err(|e| e.to_string())?;
                    if let Err(e) = fs::rename(&src, &dst) {
                        report.errors.push(format!("生成冲突副本失败 {}：{}", act.path, e));
                        continue;
                    }
                    let meta = fs::metadata(&dst).map_err(|e| e.to_string())?;
                    let digest = sha256_file(&dst).map_err(|e| e.to_string())?;
                    if let Err(e) = self.upload_blob(&dst, &digest, meta.len()) {
                        report.errors.push(format!("上传冲突副本失败 {}：{}", copy_rel, e));
                    } else {
                        report.bytes_up += meta.len() as i64;
                        report.pushes.push(copy_rel.clone());
                        ops.push(Op {
                            op: "put",
                            path: copy_rel.clone(),
                            hash: Some(digest.clone()),
                            size: Some(meta.len() as i64),
                            mtime: Some(mtime_secs(&meta)),
                            base_hash: None,
                            force: false,
                        });
                        pending_entries.push((
                            copy_rel.clone(),
                            BaseEntry {
                                hash: Some(digest),
                                size: Some(meta.len() as i64),
                                mtime: Some(mtime_secs(&meta)),
                                rev: 0,
                                deleted: false,
                            },
                        ));
                    }
                    conflicts.push((act.path.clone(), copy_rel));
                    pulls.push(act.path.clone());
                }
            }
            if let Some(cb) = progress.as_deref_mut() {
                cb(&format!("{} {}", label(act.kind), act.path), idx + 1, total);
            }
        }

        // 下载（含冲突后拉取远端版本）
        if !self.options.dry_run {
            for rel in &pulls {
                let Some(r) = remote.get(rel) else { continue };
                let Some(digest) = r.hash.as_ref() else { continue };
                match self.download(rel, digest, r.size, r.mtime) {
                    Ok(size) => {
                        report.bytes_down += size;
                        report.pulls.push(rel.clone());
                        let full = abs_path(self.state.folder(), rel)?;
                        let meta = fs::metadata(&full).map_err(|e| e.to_string())?;
                        self.state.set_base(
                            rel,
                            BaseEntry {
                                hash: Some(digest.clone()),
                                size: Some(meta.len() as i64),
                                mtime: Some(mtime_secs(&meta)),
                                rev: r.rev,
                                deleted: false,
                            },
                        );
                    }
                    Err(e) => report.errors.push(format!("下载失败 {}：{}", rel, e)),
                }
            }
        }

        // 提交
        if !ops.is_empty() && !self.options.dry_run {
            if let Some(cb) = progress.as_deref_mut() {
                cb("提交变更", total, total);
            }
            match self.client.commit(&ops, self.state.host_id()) {
                Ok(result) => {
                    report.head_rev = result.head_rev;
                    for applied in &result.applied {
                        match applied.action.as_str() {
                            "put" => {
                                if let Some((_, mut entry)) =
                                    pending_entries.iter().find(|(p, _)| p == &applied.path).cloned()
                                {
                                    entry.rev = applied.rev;
                                    self.state.set_base(&applied.path, entry);
                                }
                            }
                            "del" => {
                                self.state.set_base(
                                    &applied.path,
                                    BaseEntry {
                                        hash: None,
                                        size: None,
                                        mtime: None,
                                        rev: applied.rev,
                                        deleted: true,
                                    },
                                );
                            }
                            _ => {}
                        }
                    }
                    for c in &result.conflicts {
                        report
                            .errors
                            .push(format!("提交冲突 {}：{}", c.path, c.reason));
                        self.state.forget(&c.path);
                    }
                }
                Err(e) => report.errors.push(format!("提交失败：{}", e)),
            }
        }

        if !self.options.dry_run {
            self.state.snapshot_mut().head_rev = report.head_rev;
            self.state.snapshot_mut().last_sync = crate::util::now_stamp();
            self.state.save()?;
        }

        report.duration_ms = started.elapsed().as_millis() as u64;
        if let Some(cb) = progress.as_deref_mut() {
            cb(&report.summary(), total, total);
        }
        let _ = conflicts;
        Ok(report)
    }

    fn upload_blob(&self, path: &Path, digest: &str, size: u64) -> Result<(), String> {
        if self.client.has_blob(digest).map_err(|e| e.to_string())? {
            return Ok(());
        }
        let actual = fs::metadata(path).map_err(|e| e.to_string())?.len();
        if actual != size {
            return Err(format!("文件在同步过程中被修改（{} → {} 字节）", size, actual));
        }
        self.client.put_blob_file(digest, path).map_err(|e| e.to_string())
    }

    fn download(
        &mut self,
        rel: &str,
        digest: &str,
        expect_size: Option<i64>,
        mtime: Option<f64>,
    ) -> Result<i64, String> {
        let dest = abs_path(self.state.folder(), rel)?;
        let (data, source) = if self.peer_id.is_some() {
            self.client
                .get_blob_with_peers(digest, self.peer_id.as_deref())
                .map_err(|e| e.to_string())?
        } else {
            (self.client.get_blob_bytes(digest).map_err(|e| e.to_string())?, "server".to_string())
        };
        self.sources.insert(rel.to_string(), source);
        if let Some(want) = expect_size {
            if data.len() as i64 != want {
                return Err(format!("校验失败：期望 {} 字节，收到 {} 字节", want, data.len()));
            }
        }
        atomic_write(&dest, &data).map_err(|e| format!("写入失败：{}", e))?;
        // 还原修改时间，避免同步后被当成新改动
        if let Some(m) = mtime {
            set_mtime(&dest, m);
        }
        Ok(data.len() as i64)
    }

    fn conflict_name(&self, rel: &str) -> String {
        let (dir, name) = match rel.rfind('/') {
            Some(i) => (&rel[..i], &rel[i + 1..]),
            None => ("", rel),
        };
        let (stem, ext) = match name.rfind('.') {
            Some(i) if i > 0 => (&name[..i], &name[i + 1..]),
            _ => (name, ""),
        };
        let suffix = if ext.is_empty() { String::new() } else { format!(".{}", ext) };
        let stamp = now_stamp();
        let mut counter = 1;
        loop {
            let extra = if counter == 1 { String::new() } else { format!("-{}", counter) };
            let candidate = format!(
                "{} ({}{}-从 {} {}){}",
                stem,
                CONFLICT_TAG,
                extra,
                self.state.host_id(),
                stamp,
                suffix
            );
            let full = if dir.is_empty() { candidate.clone() } else { format!("{}/{}", dir, candidate) };
            let exists = abs_path(self.state.folder(), &full)
                .map(|p| p.exists())
                .unwrap_or(false);
            if !exists {
                return full;
            }
            counter += 1;
        }
    }
}

fn label(kind: ActionKind) -> &'static str {
    match kind {
        ActionKind::Push => "↑",
        ActionKind::Pull => "↓",
        ActionKind::DeleteLocal => "-",
        ActionKind::DeleteRemote => "-",
        ActionKind::Conflict => "*",
        ActionKind::Converge => "=",
        ActionKind::Skip => "!",
    }
}

fn set_mtime(path: &Path, epoch: f64) {
    // std 1.75+ 的 File::set_times 跨平台可用，避免引入额外 crate。
    use std::time::{Duration, UNIX_EPOCH};
    let Ok(file) = fs::OpenOptions::new().write(true).open(path) else {
        return;
    };
    let when = UNIX_EPOCH + Duration::from_secs_f64(epoch.max(0.0));
    let times = fs::FileTimes::new().set_accessed(when).set_modified(when);
    let _ = file.set_times(times);
}
