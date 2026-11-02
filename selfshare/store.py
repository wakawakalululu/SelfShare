"""Server-side storage: content-addressed blobs + SQLite metadata and history.

One :class:`Vault` is an independent sync namespace (roughly one 坚果云 "同步文件夹").
Blobs are deduplicated by SHA-256 at the store level, so uploading the same file
to two vaults only costs one copy.

Layout on disk::

    <server_root>/
        server.json                 # vault registry + token digests
        vaults/<vault_id>/
            vault.db                # sqlite: files, versions, meta
            blobs/ab/abcdef...      # raw file bytes, content addressed
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import threading
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .util import CHUNK, atomic_write_bytes, norm_rel, now_iso, save_json, load_json, sha256_bytes

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    rel      TEXT PRIMARY KEY,
    hash     TEXT,
    size     INTEGER,
    mtime    REAL,
    rev      INTEGER NOT NULL,
    deleted  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_files_rev ON files(rev);

CREATE TABLE IF NOT EXISTS versions (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    rel     TEXT NOT NULL,
    hash    TEXT,
    size    INTEGER,
    rev     INTEGER NOT NULL,
    ts      REAL NOT NULL,
    origin  TEXT,
    action  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_versions_rel ON versions(rel, id DESC);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

VAULT_ID_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")


def valid_vault_id(vault_id: str) -> bool:
    return bool(vault_id) and len(vault_id) <= 64 and set(vault_id) <= VAULT_ID_CHARS


class Conflict(Exception):
    """Raised when a commit is rejected for a non-recoverable reason."""


class Vault:
    def __init__(self, path: str):
        self.path = path
        self.blob_root = os.path.join(path, "blobs")
        os.makedirs(self.blob_root, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(
            os.path.join(path, "vault.db"), check_same_thread=False, timeout=30
        )
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=NORMAL")
            self._db.commit()
            if self._get_meta("head_rev") is None:
                self._set_meta("head_rev", "0")

    # ---------------------------------------------------------------- meta ---
    def _get_meta(self, key: str) -> Optional[str]:
        row = self._db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def _set_meta(self, key: str, value: str) -> None:
        self._db.execute(
            "INSERT INTO meta(key, value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    @property
    def head_rev(self) -> int:
        return int(self._get_meta("head_rev") or 0)

    def _bump(self) -> int:
        rev = self.head_rev + 1
        self._set_meta("head_rev", str(rev))
        return rev

    # --------------------------------------------------------------- blobs ---
    def blob_path(self, digest: str) -> str:
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise Conflict("bad blob digest")
        return os.path.join(self.blob_root, digest[:2], digest)

    def has_blob(self, digest: str) -> bool:
        return os.path.exists(self.blob_path(digest))

    def put_blob_bytes(self, data: bytes) -> str:
        digest = sha256_bytes(data)
        if not self.has_blob(digest):
            atomic_write_bytes(self.blob_path(digest), data)
        return digest

    def open_blob(self, digest: str):
        path = self.blob_path(digest)
        if not os.path.exists(path):
            raise FileNotFoundError(digest)
        return open(path, "rb")

    def blob_size(self, digest: str) -> int:
        try:
            return os.path.getsize(self.blob_path(digest))
        except OSError:
            return 0

    # -------------------------------------------------------------- commit ---
    def commit(self, ops: Iterable[Dict[str, Any]], origin: str = "") -> Dict[str, Any]:
        """Apply a batch of operations atomically.

        Each op is ``{"op": "put"|"del", "path": str, "hash": str|None,
        "base_hash": str|None, "size": int, "mtime": float}``.

        ``base_hash`` is the content the client believed to be current. If the
        server holds a different value, the op is reported as a conflict and is
        *not* applied -- the client keeps its version as a conflict copy, which
        mirrors 坚果云's keep-both behaviour.
        """
        conflicts: List[Dict[str, Any]] = []
        applied: List[Dict[str, Any]] = []
        with self._lock:
            for op in ops:
                rel = norm_rel(op.get("path", ""))
                if not rel:
                    continue
                kind = op.get("op", "put")
                base = op.get("base_hash")
                row = self._db.execute(
                    "SELECT hash, rev, deleted FROM files WHERE rel=?", (rel,)
                ).fetchone()
                current = None if (row is None or row["deleted"]) else row["hash"]
                current_rev = row["rev"] if row else 0

                if kind == "del":
                    if current is None:
                        continue  # already gone, nothing to do
                    if base is not None and current != base:
                        conflicts.append(
                            {
                                "path": rel,
                                "reason": "remote_changed",
                                "remote_hash": current,
                                "remote_rev": current_rev,
                            }
                        )
                        continue
                    rev = self._bump()
                    self._db.execute(
                        "UPDATE files SET hash=NULL, size=NULL, mtime=NULL, rev=?, deleted=1 "
                        "WHERE rel=?",
                        (rev, rel),
                    )
                    self._record_version(rel, None, None, rev, origin, "del")
                    applied.append({"path": rel, "rev": rev, "action": "del"})
                    continue

                digest = op.get("hash")
                if not isinstance(digest, str) or not self.has_blob(digest):
                    raise Conflict("blob missing for %s: %r" % (rel, digest))

                if current != base:
                    # Someone else moved this path since the client last synced.
                    if current == digest:
                        continue  # already identical, silent no-op
                    # A client that still holds edited content may resurrect a
                    # path another host deleted. Nothing is overwritten (the
                    # remote side is "absent"), so keep-both semantics hold.
                    if op.get("force") and current is None:
                        pass
                    else:
                        conflicts.append(
                            {
                                "path": rel,
                                "reason": "remote_changed",
                                "remote_hash": current,
                                "remote_rev": current_rev,
                            }
                        )
                        continue

                if current == digest:
                    continue  # unchanged content, no new revision

                rev = self._bump()
                size = int(op.get("size") or self.blob_size(digest))
                mtime = float(op.get("mtime") or time.time())
                self._db.execute(
                    "INSERT INTO files(rel, hash, size, mtime, rev, deleted) "
                    "VALUES(?,?,?,?,?,0) "
                    "ON CONFLICT(rel) DO UPDATE SET hash=excluded.hash, size=excluded.size, "
                    "mtime=excluded.mtime, rev=excluded.rev, deleted=0",
                    (rel, digest, size, mtime, rev),
                )
                self._record_version(rel, digest, size, rev, origin, "put")
                applied.append({"path": rel, "hash": digest, "rev": rev, "action": "put"})

            self._db.commit()
            return {"head_rev": self.head_rev, "applied": applied, "conflicts": conflicts}

    def _record_version(
        self, rel: str, digest: Optional[str], size: Optional[int], rev: int, origin: str, action: str
    ) -> None:
        self._db.execute(
            "INSERT INTO versions(rel, hash, size, rev, ts, origin, action) VALUES(?,?,?,?,?,?,?)",
            (rel, digest, size, rev, time.time(), origin, action),
        )

    # ------------------------------------------------------------ manifest ---
    def manifest(self, since: int = 0) -> Dict[str, Any]:
        with self._lock:
            rows = self._db.execute(
                "SELECT rel, hash, size, mtime, rev, deleted FROM files "
                "WHERE rev > ? ORDER BY rev ASC",
                (since,),
            ).fetchall()
        entries = [
            {
                "path": r["rel"],
                "hash": r["hash"],
                "size": r["size"],
                "mtime": r["mtime"],
                "rev": r["rev"],
                "deleted": bool(r["deleted"]),
            }
            for r in rows
        ]
        return {"head_rev": self.head_rev, "entries": entries}

    def history(self, rel: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            if rel:
                rows = self._db.execute(
                    "SELECT rel, hash, size, rev, ts, origin, action FROM versions "
                    "WHERE rel=? ORDER BY id DESC LIMIT ?",
                    (norm_rel(rel), limit),
                ).fetchall()
            else:
                rows = self._db.execute(
                    "SELECT rel, hash, size, rev, ts, origin, action FROM versions "
                    "ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [
            {
                "path": r["rel"],
                "hash": r["hash"],
                "size": r["size"],
                "rev": r["rev"],
                "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["ts"])),
                "origin": r["origin"] or "",
                "action": r["action"],
            }
            for r in rows
        ]

    def stat(self) -> Dict[str, Any]:
        with self._lock:
            live = self._db.execute(
                "SELECT COUNT(*) c, COALESCE(SUM(size),0) s FROM files WHERE deleted=0"
            ).fetchone()
            versions = self._db.execute("SELECT COUNT(*) c FROM versions").fetchone()["c"]
        blobs = 0
        blob_bytes = 0
        for dirpath, _dirnames, filenames in os.walk(self.blob_root):
            for name in filenames:
                blobs += 1
                try:
                    blob_bytes += os.path.getsize(os.path.join(dirpath, name))
                except OSError:
                    pass
        return {
            "files": live["c"],
            "bytes": live["s"],
            "versions": versions,
            "blobs": blobs,
            "blob_bytes": blob_bytes,
            "head_rev": self.head_rev,
        }

    def close(self) -> None:
        with self._lock:
            try:
                self._db.close()
            except Exception:
                pass


class Registry:
    """Vault registry + bearer-token verification.

    ``server.json`` may be edited by an admin process (``selfshare vault create``)
    while the server is already running, so the in-memory copy is reloaded
    whenever the file mtime changes.
    """

    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)
        self.file = os.path.join(self.root, "server.json")
        self._lock = threading.RLock()
        self._mtime: Optional[float] = None
        self.data: Dict[str, Any] = {"vaults": {}}
        self._reload()

    def _reload(self) -> None:
        try:
            mtime = os.path.getmtime(self.file)
        except OSError:
            mtime = None
        if mtime == self._mtime and self.data.get("vaults"):
            return
        data = load_json(self.file, None) or {"vaults": {}}
        data.setdefault("vaults", {})
        self.data = data
        self._mtime = mtime

    def _refresh(self) -> None:
        with self._lock:
            self._reload()

    def save(self) -> None:
        with self._lock:
            save_json(self.file, self.data)
            try:
                self._mtime = os.path.getmtime(self.file)
            except OSError:
                self._mtime = None

    def vault_path(self, vault_id: str) -> str:
        return os.path.join(self.root, "vaults", vault_id)

    def list_vaults(self) -> List[str]:
        self._refresh()
        return sorted(self.data.get("vaults", {}))

    def exists(self, vault_id: str) -> bool:
        self._refresh()
        return vault_id in self.data.get("vaults", {})

    def create_vault(self, vault_id: str, token: Optional[str] = None, note: str = "") -> Dict[str, Any]:
        if not valid_vault_id(vault_id):
            raise ValueError(
                "vault id must be 1-64 chars of a-z A-Z 0-9 _ - (got %r)" % vault_id
            )
        with self._lock:
            self._reload()
            if vault_id in self.data.get("vaults", {}):
                raise ValueError("vault %r already exists" % vault_id)
            token = token or secrets.token_urlsafe(24)
            salt = secrets.token_hex(16)
            self.data["vaults"][vault_id] = {
                "created": now_iso(),
                "note": note,
                "salt": salt,
                "token_sha256": _digest_token(token, salt),
            }
            self.save()
        os.makedirs(self.vault_path(vault_id), exist_ok=True)
        return {"vault": vault_id, "token": token}

    def check_token(self, vault_id: str, token: str) -> bool:
        self._refresh()
        info = self.data.get("vaults", {}).get(vault_id)
        if not info or not token:
            return False
        return hmac.compare_digest(_digest_token(token, info["salt"]), info["token_sha256"])

    def rotate_token(self, vault_id: str) -> Dict[str, Any]:
        self._refresh()
        if not self.exists(vault_id):
            raise ValueError("no such vault: %r" % vault_id)
        token = secrets.token_urlsafe(24)
        salt = secrets.token_hex(16)
        with self._lock:
            self.data["vaults"][vault_id]["salt"] = salt
            self.data["vaults"][vault_id]["token_sha256"] = _digest_token(token, salt)
            self.save()
        return {"vault": vault_id, "token": token}

    def open_vault(self, vault_id: str) -> Vault:
        if not self.exists(vault_id):
            raise ValueError("no such vault: %r" % vault_id)
        path = self.vault_path(vault_id)
        os.makedirs(path, exist_ok=True)
        return Vault(path)


def _digest_token(token: str, salt: str) -> str:
    return hashlib.sha256((salt + ":" + token).encode("utf-8")).hexdigest()
