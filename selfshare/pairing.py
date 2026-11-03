"""配对码：让「加一台设备」变成输入一串短码。

后台逻辑
--------
「配对码」把 vault + 令牌 + 服务端地址打包成一个短字符串，例如::

    SS-7K3PQ-9WD2M

它只是**一次性搬运载体**，不是长期凭证：

- 有效期内可换取真实的 vault 令牌
- 兑换后立即作废（一次性）
- 过期自动失效（默认 30 分钟）
- 服务端可随时吊销全部未使用的码

因此即使配对码泄露，攻击窗口也很短，且兑换后令牌不会再暴露在码里。
"""

from __future__ import annotations

import json
import os
import secrets
import time
from typing import Any, Dict, List, Optional

from .util import atomic_write_bytes, load_json

# 去掉易混淆字符 0/O、1/I/L
ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
CODE_PREFIX = "SS"
GROUP = 4
GROUPS = 3

FILE = "paircodes.json"
DEFAULT_TTL = 1800.0
MAX_TTL = 86400.0


def _normalise(code: str) -> str:
    """容忍用户输入的空格、小写、缺少分组符。"""
    text = "".join(ch for ch in (code or "").upper() if ch.isalnum())
    if text.startswith(CODE_PREFIX):
        text = text[len(CODE_PREFIX):]
    return text


def _random_code() -> str:
    raw = "".join(secrets.choice(ALPHABET) for _ in range(GROUP * GROUPS))
    return "-".join(raw[i:i + GROUP] for i in range(0, len(raw), GROUP))


def format_code(code: str) -> str:
    """统一显示成 SS-XXXX-XXXX-XXXX。"""
    body = _normalise(code)
    grouped = "-".join(body[i:i + GROUP] for i in range(0, len(body), GROUP))
    return "%s-%s" % (CODE_PREFIX, grouped)


class PairCodeStore:
    """服务端保存的配对码表（按 vault 分文件）。"""

    def __init__(self, vault_root: str):
        self.path = os.path.join(vault_root, FILE)

    def _load(self) -> Dict[str, Any]:
        data = load_json(self.path, {"codes": {}}) or {"codes": {}}
        data.setdefault("codes", {})
        return data

    def _save(self, data: Dict[str, Any]) -> None:
        atomic_write_bytes(
            self.path, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        )

    def _prune(self, data: Dict[str, Any], vault_id: str) -> None:
        now = time.time()
        for key in list(data["codes"]):
            item = data["codes"][key]
            if item.get("vault") != vault_id:
                continue
            if item.get("used") or item.get("expires_at", 0) < now:
                data["codes"].pop(key, None)

    def issue(self, vault_id: str, ttl: float = DEFAULT_TTL,
              note: str = "") -> Dict[str, Any]:
        ttl = max(60.0, min(float(ttl or DEFAULT_TTL), MAX_TTL))
        data = self._load()
        self._prune(data, vault_id)
        code = _random_code()
        # 极小概率碰撞，重新生成
        for _ in range(8):
            if code not in data["codes"]:
                break
            code = _random_code()
        data["codes"][_normalise(code)] = {
            "vault": vault_id,
            "created_at": time.time(),
            "expires_at": time.time() + ttl,
            "used": False,
            "note": note,
        }
        self._save(data)
        return {
            "code": format_code(code),
            "raw": code,
            "expires_in": int(ttl),
            "expires_at": time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(time.time() + ttl)
            ),
        }

    def redeem(self, code: str) -> Optional[Dict[str, Any]]:
        key = _normalise(code)
        if not key:
            return None
        data = self._load()
        item = data["codes"].get(key)
        if not item:
            return None
        if item.get("used"):
            return None
        if item.get("expires_at", 0) < time.time():
            data["codes"].pop(key, None)
            self._save(data)
            return None
        item["used"] = True
        item["used_at"] = time.time()
        self._save(data)
        return {"vault": item["vault"], "note": item.get("note", "")}

    def list_active(self, vault_id: str) -> List[Dict[str, Any]]:
        data = self._load()
        self._prune(data, vault_id)
        self._save(data)
        now = time.time()
        out = []
        for raw, item in data["codes"].items():
            if item.get("vault") != vault_id or item.get("used"):
                continue
            out.append({
                "code": format_code(raw),
                "expires_in": max(0, int(item["expires_at"] - now)),
                "note": item.get("note", ""),
            })
        out.sort(key=lambda x: x["expires_in"])
        return out

    def revoke_all(self, vault_id: str) -> int:
        data = self._load()
        before = len(data["codes"])
        data["codes"] = {
            k: v for k, v in data["codes"].items() if v.get("vault") != vault_id
        }
        removed = before - len(data["codes"])
        self._save(data)
        return removed
