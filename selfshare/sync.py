"""Two-way sync engine with three-way merge.

Per mount folder we keep a small SQLite "base" snapshot: the state both sides
agreed on at the end of the previous sync. Every path is then merged from three
observations -- local disk (L), base snapshot (B), remote manifest (R):

===================  =====================  ==========================
local vs base        remote vs base         action
===================  =====================  ==========================
unchanged            unchanged              nothing
changed              unchanged              push
unchanged            changed                pull
changed              changed (same content) converge
changed              changed (different)    conflict copy + pull
deleted              unchanged              push delete
deleted              changed                pull (remote wins, no data loss)
unchanged            deleted                delete locally
changed              deleted                keep local, re-upload
===================  =====================  ==========================

"Conflict copy" mirrors 坚果云: the local version is renamed to
``name (冲突副本-从 HOST 时间戳).ext`` next to the original, the remote version
takes the canonical name, and both are uploaded, so nothing is ever lost.
"""

from __future__ import annotations

import os
import shutil
import socket
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .client import Client, RemoteError
from .util import (
    ALWAYS_IGNORED_DIRS,
    abs_path,
    ensure_parent,
    is_ignored,
    load_ignore_patterns,
    norm_rel,
    now_stamp,
    sha256_file,
)

STATE_DIR = ".selfshare"
LOCK_NAME = "sync.lock"
CONFLICT_TAG = "冲突副本"


def _workers(env_name: str, default: int) -> int:
    raw = os.environ.get(env_name, "")
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(1, min(64, value)) if value > 0 else default


# urllib 每条请求都新建 TCP 连接，串行上传上千个小文件会慢到几十秒；
# 按内容摘要去重后并发上传是这里最大的一笔开销节省。
UPLOAD_WORKERS = _workers("SELFSHARE_UPLOAD_WORKERS", 8)
# 小文件直接 PUT：内容寻址本身幂等，省掉一次 HEAD 往返比避免重复上传更划算。
# 大文件仍先 HEAD，免得把已存在的 GB 级内容再传一遍。
HEAD_SKIP_ABOVE = 1024 * 1024
# 下载同样按请求数计成本；每个文件写各自的临时文件，可以安全并发。
DOWNLOAD_WORKERS = _workers("SELFSHARE_DOWNLOAD_WORKERS", 8)
# 批量上传的分组上限（服务端另有 512 项 / 单项 4 MiB 的硬限制）
BULK_ITEM_MAX = 256 * 1024
BULK_BATCH_ITEMS = 200
BULK_BATCH_BYTES = 8 * 1024 * 1024


# --------------------------------------------------------------------------- #
# local state
# --------------------------------------------------------------------------- #
@dataclass
class Entry:
    hash: Optional[str]
    size: Optional[int]
    mtime: Optional[float]
    rev: int = 0
    deleted: bool = False


