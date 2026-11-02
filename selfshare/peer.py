"""P2P 节点服务：在本机监听，供其他已认证 peer 直连拉取 blob。

认证流程（不落 token 明文到网络）：

1. 客户端每次请求带 ``X-P2P-MAC = HMAC(token, vault_id:peer_id:digest:nonce)``
2. 服务端用同 vault 的 token 重算并比对
3. nonce 每次随机，防止重放

节点只提供已同步到本地的 blob 内容，元数据仍由中心服务器管理。
"""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from .client import Client, RemoteError
from .p2p import HEARTBEAT, PEER_TTL, make_p2p_hmac, new_peer_id
from .sync import LocalState
from .util import sha256_file, human_size, now_iso


class PeerHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "SelfSharePeer/1.0"

    @property
    def peer(self) -> "PeerNode":
        return self.server.peer  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:
        if self.peer.quiet:
            return
        print("[%s] peer %s %s" % (now_iso(), self.address_string(), fmt % args), flush=True)

    def _send_json(self, code: int, obj: Any) -> None:
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        parts = [p for p in parsed.path.split("/") if p]
        query = parse_qs(parsed.query)
        if parts[:2] == ["p2p", "ping"]:
            self._send_json(200, {"ok": True, "peer_id": self.peer.peer_id,
                                  "vault": self.peer.vault_id, "time": now_iso()})
            return
        if parts[:2] == ["p2p", "blob"] and len(parts) >= 3:
            digest = parts[2].lower()
            if not self._authorised(query):
                self._send_json(401, {"error": "unauthorised"})
                return
            self._serve_blob(digest)
            return
        self._send_json(404, {"error": "not found"})

    def _authorised(self, query: dict) -> bool:
        peer_id = (query.get("peer_id") or [""])[0]
        nonce = (query.get("nonce") or [""])[0]
        mac = self.headers.get("X-P2P-MAC", "")
        if not peer_id or not nonce or not mac:
            return False
        expected = make_p2p_hmac(
            self.peer.token,
            self.peer.vault_id + ":" + peer_id,
            (parsed := urlparse(self.path)).path.rsplit("/", 1)[-1],
            nonce,
        )
        return secrets.compare_digest(expected, mac)

    def _serve_blob(self, digest: str) -> None:
        path = self.peer.blob_path(digest)
        if not path or not os.path.exists(path):
            self._send_json(404, {"error": "blob not found"})
            return
        size = os.path.getsize(path)
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(size))
        self.end_headers()
        with open(path, "rb") as fh:
            while True:
                block = fh.read(1 << 20)
                if not block:
                    break
                self.wfile.write(block)


class PeerNode:
    """一个本地 P2P 节点：注册到中心服务器，并监听给其他 peer 提供 blob。"""

    def __init__(self, folder: str, client: Client, quiet: bool = False):
        self.folder = folder
        self.client = client
        self.vault_id = client.vault_id
        self.token = client.token
        self.quiet = quiet
        self.peer_id = new_peer_id()
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._beat: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.listen = ""

    # ------------------------------------------------------------ lifecycle ---
    def start(self, host: str = "0.0.0.0", port: int = 0) -> str:
        self._server = ThreadingHTTPServer((host, port), PeerHandler)
        self._server.peer = self  # type: ignore[attr-defined]
        actual_port = self._server.server_address[1]
        # 用本机对外 IP 广播，让其他主机能找到
        adv_host = host if host not in ("0.0.0.0", "::") else self._outbound_ip()
        self.listen = "%s:%d" % (adv_host, actual_port)

        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self._register()
        self._beat = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._beat.start()
        return self.listen

    def stop(self) -> None:
        self._stop.set()
        try:
            self.client.peer_unregister(self.peer_id)
        except RemoteError:
            pass
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        if self._thread:
            self._thread.join(timeout=3)
        if self._beat:
            self._beat.join(timeout=3)

    # -------------------------------------------------------------- serving ---
    def blob_path(self, digest: str) -> Optional[str]:
        """把 blob 哈希映射到本地文件。blob 就是当前目录下的某个文件内容。"""
        # 每次请求重新打开 LocalState，避免 SQLite 跨线程访问。
        from .sync import LocalState as _LS
        st = _LS(self.folder)
        try:
            base = st.load()
        finally:
            st.close()
        for rel, entry in base.items():
            if entry.hash == digest and not entry.deleted:
                full = os.path.join(self.folder, *rel.split("/"))
                if os.path.isfile(full):
                    return full
        return None

    # --------------------------------------------------------- registration ---
    def _local_blobs(self) -> list:
        from .sync import LocalState as _LS
        st = _LS(self.folder)
        try:
            base = st.load()
        finally:
            st.close()
        out = []
        for rel, entry in base.items():
            if entry.hash and not entry.deleted:
                full = os.path.join(self.folder, *rel.split("/"))
                if os.path.isfile(full):
                    out.append(entry.hash)
        return out

    def _register(self) -> None:
        from .sync import LocalState as _LS
        st = _LS(self.folder)
        try:
            host_id = st.host_id
        finally:
            st.close()
        self.client.peer_register(
            self.peer_id, self.listen, self._local_blobs(), host_id
        )
        if not self.quiet:
            print("[peer] registered as %s at %s (%d blobs)"
                  % (self.peer_id, self.listen, len(self._local_blobs())), flush=True)

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(HEARTBEAT):
            try:
                self.client.peer_heartbeat(self.peer_id, len(self._local_blobs()))
            except RemoteError:
                pass

    def _outbound_ip(self) -> str:
        """发往服务端的目标 IP，取本机出口地址用于广播。"""
        try:
            from urllib.parse import urlparse

            target = urlparse(self.client.base_url).hostname or "8.8.8.8"
            with __import__("socket").socket(__import__("socket").AF_INET,
                                             __import__("socket").SOCK_DGRAM) as s:
                s.connect((target, 80))
                return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"
