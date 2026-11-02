"""Config storage: per-mount config file + a global mount registry."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from .util import atomic_write_bytes, load_json, save_json
from .sync import STATE_DIR

GLOBAL_DIR_ENV = "SELFSHARE_HOME"


def global_dir() -> str:
    override = os.environ.get(GLOBAL_DIR_ENV)
    if override:
        path = os.path.abspath(override)
    elif os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        path = os.path.join(base, "SelfShare")
    elif os.uname().sysname == "Darwin":
        path = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "SelfShare")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
        path = os.path.join(base, "selfshare")
    os.makedirs(path, exist_ok=True)
    return path


def mounts_file() -> str:
    return os.path.join(global_dir(), "mounts.json")


def config_path(folder: str) -> str:
    return os.path.join(os.path.abspath(folder), STATE_DIR, "config.json")


def read_config(folder: str) -> Dict[str, Any]:
    data = load_json(config_path(folder), None)
    if not isinstance(data, dict):
        raise FileNotFoundError(
            "此文件夹尚未初始化同步: %s\n请先运行 selfshare mount \"%s\" --url ... --vault ... --token ..."
            % (os.path.abspath(folder), folder)
        )
    return data


def write_config(folder: str, cfg: Dict[str, Any]) -> str:
    state_dir = os.path.join(os.path.abspath(folder), STATE_DIR)
    os.makedirs(state_dir, exist_ok=True)
    path = config_path(folder)
    payload = json.dumps(cfg, ensure_ascii=False, indent=2).encode("utf-8")
    atomic_write_bytes(path, payload)
    try:  # 0600 where supported
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def register_mount(folder: str) -> None:
    folder = os.path.abspath(folder)
    data = load_json(mounts_file(), {"mounts": []}) or {"mounts": []}
    entries: List[Dict[str, str]] = data.setdefault("mounts", [])
    entries = [e for e in entries if os.path.abspath(e.get("path", "")) != folder]
    cfg = read_config(folder)
    entries.append(
        {
            "path": folder,
            "url": cfg.get("url", ""),
            "vault": cfg.get("vault", ""),
        }
    )
    data["mounts"] = sorted(entries, key=lambda e: e["path"].lower())
    save_json(mounts_file(), data)


def unregister_mount(folder: str) -> None:
    folder = os.path.abspath(folder)
    data = load_json(mounts_file(), {"mounts": []}) or {"mounts": []}
    entries = [e for e in data.get("mounts", [])
               if os.path.abspath(e.get("path", "")) != folder]
    data["mounts"] = entries
    save_json(mounts_file(), data)


def known_mounts() -> List[Dict[str, str]]:
    data = load_json(mounts_file(), {"mounts": []}) or {"mounts": []}
    out = []
    for entry in data.get("mounts", []):
        path = os.path.abspath(entry.get("path", ""))
        if os.path.isdir(path) and os.path.exists(config_path(path)):
            out.append({"path": path, "url": entry.get("url", ""), "vault": entry.get("vault", "")})
    return out


def resolve_folder(folder: Optional[str], start: Optional[str] = None) -> str:
    """Find the mount root: explicit path, else walk up from cwd."""
    if folder:
        target = os.path.abspath(folder)
        for cand in _walk_up(target):
            if os.path.exists(config_path(cand)):
                return cand
        return target
    for cand in _walk_up(os.path.abspath(start or os.getcwd())):
        if os.path.exists(config_path(cand)):
            return cand
    raise FileNotFoundError(
        "当前目录不在任何已挂载的同步文件夹内，请显式指定目录，或用 selfshare list 查看挂载点"
    )


def _walk_up(path: str):
    current = os.path.abspath(path)
    while True:
        yield current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