class LocalState:
    def __init__(self, folder: str):
        self.folder = folder
        self.dir = os.path.join(folder, STATE_DIR)
        os.makedirs(self.dir, exist_ok=True)
        self.db_path = os.path.join(self.dir, "state.db")
        self._db = sqlite3.connect(self.db_path, timeout=30)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS files (
                rel TEXT PRIMARY KEY, hash TEXT, size INTEGER,
                mtime REAL, rev INTEGER DEFAULT 0, deleted INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """
        )
        self._db.commit()
        if not self.get("host_id"):
            self.set("host_id", "%s-%s" % (_short_host(), os.urandom(2).hex()))
            self.set("created", time.strftime("%Y-%m-%d %H:%M:%S"))
        self.set("folder", os.path.abspath(folder))
        if not self.get("head_rev"):
            self.set("head_rev", "0")

    # ------------------------------------------------------------------ meta ---
    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self._db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set(self, key: str, value: str) -> None:
        self._db.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
        self._db.commit()

    @property
    def host_id(self) -> str:
        return self.get("host_id") or _short_host()

    # -------------------------------------------------------------- entries ---
    def load(self) -> Dict[str, Entry]:
        rows = self._db.execute(
            "SELECT rel, hash, size, mtime, rev, deleted FROM files"
        ).fetchall()
        return {
            r["rel"]: Entry(r["hash"], r["size"], r["mtime"], r["rev"], bool(r["deleted"]))
            for r in rows
        }

    def put(self, rel: str, hash_: Optional[str], size: Optional[int],
            mtime: Optional[float], rev: int, deleted: bool = False) -> None:
        self._db.execute(
            "INSERT INTO files(rel,hash,size,mtime,rev,deleted) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(rel) DO UPDATE SET hash=excluded.hash, size=excluded.size, "
            "mtime=excluded.mtime, rev=excluded.rev, deleted=excluded.deleted",
            (rel, hash_, size, mtime, rev, 1 if deleted else 0),
        )

    def forget(self, rel: str) -> None:
        self._db.execute("DELETE FROM files WHERE rel=?", (rel,))

    def put_many(self, items: Iterable[Tuple[str, Entry]]) -> None:
        for rel, e in items:
            self.put(rel, e.hash, e.size, e.mtime, e.rev, e.deleted)
        self._db.commit()

    def commit(self) -> None:
        self._db.commit()

    def close(self) -> None:
        try:
            self._db.close()
        except Exception:
            pass


def _short_host() -> str:
    try:
        name = socket.gethostname() or "host"
    except OSError:
        name = "host"
    name = "".join(c if c.isalnum() or c in "-_" else "-" for c in name)
    return name[:24]


# --------------------------------------------------------------------------- #
# actions
# --------------------------------------------------------------------------- #
@dataclass
class Action:
    kind: str                      # push | pull | delete_local | delete_remote | conflict | converge
    rel: str
    reason: str = ""
    local: Optional[Entry] = None
    remote: Optional[Entry] = None
    conflict_rel: str = ""
    force: bool = False


@dataclass
class SyncReport:
    pulls: List[str] = field(default_factory=list)
    pushes: List[str] = field(default_factory=list)
    deletes_local: List[str] = field(default_factory=list)
    deletes_remote: List[str] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    bytes_down: int = 0
    bytes_up: int = 0
    head_rev: int = 0
    dry_run: bool = False

    @property
    def changed(self) -> bool:
        return bool(
            self.pulls or self.pushes or self.deletes_local or self.deletes_remote
        )

    def summary(self) -> str:
        parts = [
            "拉取 %d" % len(self.pulls),
            "上传 %d" % len(self.pushes),
            "本地删除 %d" % len(self.deletes_local),
            "远端删除 %d" % len(self.deletes_remote),
            "冲突 %d" % len(self.conflicts),
        ]
        if self.errors:
            parts.append("错误 %d" % len(self.errors))
        sizes = ""
        if self.bytes_down or self.bytes_up:
            sizes = " | 下行 %.1f KB / 上行 %.1f KB" % (
                self.bytes_down / 1024.0,
                self.bytes_up / 1024.0,
            )
        prefix = "[预演] " if self.dry_run else ""
        return prefix + ", ".join(parts) + sizes


# --------------------------------------------------------------------------- #
# engine
# --------------------------------------------------------------------------- #
class Syncer:
    def __init__(self, folder: str, client: Client, on_log=None):
        self.folder = os.path.abspath(folder)
        self.client = client
        self.state = LocalState(self.folder)
        self.patterns = load_ignore_patterns(self.folder)
        self._log = on_log or (lambda msg: None)
        self._lock_handle = None
        self.peer_id = None          # P2P：本节点的 peer_id；None 表示不启用 P2P
        self.peer_node = None        # 可选：持有 PeerNode 引用，由 watch/CLI 管理生命周期
        self.upload_errors: List[str] = []   # 并发上传期间的失败，由主线程汇总进 report

    # ------------------------------------------------------------- lifecycle ---
    def __enter__(self) -> "Syncer":
        self._acquire_lock()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._release_lock()
        self.state.close()

    def _acquire_lock(self) -> None:
        path = os.path.join(self.state.dir, LOCK_NAME)
        if os.path.exists(path):
            pid = ""
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    pid = fh.read().strip()
            except OSError:
                pass
            if pid.isdigit() and _pid_alive(int(pid)):
                raise RuntimeError(
                    "another sync is already running for this folder (pid %s)" % pid
                )
            self._log("发现残留锁文件，已接管")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(str(os.getpid()))
        self._lock_handle = path

    def _release_lock(self) -> None:
        if self._lock_handle:
            try:
                os.unlink(self._lock_handle)
            except OSError:
                pass
            self._lock_handle = None

    # ---------------------------------------------------------------- scan ---
    def scan_local(self) -> Dict[str, Tuple[int, float]]:
        """Return rel -> (size, mtime) for every syncable file on disk."""
        found: Dict[str, Tuple[int, float]] = {}
        root = self.folder
        for dirpath, dirnames, filenames in os.walk(root):
            rel_dir = os.path.relpath(dirpath, root).replace("\\", "/")
            rel_dir = "" if rel_dir == "." else rel_dir
            kept = []
            for name in dirnames:
                child = (rel_dir + "/" + name) if rel_dir else name
                if name == STATE_DIR or name in ALWAYS_IGNORED_DIRS:
                    continue
                if name.startswith(".selfshare-"):
                    continue
                if self.patterns and is_ignored(child, self.patterns, is_dir=True):
                    continue
                kept.append(name)
            dirnames[:] = kept
            for name in filenames:
                child = (rel_dir + "/" + name) if rel_dir else name
                if name.startswith(".selfshare-") or name.endswith(".selfshare-tmp"):
                    continue
                if self.patterns and is_ignored(child, self.patterns):
                    continue
                full = os.path.join(dirpath, name)
                if os.path.islink(full):
                    # 跟随符号链接会把同步目录之外的内容上传到服务端
                    continue
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                found[child] = (st.st_size, st.st_mtime)
        return found

    # ----------------------------------------------------------------- plan ---
    def plan(self, local_files: Dict[str, Tuple[int, float]],
             base: Dict[str, Entry],
             remote: Dict[str, Entry]) -> List[Action]:
        actions: List[Action] = []
        all_paths = set(base) | set(remote) | set(local_files)

        for rel in sorted(all_paths):
            b = base.get(rel)
            r = remote.get(rel)
            local_stat = local_files.get(rel)
            bh = None if (b is None or b.deleted) else b.hash
            rh = None if (r is None or r.deleted) else r.hash

            # local content hash, computed only when the cheap check says it may
            # have changed (or when we have no base record to trust).
            lh: Optional[str] = None
            if local_stat is not None:
                if b is not None and not b.deleted and b.size == local_stat[0] \
                        and b.mtime is not None and abs(b.mtime - local_stat[1]) < 1e-6:
                    lh = bh
                else:
                    try:
                        lh = sha256_file(abs_path(self.folder, rel))
                    except OSError as exc:
                        actions.append(Action("skip", rel, "读取失败: %s" % exc))
                        continue

            if lh is None and rh is None:
                if b is not None and not b.deleted:
                    actions.append(Action("converge", rel, "双方已删除"))
                continue

            if lh is None:  # absent locally
                if bh is not None:
                    if rh == bh:
                        actions.append(Action("delete_remote", rel, "本地已删，远端未变 → 同步删除",
                                              local=Entry(None, None, None, 0, deleted=True)))
                    else:
                        actions.append(Action("pull", rel, "本地已删但远端有改动 → 保留远端",
                                              remote=r))
                else:
                    actions.append(Action("pull", rel, "远端新增", remote=r))
                continue

            if rh is None:  # absent remotely
                if bh is not None:
                    if lh == bh:
                        # remote deleted it, local untouched -> follow the delete
                        actions.append(Action("delete_local", rel, "远端已删，本地未变 → 同步删除",
                                              remote=Entry(None, None, None, 0, deleted=True)))
                    else:
                        actions.append(Action("push", rel, "本地有改动但远端已删 → 保留本地",
                                              local=Entry(lh, local_stat[0], local_stat[1]),
                                              force=True))
                else:
                    actions.append(Action("push", rel, "本地新增",
                                          local=Entry(lh, local_stat[0], local_stat[1])))
                continue

            # both sides have the file
            if lh == rh:
                actions.append(Action("converge", rel, "内容一致", local=Entry(lh, local_stat[0], local_stat[1]),
                                      remote=r))
                continue
            local_changed = lh != bh
            remote_changed = rh != bh
            if local_changed and not remote_changed:
                actions.append(Action("push", rel, "本地改动",
                                      local=Entry(lh, local_stat[0], local_stat[1]), remote=r))
            elif remote_changed and not local_changed:
                actions.append(Action("pull", rel, "远端改动", remote=r))
            elif not local_changed and not remote_changed:
                actions.append(Action("converge", rel, "无变化"))
            else:
                actions.append(Action("conflict", rel, "双方都改动",
                                      local=Entry(lh, local_stat[0], local_stat[1]), remote=r))

        return actions

    # ---------------------------------------------------------------- apply ---
    def sync(self, dry_run: bool = False) -> SyncReport:
        report = SyncReport(dry_run=dry_run)
        base = self.state.load()
        self._log("扫描本地文件…")
        local_files = self.scan_local()
        self._log("获取远端清单…")
        manifest = self.client.manifest(0)
        remote = {
            e["path"]: Entry(e["hash"], e["size"], e["mtime"], e["rev"], e["deleted"])
            for e in manifest["entries"]
        }
        report.head_rev = manifest["head_rev"]
        actions = self.plan(local_files, base, remote)

        push_ops: List[Dict[str, Any]] = []
        push_entries: List[Tuple[str, Entry]] = []
        pending_pulls: List[Action] = []
        conflict_copies: List[Tuple[str, Action]] = []
        push_jobs: List[Action] = []

        for act in actions:
            if act.kind == "skip":
                report.skipped.append(act.rel)
                report.errors.append("%s: %s" % (act.rel, act.reason))
                continue
            if act.kind == "converge":
                if act.remote is not None:
                    self.state.put(act.rel, act.remote.hash, act.remote.size,
                                   act.remote.mtime if act.local is None else act.local.mtime,
                                   act.remote.rev, act.remote.deleted)
                continue

            if act.kind == "pull":
                report.pulls.append(act.rel)
                pending_pulls.append(act)
            elif act.kind == "delete_local":
                report.deletes_local.append(act.rel)
                if not dry_run:
                    full = abs_path(self.folder, act.rel)
                    try:
                        os.unlink(full)
                    except OSError as exc:
                        report.errors.append("删除失败 %s: %s" % (act.rel, exc))
                        continue
                    self.state.put(act.rel, None, None, None,
                                   act.remote.rev if act.remote else 0, deleted=True)
            elif act.kind == "delete_remote":
                report.deletes_remote.append(act.rel)
                lop = {
                    "op": "del",
                    "path": act.rel,
                    "base_hash": base[act.rel].hash if act.rel in base else None,
                }
                push_ops.append(lop)
                push_entries.append((act.rel, Entry(None, None, None, 0, deleted=True)))
            elif act.kind == "push":
                report.pushes.append(act.rel)
                if dry_run:
                    if act.local:
                        report.bytes_up += act.local.size or 0
                    continue
                if act.local is None or act.local.hash is None:
                    report.errors.append("上传失败 %s: 缺少内容摘要" % act.rel)
                    continue
                push_jobs.append(act)
            elif act.kind == "conflict":
                report.conflicts.append(act.rel)
                conflict_copies.append((self._conflict_name(act.rel), act))
                pending_pulls.append(act)

        # 上传：先按内容摘要去重，再并发推送，成功的才进入提交清单
        for act in self._upload_pushes(push_jobs, report):
            b = base.get(act.rel)
            push_ops.append({
                "op": "put",
                "path": act.rel,
                "hash": act.local.hash,
                "size": act.local.size,
                "mtime": act.local.mtime,
                "base_hash": None if (b is None or b.deleted) else b.hash,
                "force": bool(act.force),
            })
            push_entries.append((act.rel, Entry(act.local.hash, act.local.size,
                                                act.local.mtime, 0)))

        # conflict copies: rename local aside first, then pull remote over it,
        # then upload the copy so the other side gets it too.
        for copy_rel, act in conflict_copies:
            if dry_run:
                continue
            src = abs_path(self.folder, act.rel)
            dst = abs_path(self.folder, copy_rel)
            try:
                ensure_parent(dst)
                shutil.move(src, dst)
            except OSError as exc:
                report.errors.append("生成冲突副本失败 %s: %s" % (act.rel, exc))
                continue
            st = os.stat(dst)
            digest = sha256_file(dst)
            entry = Entry(digest, st.st_size, st.st_mtime)
            report.pushes.append(copy_rel)
            self.upload_errors = []
            copy_size = self._upload_blob(copy_rel, entry)
            if copy_size is not None:
                report.bytes_up += copy_size
                push_ops.append({
                    "op": "put",
                    "path": copy_rel,
                    "hash": digest,
                    "size": entry.size,
                    "mtime": entry.mtime,
                    "base_hash": None,
                })
                push_entries.append((copy_rel, Entry(digest, entry.size, entry.mtime, 0)))
            else:
                report.errors.extend(self.upload_errors)
                self.upload_errors = []
        # downloads
        if not dry_run:
            self._download_many(pending_pulls, report)
            if pending_pulls:
                self.state.commit()

        # commit
        if push_ops and not dry_run:
            self._log("提交 %d 项变更…" % len(push_ops))
            try:
                result = self.client.commit(push_ops, origin=self.state.host_id)
            except RemoteError as exc:
                report.errors.append("提交失败: %s" % exc)
                result = None
            if result:
                report.head_rev = result.get("head_rev", report.head_rev)
                applied = {a["path"]: a for a in result.get("applied", [])}
                for rel, entry in push_entries:
                    info = applied.get(rel)
                    if info and info.get("action") == "put":
                        self.state.put(rel, entry.hash, entry.size, entry.mtime, info["rev"])
                    elif info and info.get("action") == "del":
                        self.state.put(rel, None, None, None, info["rev"], deleted=True)
                    elif rel in applied:
                        pass
                for cfl in result.get("conflicts", []):
                    report.errors.append(
                        "提交冲突 %s: %s" % (cfl.get("path"), cfl.get("reason"))
                    )
                    self.state.forget(cfl.get("path", ""))
                self.state.commit()
        elif push_ops and dry_run:
            for act in push_entries:
                if act[1].hash:
                    report.bytes_up += act[1].size or 0

        if not dry_run:
            self.state.set("head_rev", str(report.head_rev))
            self.state.set("last_sync", time.strftime("%Y-%m-%d %H:%M:%S"))
        return report

    # -------------------------------------------------------------- helpers ---
    def _upload_blob(self, rel: str, entry: Optional[Entry]) -> Optional[int]:
        """上传单个 blob，返回实际传输字节（已存在则为 0），失败返回 None。

        不碰共享的 report，方便被线程池并发调用。
        """
        if entry is None or entry.hash is None:
            return None
        try:
            src = abs_path(self.folder, rel)
            actual_size = os.path.getsize(src)
            if actual_size != entry.size:
                raise OSError("文件在同步过程中被修改: %s" % rel)
            if actual_size > HEAD_SKIP_ABOVE and self.client.has_blob(entry.hash):
                return 0
            self.client.put_blob_file(entry.hash, src)
            return actual_size
        except (RemoteError, OSError) as exc:
            self.upload_errors.append("上传失败 %s: %s" % (rel, exc))
            return None

    def _upload_pushes(self, acts: List[Action],
                       report: SyncReport) -> List[Action]:
        """按内容摘要去重后上传，返回上传成功的 action（保持原顺序）。

        小文件合并成批量请求（瓶颈是请求数），大文件单独 PUT 且先 HEAD 避免重复传输。
        """
        if not acts:
            return []
        first_by_hash: Dict[str, Action] = {}
        for act in acts:
            if act.local is None or act.local.hash is None:
                continue
            first_by_hash.setdefault(act.local.hash, act)
        jobs = list(first_by_hash.values())

        self.upload_errors = []
        bad = set()
        sent_bytes = 0
        workers = max(1, min(UPLOAD_WORKERS, len(jobs)))
        small = [a for a in jobs if (a.local.size or 0) <= BULK_ITEM_MAX]
        large = [a for a in jobs if (a.local.size or 0) > BULK_ITEM_MAX]

        serial_queue = list(large)
        if small:
            payloads = []
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for digest, data, err in pool.map(self._read_small_blob, small):
                    if err is not None:
                        self.upload_errors.append(err)
                        bad.add(digest)
                    else:
                        payloads.append((digest, data))

            if payloads and self.client.bulk_supported:
                handled = set()
                retry = set()
                batches = self._chunk_batches(payloads)
                with ThreadPoolExecutor(max_workers=min(workers, len(batches))) as pool:
                    for out in pool.map(self._send_bulk_batch, batches):
                        if out["unsupported"]:
                            retry.update(out["digests"])
                        elif out["error"]:
                            self.upload_errors.append(out["error"])
                            bad.update(out["digests"])
                        else:
                            bad.update(out["failed"])
                            sent_bytes += out["sent"]
                            handled.update(d for d in out["digests"] if d not in out["failed"])
                retry.update(d for d, _ in payloads if d not in handled and d not in bad)
                for digest, _ in payloads:
                    if digest in retry:
                        serial_queue.append(first_by_hash[digest])
            else:
                serial_queue.extend(small)

        if serial_queue:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for digest, size in pool.map(
                        lambda a: (a.local.hash, self._upload_blob(a.rel, a.local)),
                        serial_queue):
                    if size is None:
                        bad.add(digest)
                    else:
                        sent_bytes += size

        report.bytes_up += sent_bytes
        report.errors.extend(self.upload_errors)
        self.upload_errors = []
        return [act for act in acts
                if act.local and act.local.hash is not None and act.local.hash not in bad]

    def _chunk_batches(self, payloads):
        batches, cur, cur_bytes = [], [], 0
        for digest, data in payloads:
            if cur and (len(cur) >= BULK_BATCH_ITEMS
                        or cur_bytes + len(data) > BULK_BATCH_BYTES):
                batches.append(cur)
                cur, cur_bytes = [], 0
            cur.append((digest, data))
            cur_bytes += len(data)
        if cur:
            batches.append(cur)
        return batches

    def _read_small_blob(self, act: Action) -> Tuple[str, Optional[bytes], Optional[str]]:
        digest = act.local.hash
        src = abs_path(self.folder, act.rel)
        try:
            st = os.stat(src)
            if act.local.size is not None and st.st_size != act.local.size:
                raise OSError("文件在同步过程中被修改: %s" % act.rel)
            with open(src, "rb") as fh:
                data = fh.read()
            return digest, data, None
        except OSError as exc:
            return digest, None, "上传失败 %s: %s" % (act.rel, exc)

    def _send_bulk_batch(self, batch):
        digests = [d for d, _ in batch]
        try:
            res = self.client.put_blobs_bulk(batch)
        except RemoteError as exc:
            if exc.status == 404:
                # 旧服务端没有批量端点：本批转串行，之后的批也走串行
                self.client.bulk_supported = False
                return {"digests": digests, "failed": set(), "sent": 0,
                        "error": "", "unsupported": True}
            return {"digests": digests, "failed": set(digests), "sent": 0,
                    "error": "批量上传失败: %s" % exc, "unsupported": False}
        failed = {str(item.get("hash") or "").lower() for item in res.get("failed", [])}
        sent = sum(len(data) for digest, data in batch if digest not in failed)
        return {"digests": digests, "failed": failed, "sent": sent,
                "error": "", "unsupported": False}

    def _fetch_blob(self, act: Action) -> Tuple[Optional[int], str]:
        """把远端内容落到本地，返回 (字节数, 错误)。不碰状态库和 report，便于并发。"""
        remote = act.remote
        if remote is None or remote.hash is None:
            return None, ""
        dest = abs_path(self.folder, act.rel)
        try:
            ensure_parent(dest)
            if self.peer_id:  # P2P：优先直连节点，失败回退中心
                try:
                    source = self.client.get_blob_with_peers(
                        remote.hash, dest, exclude_peer_id=self.peer_id
                    )
                except RemoteError:
                    source = "server"
                    self.client.get_blob(remote.hash, dest)
            else:
                source = "server"
                self.client.get_blob(remote.hash, dest)
            if source.startswith("peer:"):
                self._log("  %s <- %s" % (act.rel, source))
            if remote.size is not None:
                actual = os.path.getsize(dest)
                if actual != remote.size:
                    return None, "校验失败 %s: 期望 %s 字节, 实际 %s" % (
                        act.rel, remote.size, actual)
            if remote.mtime:
                try:
                    os.utime(dest, (remote.mtime, remote.mtime))
                except OSError:
                    pass
            return os.path.getsize(dest), ""
        except (RemoteError, OSError) as exc:
            return None, "下载失败 %s: %s" % (act.rel, exc)

    def _download_many(self, acts: List[Action], report: SyncReport) -> None:
        jobs = [a for a in acts if a.remote is not None and a.remote.hash]
        if not jobs:
            return
        workers = max(1, min(DOWNLOAD_WORKERS, len(jobs)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(self._fetch_blob, jobs))
        for act, (size, err) in zip(jobs, results):
            if err:
                report.errors.append(err)
            if size is None:
                continue
            st = os.stat(abs_path(self.folder, act.rel))
            self.state.put(act.rel, act.remote.hash, st.st_size, st.st_mtime, act.remote.rev)
            report.bytes_down += size

    def _conflict_name(self, rel: str) -> str:
        directory, _, name = rel.rpartition("/")
        stem, dot, ext = name.rpartition(".")
        if not dot:
            stem, ext = name, ""
        suffix = ".%s" % ext if ext else ""
        stamp = now_stamp()
        candidate = "%s (%s-从 %s %s)%s" % (stem, CONFLICT_TAG, self.state.host_id, stamp, suffix)
        full = (directory + "/" + candidate) if directory else candidate
        counter = 2
        while os.path.exists(abs_path(self.folder, full)):
            candidate = "%s (%s-%d-从 %s %s)%s" % (
                stem, CONFLICT_TAG, counter, self.state.host_id, stamp, suffix
            )
            full = (directory + "/" + candidate) if directory else candidate
            counter += 1
        return full


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        try:
            import ctypes

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                return False
            code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            ctypes.windll.kernel32.CloseHandle(handle)
            return code.value == 259  # STILL_ACTIVE
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
