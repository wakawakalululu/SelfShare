"""HTTP sync service.

Endpoints (all under ``/api/v/<vault>/``), authenticated by bearer token::

    GET    ping
    GET    manifest?since=<rev>          -> {"head_rev":N,"entries":[...]}
    POST   commit                        <- {"origin":"host","ops":[...]}
    GET    history?path=&limit=
    GET    stat
    PUT    blob/<sha256>                 <- raw body
    GET    blob/<sha256>                 -> raw body (supports Range)

The server never trusts client paths: every relative path is normalised and
rejected if it contains ``..``. Blobs are deduplicated by SHA-256, and the
client-supplied digest is verified against the received bytes.
"""

from __future__ import annotations

import json
import os
import socket
import ssl
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from .store import Conflict, Registry, Vault, valid_vault_id
from .util import human_size, now_iso, sha256_bytes

MAX_BODY = 2 * 1024 * 1024 * 1024  # 2 GiB single-blob ceiling


class HandlerError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class Handler(BaseHTTPRequestHandler):
    server_version = "SelfShare/1.0"
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------- plumbing ---
    @property
    def registry(self) -> Registry:
        return self.server.registry  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:
        if getattr(self.server, "quiet", False):
            return
        sys.stderr.write(
            "[%s] %s %s\n" % (now_iso(), self.address_string(), fmt % args)
        )

    def _send_json(self, code: int, obj: Any) -> None:
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_error_json(self, code: int, message: str) -> None:
        self._send_json(code, {"error": message})

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return b""
        if length > MAX_BODY:
            raise HandlerError(413, "body too large")
        chunks = []
        remaining = length
        while remaining > 0:
            block = self.rfile.read(min(remaining, 1 << 20))
            if not block:
                break
            chunks.append(block)
            remaining -= len(block)
        return b"".join(chunks)

    def _authorise(self, vault_id: str) -> None:
        header = self.headers.get("Authorization") or ""
        token = ""
        if header.lower().startswith("bearer "):
            token = header[7:].strip()
        if not token:
            token = (self.headers.get("X-Vault-Token") or "").strip()
        if not self.registry.check_token(vault_id, token):
            raise HandlerError(401, "invalid or missing token")

    # --------------------------------------------------------------- routes ---
    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_PUT(self) -> None:
        self._dispatch("PUT")

    def do_HEAD(self) -> None:
        self._dispatch("HEAD")

    def _dispatch(self, method: str) -> None:
        parsed = urlparse(self.path)
        parts = [p for p in parsed.path.split("/") if p]
        query = parse_qs(parsed.query)
        try:
            if parts[:1] == ["api"] and parts[1:2] == ["ping"]:
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "service": "selfshare",
                        "version": "1.0",
                        "vaults": len(self.registry.list_vaults()),
                        "time": now_iso(),
                    },
                )
                return

            if len(parts) < 4 or parts[0] != "api" or parts[1] != "v":
                raise HandlerError(404, "unknown endpoint %s" % self.path)
            vault_id = parts[2]
            if not valid_vault_id(vault_id) or not self.registry.exists(vault_id):
                raise HandlerError(404, "no such vault: %s" % vault_id)
            self._authorise(vault_id)
            action = parts[3]
            rest = parts[4:]
            vault = self.registry.open_vault(vault_id)
            try:
                if action == "manifest" and method in ("GET", "HEAD"):
                    since = int((query.get("since") or ["0"])[0] or 0)
                    self._send_json(200, vault.manifest(since))
                elif action == "commit" and method == "POST":
                    body = self._read_body()
                    try:
                        req = json.loads(body.decode("utf-8") or "{}")
                    except ValueError:
                        raise HandlerError(400, "commit body must be JSON")
                    ops = req.get("ops") or []
                    if not isinstance(ops, list) or len(ops) > 5000:
                        raise HandlerError(400, "ops must be a list of <=5000 items")
                    result = vault.commit(ops, origin=str(req.get("origin") or ""))
                    self._send_json(200, result)
                elif action == "history" and method in ("GET", "HEAD"):
                    rel = (query.get("path") or [None])[0]
                    limit = int((query.get("limit") or ["50"])[0])
                    self._send_json(200, {"entries": vault.history(rel, max(1, min(limit, 500)))})
                elif action == "stat" and method in ("GET", "HEAD"):
                    self._send_json(200, vault.stat())
                elif action == "blob" and rest:
                    digest = rest[0].lower()
                    if method == "PUT":
                        self._handle_put_blob(vault, digest)
                    elif method in ("GET", "HEAD"):
                        self._handle_get_blob(vault, digest, method == "HEAD")
                    else:
                        raise HandlerError(405, "method not allowed")
                elif action == "peers" and method == "GET":
                    from .p2p import PeerRegistry

                    preg = PeerRegistry(vault.path)
                    exclude = (query.get("exclude") or [None])[0] or None
                    self._send_json(200, {"peers": preg.discover(vault_id, exclude)})
                elif action == "peer" and rest and method == "POST":
                    sub = rest[0]
                    body = self._read_body()
                    try:
                        req = json.loads(body.decode("utf-8") or "{}")
                    except ValueError:
                        raise HandlerError(400, "peer body must be JSON")
                    from .p2p import PeerRegistry

                    preg = PeerRegistry(vault.path)
                    token = self.headers.get("Authorization", "").replace("Bearer ", "").strip()
                    if sub == "register":
                        result = preg.register(
                            vault_id, token,
                            peer_id=str(req.get("peer_id", "")),
                            listen=str(req.get("listen", "")),
                            blobs=list(req.get("blobs") or []),
                            host_id=str(req.get("host_id", "")),
                            version=str(req.get("version", "")),
                        )
                    elif sub == "heartbeat":
                        result = preg.heartbeat(
                            vault_id,
                            peer_id=str(req.get("peer_id", "")),
                            blob_count=int(req.get("blob_count") or 0),
                        )
                    elif sub == "unregister":
                        result = preg.unregister(vault_id, peer_id=str(req.get("peer_id", "")))
                    else:
                        raise HandlerError(404, "unknown peer action %s" % sub)
                    self._send_json(200, result)
                else:
                    raise HandlerError(404, "unknown endpoint %s" % self.path)
            finally:
                vault.close()
        except HandlerError as exc:
            self._send_error_json(exc.code, exc.message)
        except Conflict as exc:
            self._send_error_json(409, str(exc))
        except ValueError as exc:
            self._send_error_json(400, str(exc))
        except FileNotFoundError as exc:
            self._send_error_json(404, "not found: %s" % exc)
        except Exception:
            traceback.print_exc()
            self._send_error_json(500, "internal error")

    # --------------------------------------------------------------- blobs ---
    def _handle_put_blob(self, vault: Vault, digest: str) -> None:
        body = self._read_body()
        actual = sha256_bytes(body)
        if actual != digest:
            raise HandlerError(400, "digest mismatch: declared %s, body %s" % (digest, actual))
        vault.put_blob_bytes(body)
        self._send_json(200, {"ok": True, "hash": actual, "size": len(body)})

    def _handle_get_blob(self, vault: Vault, digest: str, head_only: bool) -> None:
        path = vault.blob_path(digest)
        if not os.path.exists(path):
            raise HandlerError(404, "blob not found")
        total = os.path.getsize(path)
        start, end = 0, total - 1
        range_header = self.headers.get("Range") or ""
        if range_header.startswith("bytes="):
            spec = range_header[6:].split(",")[0].strip()
            lo, _, hi = spec.partition("-")
            try:
                if lo:
                    start = int(lo)
                if hi:
                    end = min(int(hi), total - 1)
            except ValueError:
                start, end = 0, total - 1
            if start > end or start >= total:
                raise HandlerError(416, "range not satisfiable")
        length = end - start + 1
        self.send_response(206 if range_header else 200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        if range_header:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, total))
        self.end_headers()
        if head_only:
            return
        with open(path, "rb") as fh:
            fh.seek(start)
            remaining = length
            while remaining > 0:
                block = fh.read(min(remaining, 1 << 20))
                if not block:
                    break
                self.wfile.write(block)
                remaining -= len(block)


class SyncServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address) -> None:
        """客户端正常断开（keep-alive 关闭、RST）不是服务端错误。

        Rust/ureq 等客户端会用连接池并在空闲时直接关闭 socket，
        socketserver 默认会把 ConnectionResetError 打成完整堆栈，淹没真正的错误。
        """
        import sys as _sys

        exc = _sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)

    def __init__(self, address: Tuple[str, int], root: str, quiet: bool = False):
        super().__init__(address, Handler)
        self.registry = Registry(root)
        self.quiet = quiet


def serve(root: str, host: str = "0.0.0.0", port: int = 8484,
          certfile: Optional[str] = None, keyfile: Optional[str] = None,
          quiet: bool = False) -> None:
    server = SyncServer((host, port), root, quiet=quiet)
    scheme = "http"
    if certfile:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile, keyfile)
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
        scheme = "https"
    actual_host, actual_port = server.server_address[0], server.server_address[1]
    print("SelfShare server listening on %s://%s:%s" % (scheme, _display_host(host), actual_port))
    print("  data root : %s" % os.path.abspath(root))
    vaults = server.registry.list_vaults()
    print("  vaults    : %s" % (", ".join(vaults) if vaults else "(none yet)"))
    print("  press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        server.server_close()


def _display_host(host: str) -> str:
    if host in ("0.0.0.0", "::", ""):
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"
    return host
