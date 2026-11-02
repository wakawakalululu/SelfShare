"""P2P 节点认证、注册与发现。

设计原则（认证在中心，数据在节点）：

1. 中心服务器继续负责：vault 管理、令牌签发、提交元数据、blob 兜底存储。
2. 节点注册自己的 listen 地址 + 持有哪些 blob 的哈希。
3. 其他节点通过 `/api/v/<vault>/peers` 发现节点，再用
   `http://peer/p2p/blob/<sha256>` 直连拉取。
4. 节点间通信用 vault token 的 HMAC 做双向验证，不暴露 token 明文。

离线/不可达的节点自动过期；节点不可达时客户端自动回退到中心服务器。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any, Dict, List, Optional

from .util import atomic_write_bytes, load_json

PEER_FILE = "peers.json"
PEER_TTL = 300.0          # 秒，超过即视为离线
HEARTBEAT = 30.0          # 客户端建议的心跳间隔


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class PeerRegistry:
    """服务端维护的节点注册表。

    每条记录::

        {"peer_id","listen","blobs","vault","last_seen","host_id","version"}

    单独存在 vault 根目录下，不写进 vault.db，因为注册表是易变的运行时状态，
    而 vault.db 是持久元数据。
    """

    def __init__(self, vault_root: str):
        self.path = os.path.join(vault_root, PEER_FILE)

    def _load(self) -> Dict[str, Any]:
        return load_json(self.path, {"peers": []}) or {"peers": []}

    def _save(self, data: Dict[str, Any]) -> None:
        atomic_write_bytes(self.path, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))

    def register(self, vault_id: str, token: str, peer_id: str, listen: str,
                 blobs: List[str], host_id: str, version: str) -> Dict[str, Any]:
        data = self._load()
        now = time.time()
        peers = [p for p in data["peers"] if not (p["peer_id"] == peer_id and p["vault"] == vault_id)]
        peers.append({
            "peer_id": peer_id,
            "listen": listen,
            "blobs": blobs[:50000],
            "blob_count": len(blobs),
            "vault": vault_id,
            "last_seen": now,
            "host_id": host_id,
            "version": version,
        })
        data["peers"] = peers
        self._save(data)
        return {"peer_id": peer_id, "vault": vault_id, "registered": True, "ttl": PEER_TTL}

    def heartbeat(self, vault_id: str, peer_id: str, blob_count: int) -> Dict[str, Any]:
        data = self._load()
        now = time.time()
        found = None
        for p in data["peers"]:
            if p["peer_id"] == peer_id and p["vault"] == vault_id:
                p["last_seen"] = now
                p["blob_count"] = blob_count
                found = p
        if found:
            self._save(data)
            return {"ok": True, "ttl": PEER_TTL}
        return {"ok": False, "error": "peer not registered"}

    def unregister(self, vault_id: str, peer_id: str) -> Dict[str, Any]:
        data = self._load()
        data["peers"] = [p for p in data["peers"]
                         if not (p["peer_id"] == peer_id and p["vault"] == vault_id)]
        self._save(data)
        return {"ok": True}

    def discover(self, vault_id: str, exclude_peer_id: Optional[str] = None) -> List[Dict[str, Any]]:
        data = self._load()
        now = time.time()
        out = []
        for p in data["peers"]:
            if p["vault"] != vault_id:
                continue
            if now - p["last_seen"] > PEER_TTL:
                continue
            if exclude_peer_id and p["peer_id"] == exclude_peer_id:
                continue
            out.append({
                "peer_id": p["peer_id"],
                "listen": p["listen"],
                "blob_count": p["blob_count"],
                "host_id": p["host_id"],
                "version": p["version"],
                "last_seen": p["last_seen"],
            })
        out.sort(key=lambda p: -p["last_seen"])
        return out


def make_p2p_hmac(token: str, peer_id: str, digest: str, nonce: str) -> str:
    """P2P 消息认证码。

    token 不明文传输；服务端和节点各自用 token 计算 HMAC，
    覆盖 peer_id + blob 哈希 + nonce，防止重放。
    """
    msg = "%s:%s:%s" % (peer_id, digest, nonce)
    return hmac.new(token.encode("utf-8"), msg.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def new_peer_id() -> str:
    return secrets.token_hex(16)
