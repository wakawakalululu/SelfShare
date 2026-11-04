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
        # 旧服务端没有 /blobbulk；首次遇到 404 后退化为逐个 PUT
        self.bulk_supported = True

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

    def put_blobs_bulk(self, items) -> Dict[str, Any]:
        """一次提交多个小 blob，items 为 [(digest, bytes), ...]。

        小文件同步的瓶颈是请求数：上千个 1 KB 文件逐个 PUT 要几十秒。
        """
        import base64

        payload = {"blobs": [{"hash": digest,
                              "data": base64.b64encode(data).decode("ascii")}
                             for digest, data in items]}
        return self._json("POST", "blobbulk", payload)

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

    # ------------------------------------------------------------- pairing ---
    @staticmethod
    def pair(base_url: str, code: str, timeout: float = 20.0) -> Dict[str, Any]:
        """用配对码换取 vault 令牌。需要网络，不需要预先知道库名。"""
        import json as _json

        url = base_url.rstrip("/") + "/api/pair"
        payload = _json.dumps({"code": code}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json", "User-Agent": UA},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", "replace")
                body = _json.loads(body).get("error", body)
            except Exception:
                pass
            raise RemoteError("配对失败：%s" % (body or exc.code), exc.code) from None
        except urllib.error.URLError as exc:
            raise RemoteError("无法连接 %s：%s" % (base_url, exc.reason)) from None
        if not data.get("token"):
            raise RemoteError("配对响应缺少令牌")
        return data

    @staticmethod
    def probe(base_url: str, timeout: float = 8.0) -> bool:
        """检查地址是否为 SelfShare 服务端。"""
        import json as _json

        try:
            with urllib.request.urlopen(
                base_url.rstrip("/") + "/api/pair", timeout=timeout
            ) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
            return bool(data.get("service") == "selfshare")
        except Exception:
            return False

    # ---------------------------------------------------------------- p2p ---
    def peers(self, exclude_peer_id: Optional[str] = None,
              with_blobs: bool = False) -> list:
        query = "exclude=" + exclude_peer_id if exclude_peer_id else ""
        if with_blobs:
            query += ("&" if query else "") + "with_blobs=1"
        data = self._json("GET", "peers", query=query)
        return data.get("peers", [])

    def peer_register(self, peer_id: str, listen: str, blobs: list,
                      host_id: str, version: str = "1.0") -> dict:
        return self._json("POST", "peer/register", {
            "peer_id": peer_id, "listen": listen, "blobs": blobs,
            "host_id": host_id, "version": version,
        })

    def peer_heartbeat(self, peer_id: str, blob_count: int,
                       blobs: Optional[list] = None) -> dict:
        payload: Dict[str, Any] = {"peer_id": peer_id, "blob_count": blob_count}
        if blobs is not None:
            payload["blobs"] = blobs
        return self._json("POST", "peer/heartbeat", payload)

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
        except urllib.error.HTTPError as exc:
            # 保留状态码：401 是认证失败，不能和"节点不可达"混为一谈，
            # 否则 token 配错会被当成掉线而静默回退到中心服务器
            _silent_remove(tmp)
            raise RemoteError("peer %s returned %d: %s"
                              % (peer_listen, exc.code, exc.reason),
                              status=exc.code) from None
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
        peers = self.peers(exclude_peer_id=exclude_peer_id, with_blobs=True)
        # 优先试声明持有该 blob 的节点；不上报列表的节点（如 Rust）仍会作为兜底被尝试
        advertised = {p["peer_id"] for p in peers if digest in (p.get("blobs") or [])}
        peers.sort(key=lambda p: p["peer_id"] not in advertised)
        for peer in peers:
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
