"""Shared helpers: hashing, atomic IO, relative-path normalisation, ignore rules.

Everything here is pure standard library so the tool runs on any host that has
Python 3.9+ (Windows, Linux, macOS) with no third-party packages.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import tempfile
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

CHUNK = 1 << 20  # 1 MiB


# --------------------------------------------------------------------------- #
# hashing
# --------------------------------------------------------------------------- #
def sha256_file(path: str, chunk: int = CHUNK) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------- #
# paths
# --------------------------------------------------------------------------- #
def norm_rel(rel: str) -> str:
    """Normalise a stored relative path to forward slashes, no leading slash.

    Rejects empty results and any traversal segment so a malicious or buggy
    client cannot write outside the vault root.
    """
    text = str(rel).replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    text = text.lstrip("/")
    parts = [p for p in text.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ValueError("path must not contain '..': %r" % rel)
    return "/".join(parts)


def abs_path(root: str, rel: str) -> str:
    """Join a normalised relative path onto a local root directory.

    ``norm_rel`` rejects ``..`` segments but deliberately keeps other text
    verbatim, because the server stores whatever the client sends.  On Windows
    a segment such as ``C:`` makes ``os.path.join`` discard ``root`` and
    resolve against that drive's current directory, so a malicious or buggy
    manifest could read and write outside the vault.  Rust
    (``desktop/core/src/util.rs``) and Go (``store.AbsPath``) both add a
    post-join containment check; this keeps Python in line with them.

    The check is lexical and cheap: it rejects absolute paths and drive-relative
    segments, which are the only ways ``os.path.join`` can drop the root.
    Symlinked directories inside the vault keep their previous behaviour
    (``norm_rel`` never claimed to resolve them).
    """
    rel = norm_rel(rel)
    if not rel:
        raise ValueError("empty relative path")
    if os.path.isabs(rel) or os.path.splitdrive(rel)[0]:
        raise ValueError("path must stay relative to the vault: %r" % rel)
    joined = os.path.join(root, *rel.split("/"))
    root_abs = os.path.abspath(root)
    joined_abs = os.path.abspath(joined)
    if os.path.commonpath([root_abs, joined_abs]) != root_abs:
        raise ValueError("path escapes root: %r" % rel)
    return joined


def ensure_parent(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)


# --------------------------------------------------------------------------- #
# atomic file IO
# --------------------------------------------------------------------------- #
def atomic_write_bytes(path: str, data: bytes) -> None:
    ensure_parent(path)
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".selfshare-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_json(path: str, default: Any = None) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def save_json(path: str, obj: Any) -> None:
    payload = json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True)
    atomic_write_bytes(path, payload.encode("utf-8"))


# --------------------------------------------------------------------------- #
# misc formatting
# --------------------------------------------------------------------------- #
def human_size(num: Optional[float]) -> str:
    if num is None:
        return "-"
    value = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return ("%d %s" % (value, unit)) if unit == "B" else ("%.1f %s" % (value, unit))
        value /= 1024.0
    return "%.1f TB" % value


def now_stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.localtime())


def now_iso() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def file_sig(path: str) -> Tuple[int, float]:
    st = os.stat(path)
    return st.st_size, st.st_mtime


# --------------------------------------------------------------------------- #
# ignore rules (.selfshareignore, gitignore-lite)
# --------------------------------------------------------------------------- #
ALWAYS_IGNORED_DIRS = {".selfshare", "$RECYCLE.BIN", "System Volume Information", ".git"}


def load_ignore_patterns(folder: str) -> List[str]:
    """Read `.selfshareignore` from the folder root (one pattern per line)."""
    path = os.path.join(folder, ".selfshareignore")
    patterns: List[str] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                patterns.append(line)
    except OSError:
        pass
    return patterns


def is_ignored(rel: str, patterns: Iterable[str], is_dir: bool = False) -> bool:
    """Match a relative path against simplified gitignore patterns.

    Rules: a trailing ``/`` targets directories only, a pattern without ``/``
    matches the basename at any depth, ``!`` re-includes, and ``*`` behaves like
    fnmatch (which crosses separators -- deliberate simplification, documented).
    """
    rel = rel.strip("/")
    name = rel.rsplit("/", 1)[-1]
    ignored = False
    for raw in patterns:
        pat = raw.strip()
        if not pat or pat.startswith("#"):
            continue
        negate = pat.startswith("!")
        if negate:
            pat = pat[1:].strip()
        if not pat:
            continue
        dir_only = pat.endswith("/")
        if dir_only:
            pat = pat.rstrip("/")
        if dir_only and not is_dir:
            continue
        hit = False
        if "/" in pat:
            hit = fnmatch.fnmatchcase(rel, pat) or fnmatch.fnmatchcase(rel, pat.rstrip("/") + "/*")
        else:
            hit = fnmatch.fnmatchcase(name, pat)
        if hit:
            ignored = not negate
    return ignored


# --------------------------------------------------------------------------- #
# Windows niceties
# --------------------------------------------------------------------------- #
def hide_path(path: str) -> None:
    """Best-effort: mark a path hidden on Windows (used for the state folder)."""
    if os.name != "nt":
        return
    try:
        import ctypes

        FILE_ATTRIBUTE_HIDDEN = 0x02
        ctypes.windll.kernel32.SetFileAttributesW(str(path), FILE_ATTRIBUTE_HIDDEN)
    except Exception:
        pass


def stat_sig_map(root: str) -> Dict[str, Tuple[int, float]]:
    """Cheap recursive stat (no hashing) of a tree, relative paths as keys."""
    out: Dict[str, Tuple[int, float]] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ALWAYS_IGNORED_DIRS]
        for name in filenames:
            full = os.path.join(dirpath, name)
            try:
                st = os.stat(full)
            except OSError:
                continue
            rel = os.path.relpath(full, root).replace("\\", "/")
            out[rel] = (st.st_size, st.st_mtime)
    return out
