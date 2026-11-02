"""Client-side HTTP transport."""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

UA = "SelfShare-Client/1.0"


class RemoteError(Exception):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


class Client:
    def __init__(self, base_url: str, vault_id: str, token: str, timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.vault_id = vault_id
        self.token = token
        self.timeout = timeout

    # ------------------------------------------------------------------ url ---
    def _url(self, action: str, tail: str = "") -> str:
        url = "%s/api/v/%s/%s" % (self.base_url, self.vault_id, action)
        if tail:
            url += "/" + tail.lstrip("/")
        return url

    def _request(self, method: str, url: str, data: Optional[bytes] = None,
                 headers: Optional[Dict[str, str]] = None,
                 timeout: Optional[float] = None) -> Tuple[int, bytes]:
        hdrs = {
            "Authorization": "Bearer " + self.token,
            "User-Agent": UA,
        }
        if headers:
            hdrs.update(headers)
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            body = b""
            try:
                body = exc.read()
            except Exception:
                pass
            detail = ""
            try:
                detail = json.loads(body.decode("utf-8")).get("error", "")
            except Exception:
                detail = body.decode("utf-8", "replace")[:200]
            raise RemoteError(
                "%s %s -> HTTP %s %s" % (method, url, exc.code, detail or ""), exc.code
            ) from None
        except urllib.error.URLError as exc:
            raise RemoteError("cannot reach %s: %s" % (self.base_url, exc.reason)) from None
        except socket.timeout:
            raise RemoteError("timeout talking to %s" % self.base_url) from None

    def _json(self, method: str, action: str, payload: Any = None,
              query: str = "", tail: str = "") -> Any:
        url = self._url(action, tail)
        if query:
            url += "?" + query
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        status, body = self._request(method, url, data=data, headers=headers)
        if not body:
            return {}
        return json.loads(body.decode("utf-8"))

    # --------------------------------------------------------------- api ---
    def ping(self) -> Dict[str, Any]:
        # Ping is unauthenticated; still fine to include the header.
        return self._json("GET", "stat")

    def manifest(self, since: int = 0) -> Dict[str, Any]:
        return self._json("GET", "manifest", query="since=%d" % since)

    def commit(self, ops, origin: str) -> Dict[str, Any]:
        return self._json("POST", "commit", {"origin": origin, "ops": ops})

    def history(self, path: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
        query = "limit=%d" % limit
        if path:
            from urllib.parse import quote

            query += "&path=" + quote(path)
        return self._json("GET", "history", query=query)

    def stat(self) -> Dict[str, Any]:
        return self._json("GET", "stat")

    def has_blob(self, digest: str) -> bool:
        try:
            self._request("HEAD", self._url("blob", digest), timeout=30)
            return True
        except RemoteError as exc:
            if exc.status == 404:
                return False
            raise

    def put_blob(self, digest: str, data: bytes) -> None:
        self._request(
            "PUT",
            self._url("blob", digest),
            data=data,
            headers={"Content-Type": "application/octet-stream"},
            timeout=max(120.0, self.timeout),
        )

    def put_blob_file(self, digest: str, path: str) -> None:
        """Stream a file to the server without loading it into memory."""
        size = os.path.getsize(path)
        url = self._url("blob", digest)
        headers = {
            "Authorization": "Bearer " + self.token,
            "User-Agent": UA,
            "Content-Type": "application/octet-stream",
            "Content-Length": str(size),
        }
        with open(path, "rb") as fh:
            req = urllib.request.Request(url, data=fh, headers=headers, method="PUT")
            try:
                with urllib.request.urlopen(req, timeout=max(300.0, self.timeout)) as resp:
                    resp.read()
            except urllib.error.HTTPError as exc:
                detail = ""
                try:
                    detail = exc.read().decode("utf-8", "replace")[:200]
                except Exception:
                    pass
                raise RemoteError(
                    "PUT blob %s -> HTTP %s %s" % (digest[:12], exc.code, detail), exc.code
                ) from None
            except urllib.error.URLError as exc:
                raise RemoteError("cannot reach %s: %s" % (self.base_url, exc.reason)) from None

    def get_blob(self, digest: str, dest_path: str) -> None:
        url = self._url("blob", digest)
        req = urllib.request.Request(
            url,
            headers={"Authorization": "Bearer " + self.token, "User-Agent": UA},
            method="GET",
        )
        tmp = dest_path + ".selfshare-tmp"
        os.makedirs(os.path.dirname(os.path.abspath(dest_path)) or ".", exist_ok=True)
        try:
            with urllib.request.urlopen(req, timeout=max(120.0, self.timeout)) as resp, open(
                tmp, "wb"
            ) as out:
                while True:
                    block = resp.read(1 << 20)
                    if not block:
                        break
                    out.write(block)
            os.replace(tmp, dest_path)
        except urllib.error.HTTPError as exc:
            _silent_remove(tmp)
            raise RemoteError("GET blob %s -> HTTP %s" % (digest[:12], exc.code), exc.code) from None
        except urllib.error.URLError as exc:
            _silent_remove(tmp)
            raise RemoteError("cannot reach %s: %s" % (self.base_url, exc.reason)) from None
        except BaseException:
            _silent_remove(tmp)
            raise

    # ---------------------------------------------------------------- p2p ---
    def peers(self, exclude_peer_id: Optional[str] = None) -> list:
        query = "exclude=" + exclude_peer_id if exclude_peer_id else ""
        data = self._json("GET", "peers", query=query)
        return data.get("peers", [])

    def peer_register(self, peer_id: str, listen: str, blobs: list,
                      host_id: str, version: str = "1.0") -> dict:
        return self._json("POST", "peer/register", {
            "peer_id": peer_id, "listen": listen, "blobs": blobs,
            "host_id": host_id, "version": version,
        })

    def peer_heartbeat(self, peer_id: str, blob_count: int) -> dict:
        return self._json("POST", "peer/heartbeat", {
            "peer_id": peer_id, "blob_count": blob_count,
        })

    def peer_unregister(self, peer_id: str) -> dict:
        return self._json("POST", "peer/unregister", {"peer_id": peer_id})

    def get_blob_p2p(self, digest: str, dest_path: str,
                     peer_listen: str, peer_id: str) -> None:
        """从某个 peer 直连拉取 blob，用 HMAC 认证，不暴露 token 明文。"""
        import secrets as _secrets
        from .p2p import make_p2p_hmac

        nonce = _secrets.token_hex(16)
        mac = make_p2p_hmac(self.token, self.vault_id + ":" + peer_id, digest, nonce)
        url = "http://%s/p2p/blob/%s?peer_id=%s&nonce=%s" % (
            peer_listen, digest, peer_id, nonce)
        req = urllib.request.Request(url, headers={
            "User-Agent": UA, "X-P2P-MAC": mac, "X-Vault-Id": self.vault_id,
        }, method="GET")
        tmp = dest_path + ".selfshare-p2p-tmp"
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp, open(tmp, "wb") as out:
                while True:
                    block = resp.read(1 << 20)
                    if not block:
                        break
                    out.write(block)
            os.replace(tmp, dest_path)
        except urllib.error.URLError as exc:
            _silent_remove(tmp)
            raise RemoteError("peer %s unreachable: %s" % (peer_listen, exc.reason)) from None
        except BaseException:
            _silent_remove(tmp)
            raise

    def get_blob_with_peers(self, digest: str, dest_path: str,
                            exclude_peer_id: Optional[str] = None) -> str:
        """优先从在线 peer 拉取，全部失败后回退到中心服务器。

        返回实际来源："peer:<listen>" 或 "server"。
        """
        peers = self.peers(exclude_peer_id=exclude_peer_id)
        for peer in peers:
            if digest not in peer.get("blobs", []) and peer.get("blob_count"):
                continue
            try:
                self.get_blob_p2p(digest, dest_path, peer["listen"], peer["peer_id"])
                return "peer:%s" % peer["listen"]
            except RemoteError:
                continue
        self.get_blob(digest, dest_path)
        return "server"


def _silent_remove(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass
