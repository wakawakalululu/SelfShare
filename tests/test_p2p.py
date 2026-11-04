"""P2P 集成测试：中心服务器认证 + 节点直连传输 blob。

需要可用的 python 与 selfshare.py；自动拉起服务端，不需要外部网络。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from selfshare.client import Client, RemoteError
from selfshare.peer import PeerNode
from selfshare.p2p import make_p2p_hmac, new_peer_id
from selfshare.server import SyncServer
from selfshare.store import Registry
from selfshare.util import sha256_file


def _free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class P2PServerFixture:
    def __init__(self):
        self.ext = None
        if os.environ.get("SELFSHARE_SERVER_BIN"):
            from external_server import ExternalServer

            self.ext = ExternalServer("p2p", "tok-p2p")
            self.ext.create_vault()
            self.root = self.ext.root
            self.url = self.ext.url
            return
        self.root = tempfile.mkdtemp(prefix="selfshare-p2p-server-")
        self.registry = Registry(self.root)
        self.registry.create_vault("p2p", token="tok-p2p")
        self.server = SyncServer(("127.0.0.1", 0), self.root, quiet=True)
        self.port = self.server.server_address[1]
        self.url = "http://127.0.0.1:%d" % self.port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def client(self) -> Client:
        return Client(self.url, "p2p", "tok-p2p", timeout=15)

    def stop(self):
        if self.ext is not None:
            self.ext.stop()
            return
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.root, ignore_errors=True)


class P2PTestCase(unittest.TestCase):
    def setUp(self):
        self.fx = P2PServerFixture()

    def tearDown(self):
        self.fx.stop()

    # --------------------------------------------------------------- tests ---
    def test_peer_register_heartbeat_discover(self):
        folder = tempfile.mkdtemp(prefix="selfshare-p2p-a-")
        try:
            # 先挂一个本地文件，让 peer 有 blob 可注册
            from selfshare.sync import Syncer
            with Syncer(folder, self.fx.client()) as s:
                with open(os.path.join(folder, "a.txt"), "w", encoding="utf-8") as fh:
                    fh.write("from A")
                s.sync()

            node = PeerNode(folder, self.fx.client(), quiet=True)
            listen = node.start()
            self.assertTrue(listen.startswith("127.0.0.1:") or ":" in listen)
            time.sleep(0.3)
            peers = self.fx.client().peers()
            self.assertEqual(len(peers), 1)
            self.assertEqual(peers[0]["peer_id"], node.peer_id)
            node.stop()
            time.sleep(0.2)
            peers = self.fx.client().peers()
            self.assertEqual(peers, [])
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_blob_transfers_over_p2p(self):
        fa = tempfile.mkdtemp(prefix="selfshare-p2p-fa-")
        fb = tempfile.mkdtemp(prefix="selfshare-p2p-fb-")
        try:
            from selfshare.sync import Syncer
            # A 上传文件
            with Syncer(fa, self.fx.client()) as sa:
                with open(os.path.join(fa, "shared.bin"), "wb") as fh:
                    fh.write(b"P2P" * 1000)
                sa.sync()
            digest = None
            # B 先通过服务器下载一次，确认 blob 在
            with Syncer(fb, self.fx.client()) as sb:
                sb.sync()
            src = os.path.join(fa, "shared.bin")
            dst = os.path.join(fb, "shared.bin")
            self.assertEqual(sha256_file(src), sha256_file(dst))

            # 现在 A 作为 peer 服务；B 直接用 P2P 拉取同一个 blob
            node = PeerNode(fa, self.fx.client(), quiet=True)
            node.start()
            try:
                digest = sha256_file(src)
                out = os.path.join(fb, "via-p2p.bin")
                client = self.fx.client()
                peers = client.peers()
                self.assertEqual(len(peers), 1)
                client.get_blob_p2p(digest, out, peers[0]["listen"], peers[0]["peer_id"])
                self.assertEqual(sha256_file(out), digest)
            finally:
                node.stop()
        finally:
            shutil.rmtree(fa, ignore_errors=True)
            shutil.rmtree(fb, ignore_errors=True)

    def test_hmac_rejects_wrong_token(self):
        folder = tempfile.mkdtemp(prefix="selfshare-p2p-sec-")
        try:
            from selfshare.sync import Syncer
            with Syncer(folder, self.fx.client()) as s:
                with open(os.path.join(folder, "x.txt"), "w", encoding="utf-8") as fh:
                    fh.write("secret")
                s.sync()
            node = PeerNode(folder, self.fx.client(), quiet=True)
            node.start()
            try:
                digest = sha256_file(os.path.join(folder, "x.txt"))
                # 用错误 token 构造 MAC
                bad = make_p2p_hmac("wrong-token", "p2p:" + node.peer_id, digest, "n")
                url = "http://%s/p2p/blob/%s?peer_id=%s&nonce=n" % (node.listen, digest, node.peer_id)
                import urllib.request
                req = urllib.request.Request(url, headers={"X-P2P-MAC": bad})
                with self.assertRaises(Exception):
                    urllib.request.urlopen(req, timeout=5)
            finally:
                node.stop()
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class BlobAdvertisementTestCase(unittest.TestCase):
    """节点启动之后同步到的新 blob 也要重新广播，并且默认发现响应保持精简。"""

    def setUp(self):
        self.fx = P2PServerFixture()

    def tearDown(self):
        self.fx.stop()

    def test_blobs_readvertised_after_refresh(self):
        folder = tempfile.mkdtemp(prefix="selfshare-p2p-adv-")
        try:
            from selfshare.sync import Syncer

            node = PeerNode(folder, self.fx.client(), quiet=True)
            node.start()
            time.sleep(0.2)

            with Syncer(folder, self.fx.client()) as s:
                with open(os.path.join(folder, "late.txt"), "w", encoding="utf-8") as fh:
                    fh.write("created after the peer started\n")
                s.sync()
            digest = sha256_file(os.path.join(folder, "late.txt"))

            node.refresh()
            holders = [p for p in self.fx.client().peers(with_blobs=True)
                       if digest in (p.get("blobs") or [])]
            self.assertEqual(len(holders), 1)
            self.assertNotIn("blobs", self.fx.client().peers()[0])
            node.stop()
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_peer_auth_failure_reports_status_not_unreachable(self):
        # 401 被当成"节点不可达"时，token 配错会被回退逻辑静默掩盖
        folder = tempfile.mkdtemp(prefix="selfshare-p2p-auth-")
        try:
            from selfshare.sync import Syncer

            with Syncer(folder, self.fx.client()) as s:
                with open(os.path.join(folder, "secret.txt"), "w", encoding="utf-8") as fh:
                    fh.write("needs the right token\n")
                s.sync()
            digest = sha256_file(os.path.join(folder, "secret.txt"))

            node = PeerNode(folder, self.fx.client(), quiet=True)
            listen = node.start()
            time.sleep(0.2)
            try:
                bad = Client(self.fx.url, "p2p", "wrong-token", timeout=10)
                dest = os.path.join(folder, "out.bin")
                with self.assertRaises(RemoteError) as ctx:
                    bad.get_blob_p2p(digest, dest, listen, node.peer_id)
                self.assertEqual(ctx.exception.status, 401)
                self.assertNotIn("unreachable", str(ctx.exception))
            finally:
                node.stop()
        finally:
            shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
