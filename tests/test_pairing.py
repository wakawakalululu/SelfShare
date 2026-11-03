"""配对码端到端测试：一条码完成挂载。"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from selfshare.client import Client, RemoteError
from selfshare.pairing import PairCodeStore, format_code
from selfshare.server import SyncServer
from selfshare.store import Registry
from selfshare.sync import LocalState, Syncer


class PairTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="ss-pair-")
        self.reg = Registry(self.root)
        self.reg.create_vault("work", token="tok-pair-1")
        self.server = SyncServer(("127.0.0.1", 0), self.root, quiet=True)
        self.port = self.server.server_address[1]
        self.url = "http://127.0.0.1:%d" % self.port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.root, ignore_errors=True)

    def _store(self):
        vault = self.reg.open_vault("work")
        try:
            return PairCodeStore(vault.path)
        finally:
            vault.close()

    def test_code_is_single_use(self):
        code = self._store().issue("work")["code"]
        info = Client.pair(self.url, code)
        self.assertEqual(info["vault"], "work")
        self.assertTrue(info["token"])
        with self.assertRaises(RemoteError):
            Client.pair(self.url, code)

    def test_code_accepts_loose_input(self):
        code = self._store().issue("work")["code"]
        loose = code.replace("-", "").lower()
        info = Client.pair(self.url, loose)
        self.assertEqual(info["vault"], "work")

    def test_expired_code_rejected(self):
        code = self._store().issue("work", ttl=60)["code"]
        # 直接把过期时间改到过去
        import json
        path = os.path.join(self.reg.vault_path("work"), "paircodes.json")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        for k in data["codes"]:
            data["codes"][k]["expires_at"] = 1
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        with self.assertRaises(RemoteError):
            Client.pair(self.url, code)

    def test_probe_detects_server(self):
        self.assertTrue(Client.probe(self.url))
        self.assertFalse(Client.probe("http://127.0.0.1:1"))

    def test_paired_mount_syncs(self):
        # A 上传一个文件
        fa = tempfile.mkdtemp(prefix="ss-pa-")
        try:
            st = LocalState(fa)
            st.close()
            from selfshare.config import write_config
            write_config(fa, {"url": self.url, "vault": "work",
                              "token": "tok-pair-1", "folder": fa})
            with Syncer(fa, Client(self.url, "work", "tok-pair-1")) as s:
                with open(os.path.join(fa, "a.txt"), "w", encoding="utf-8") as fh:
                    fh.write("hello pair")
                s.sync()

            # B 用配对码挂载并拉取
            fb = tempfile.mkdtemp(prefix="ss-pb-")
            try:
                code = self._store().issue("work")["code"]
                info = Client.pair(self.url, code)
                write_config(fb, {"url": self.url, "vault": info["vault"],
                                  "token": info["token"], "folder": fb})
                with Syncer(fb, Client(self.url, info["vault"], info["token"])) as s:
                    s.sync()
                with open(os.path.join(fb, "a.txt"), encoding="utf-8") as fh:
                    self.assertEqual(fh.read(), "hello pair")
            finally:
                shutil.rmtree(fb, ignore_errors=True)
        finally:
            shutil.rmtree(fa, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
