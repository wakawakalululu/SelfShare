"""End-to-end tests: real server thread, two client "hosts", real files.

Run with ``python -m pytest tests -q`` or plain ``python tests/test_sync.py``.
No third-party packages required; the pytest path is optional.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from selfshare.client import Client, RemoteError
from selfshare.server import SyncServer
from selfshare.store import Registry
from selfshare.sync import Syncer
from selfshare.util import sha256_file


def write(path: str, text: str, mtime: float | None = None) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


class ServerFixture:
    def __init__(self):
        self.ext = None
        if os.environ.get("SELFSHARE_SERVER_BIN"):
            # 整套用例改跑在外部服务端上（例如 Go 实现），验证协议与存储兼容
            from external_server import ExternalServer

            self.ext = ExternalServer("test", "tok-test-123")
            self.ext.create_vault()
            self.root = self.ext.root
            self.url = self.ext.url
            return
        self.root = tempfile.mkdtemp(prefix="selfshare-server-")
        self.registry = Registry(self.root)
        self.info = self.registry.create_vault("test", token="tok-test-123")
        self.server = SyncServer(("127.0.0.1", 0), self.root, quiet=True)
        self.port = self.server.server_address[1]
        self.url = "http://127.0.0.1:%d" % self.port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def client(self) -> Client:
        return Client(self.url, "test", "tok-test-123", timeout=30)

    def stop(self) -> None:
        if self.ext is not None:
            self.ext.stop()
            return
        self.server.shutdown()
        self.server.server_close()
        self.registry.close_all() if hasattr(self.registry, "close_all") else None
        shutil.rmtree(self.root, ignore_errors=True)


class SyncTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = ServerFixture()
        self.a = tempfile.mkdtemp(prefix="selfshare-hostA-")
        self.b = tempfile.mkdtemp(prefix="selfshare-hostB-")

    def tearDown(self) -> None:
        self.fx.stop()
        shutil.rmtree(self.a, ignore_errors=True)
        shutil.rmtree(self.b, ignore_errors=True)

    # ------------------------------------------------------------------ util ---
    def sync(self, folder: str):
        with Syncer(folder, self.fx.client()) as s:
            return s.sync()

    def sync_both(self):
        ra = self.sync(self.a)
        rb = self.sync(self.b)
        return ra, rb

    # ----------------------------------------------------------------- tests ---
    def test_upload_from_a_lands_on_b(self):
        write(os.path.join(self.a, "notes", "hello.txt"), "hello world")
        report = self.sync(self.a)
        self.assertEqual(len(report.pushes), 1, report.summary())
        self.assertEqual(report.errors, [])

        report_b = self.sync(self.b)
        self.assertEqual(len(report_b.pulls), 1, report_b.summary())
        self.assertEqual(read(os.path.join(self.b, "notes", "hello.txt")), "hello world")

    def test_two_way_edit_no_conflict(self):
        write(os.path.join(self.a, "doc.txt"), "v1")
        self.sync(self.a)
        self.sync(self.b)

        write(os.path.join(self.b, "doc.txt"), "v2 from B")
        self.sync(self.b)
        report = self.sync(self.a)
        self.assertEqual(report.conflicts, [])
        self.assertEqual(read(os.path.join(self.a, "doc.txt")), "v2 from B")

    def test_conflict_keeps_both_versions(self):
        write(os.path.join(self.a, "shared.txt"), "base")
        self.sync(self.a)
        self.sync(self.b)

        # both sides edit without syncing in between -> genuine conflict
        write(os.path.join(self.a, "shared.txt"), "A edition")
        write(os.path.join(self.b, "shared.txt"), "B edition")

        report_a = self.sync(self.a)
        self.assertEqual(report_a.conflicts, [], report_a.summary())
        self.assertEqual(len(report_a.pushes), 1, "A commits first, no conflict yet")

        # B is the second host to sync, so B detects the divergence
        report_b = self.sync(self.b)
        self.assertEqual(report_b.conflicts, ["shared.txt"], report_b.summary())

        self.sync(self.a)

        a_files = sorted(os.listdir(self.a))
        b_files = sorted(os.listdir(self.b))
        blob = ""
        for d in (self.a, self.b):
            for name in os.listdir(d):
                if name.endswith(".txt"):
                    blob += read(os.path.join(d, name))
        self.assertIn("A edition", blob, "A's version must survive somewhere")
        self.assertIn("B edition", blob, "B's version must survive somewhere")
        self.assertTrue(any("冲突副本" in n for n in a_files + b_files),
                        "expected a conflict copy, got %s / %s" % (a_files, b_files))
        # canonical name carries the version that reached the server first
        self.assertEqual(read(os.path.join(self.b, "shared.txt")), "A edition")
        # and both hosts converge on the same set of files after one more pass
        self.sync(self.b)
        self.assertEqual(sorted(os.listdir(self.a)), sorted(os.listdir(self.b)))

    def test_delete_propagates(self):
        write(os.path.join(self.a, "temp.txt"), "bye")
        self.sync(self.a)
        self.sync(self.b)
        self.assertTrue(os.path.exists(os.path.join(self.b, "temp.txt")))

        os.unlink(os.path.join(self.a, "temp.txt"))
        self.sync(self.a)
        report = self.sync(self.b)
        self.assertEqual(len(report.deletes_local), 1)
        self.assertFalse(os.path.exists(os.path.join(self.b, "temp.txt")))

    def test_delete_vs_edit_keeps_edit(self):
        write(os.path.join(self.a, "keep.txt"), "original")
        self.sync(self.a)
        self.sync(self.b)

        write(os.path.join(self.b, "keep.txt"), "important change")
        os.unlink(os.path.join(self.a, "keep.txt"))

        self.sync(self.a)   # A: local delete, remote unchanged -> server delete
        self.sync(self.b)   # B: local changed, remote deleted -> re-upload
        self.sync(self.a)   # A pulls it back
        self.assertTrue(os.path.exists(os.path.join(self.a, "keep.txt")))
        self.assertEqual(read(os.path.join(self.a, "keep.txt")), "important change")

    def test_ignore_rules_respected(self):
        write(os.path.join(self.a, ".selfshareignore"), "*.tmp\nbuild/\n")
        write(os.path.join(self.a, "keep.txt"), "keep")
        write(os.path.join(self.a, "scratch.tmp"), "nope")
        write(os.path.join(self.a, "build", "out.bin"), "nope")
        report = self.sync(self.a)
        pushed = sorted(report.pushes)
        self.assertIn("keep.txt", pushed)
        self.assertNotIn("scratch.tmp", pushed)
        self.assertNotIn("build/out.bin", pushed)

    def test_large_binary_roundtrip(self):
        payload = bytes(range(256)) * 8192  # 2 MiB, deterministic
        src = os.path.join(self.a, "blob.bin")
        with open(src, "wb") as fh:
            fh.write(payload)
        self.sync(self.a)
        self.sync(self.b)
        dst = os.path.join(self.b, "blob.bin")
        self.assertTrue(os.path.exists(dst))
        self.assertEqual(sha256_file(src), sha256_file(dst))

    def test_dedup_same_content_twice(self):
        write(os.path.join(self.a, "one.txt"), "identical")
        write(os.path.join(self.a, "two.txt"), "identical")
        self.sync(self.a)
        st = self.fx.client().stat()
        self.assertEqual(st["files"], 2)
        self.assertEqual(st["blobs"], 1, "identical content should share one blob")

    def test_history_and_restore(self):
        write(os.path.join(self.a, "v.txt"), "first")
        self.sync(self.a)
        write(os.path.join(self.a, "v.txt"), "second")
        self.sync(self.a)

        hist = self.fx.client().history("v.txt")["entries"]
        self.assertGreaterEqual(len(hist), 2)
        first_hash = hist[-1]["hash"]

        dest = os.path.join(self.a, "restored.txt")
        self.fx.client().get_blob(first_hash, dest)
        self.assertEqual(read(dest), "first")

    def test_bad_token_rejected(self):
        bad = Client(self.fx.url, "test", "wrong", timeout=10)
        with self.assertRaises(Exception):
            bad.stat()

    def test_missing_vault_rejected(self):
        bad = Client(self.fx.url, "does-not-exist", "tok-test-123", timeout=10)
        with self.assertRaises(Exception):
            bad.stat()

    def test_incremental_manifest(self):
        write(os.path.join(self.a, "x.txt"), "x")
        self.sync(self.a)
        head = self.fx.client().manifest(0)["head_rev"]
        write(os.path.join(self.a, "y.txt"), "y")
        self.sync(self.a)
        delta = self.fx.client().manifest(head)["entries"]
        self.assertEqual([e["path"] for e in delta], ["y.txt"])

    def test_noop_sync_is_stable(self):
        write(os.path.join(self.a, "stable.txt"), "same")
        self.sync(self.a)
        self.sync(self.b)
        report = self.sync(self.b)
        self.assertFalse(report.changed, report.summary())
        self.assertEqual(report.errors, [])

    def test_path_traversal_blocked(self):
        from selfshare.util import norm_rel

        with self.assertRaises(ValueError):
            norm_rel("../escape.txt")
        with self.assertRaises(ValueError):
            norm_rel("a/../../b.txt")

    def test_abs_path_cannot_escape_vault(self):
        """盘符/绝对路径会让 os.path.join 丢掉 root，必须拒绝（对齐 Rust/Go）。

        Server 存的是客户端发来的原始 rel；若只有 norm_rel，Windows 上
        ``C:/Windows/x.txt`` 会解析到 vault 之外，读写都会越界。
        POSIX 上 ``C:/...`` 不是盘符而是普通相对路径，不会逃逸 vault，
        因此期望行为按宿主 OS 区分（Rust / Go 同样按 OS 解析）。
        """
        from selfshare.util import abs_path

        root = tempfile.mkdtemp(prefix="selfshare-abs-")
        try:
            drives = ("C:/Windows/x.txt", "C:rel/x.txt", "D:/y.txt")
            if os.name == "nt":
                for escape in drives:
                    with self.assertRaises(ValueError, msg=escape):
                        abs_path(root, escape)
            else:
                # 盘符段在 POSIX 只是普通目录名；红线是「不逃出 vault」。
                for drive in drives:
                    resolved = abs_path(root, drive)
                    self.assertTrue(resolved.startswith(root + os.sep), resolved)
            for ok in ("a/b.txt", "sub/dir/名字.md"):
                resolved = abs_path(root, ok)
                self.assertTrue(resolved.startswith(root + os.sep), resolved)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_norm_rel_trims_surrounding_whitespace(self):
        """C3-1：整串首尾 trim 先于去 ./ 与前导 /；盘符 OS 分支见 C6-2。"""
        from selfshare.util import norm_rel, abs_path
        self.assertEqual(norm_rel("  a/b.txt  "), "a/b.txt")
        self.assertEqual(norm_rel("  .\\a\\./b//c/  "), "a/b/c")
        self.assertEqual(norm_rel("   "), "")
        root = tempfile.mkdtemp(prefix="selfshare-trim-")
        try:
            with self.assertRaises(ValueError):
                abs_path(root, "   ")
        finally:
            shutil.rmtree(root, ignore_errors=True)
        with self.assertRaises(ValueError):
            norm_rel("  ../escape  ")
        self.assertEqual(norm_rel("a\\b\\c.txt"), "a/b/c.txt")
        self.assertEqual(norm_rel("  a/b\\c.txt  "), norm_rel("a/b/c.txt"))

    def test_three_hosts_converge(self):
        c = tempfile.mkdtemp(prefix="selfshare-hostC-")
        try:
            write(os.path.join(self.a, "t1.txt"), "from A")
            self.sync(self.a)
            write(os.path.join(self.b, "t2.txt"), "from B")
            self.sync(self.b)
            with Syncer(c, self.fx.client()) as s:
                s.sync()
            self.assertEqual(read(os.path.join(c, "t1.txt")), "from A")
            self.assertEqual(read(os.path.join(c, "t2.txt")), "from B")
        finally:
            shutil.rmtree(c, ignore_errors=True)


class SymlinkSafetyTestCase(unittest.TestCase):
    """跟随符号链接会把同步目录之外的文件内容上传到服务端。"""

    def setUp(self):
        self.fx = ServerFixture()
        self.a = tempfile.mkdtemp(prefix="selfshare-link-")

    def tearDown(self):
        self.fx.stop()
        shutil.rmtree(self.a, ignore_errors=True)

    def test_symlink_target_content_is_not_uploaded(self):
        write(os.path.join(self.a, "real.txt"), "inside the folder\n")
        link = os.path.join(self.a, "link.txt")
        try:
            os.symlink(os.path.join(self.a, "real.txt"), link)
        except OSError:
            self.skipTest("本机不允许创建符号链接")

        with Syncer(self.a, self.fx.client()) as s:
            s.sync()

        remote = {e["path"] for e in self.fx.client().manifest().get("entries", [])}
        self.assertIn("real.txt", remote)
        self.assertNotIn("link.txt", remote)


class BulkUploadTestCase(unittest.TestCase):
    """批量上传：单项摘要造假不能连累同批其它项，也不能污染存储。"""

    def setUp(self):
        self.fx = ServerFixture()
        self.a = tempfile.mkdtemp(prefix="selfshare-bulk-")

    def tearDown(self):
        self.fx.stop()
        shutil.rmtree(self.a, ignore_errors=True)

    def test_bad_digest_only_fails_that_item(self):
        import base64
        import hashlib

        good = b"good content\n"
        good_hash = hashlib.sha256(good).hexdigest()
        bad_hash = hashlib.sha256(b"claimed\n").hexdigest()
        client = self.fx.client()
        res = client.put_blobs_bulk([
            (good_hash, good),
            (bad_hash, b"actually different\n"),   # 摘要与内容不符
        ])
        self.assertEqual(res["stored"], [good_hash])
        self.assertEqual(len(res["failed"]), 1)
        self.assertEqual(res["failed"][0]["hash"], bad_hash)
        self.assertTrue(client.has_blob(good_hash))
        self.assertFalse(client.has_blob(bad_hash), "造假项不应被写入存储")

    def test_bulk_and_serial_paths_agree(self):
        import hashlib

        payload = "same bytes\n"
        write(os.path.join(self.a, "f.txt"), payload)
        with Syncer(self.a, self.fx.client()) as s:
            s.sync()
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        self.assertTrue(self.fx.client().has_blob(digest))
        remote = {e["path"] for e in self.fx.client().manifest().get("entries", [])}
        self.assertIn("f.txt", remote)


    def test_falls_back_when_server_lacks_bulk(self):
        # 已发布的老服务端没有 /blobbulk，新客户端必须退回逐个 PUT
        client = self.fx.client()

        def unsupported(items):
            raise RemoteError("POST -> HTTP 404 unknown endpoint", 404)

        client.put_blobs_bulk = unsupported
        write(os.path.join(self.a, "s1.txt"), "bulk unsupported\n")
        write(os.path.join(self.a, "s2.txt"), "still lands\n")
        with Syncer(self.a, client) as s:
            report = s.sync()

        self.assertEqual(report.errors, [], "回退不应产生错误")
        self.assertFalse(client.bulk_supported)
        remote = {e["path"] for e in client.manifest().get("entries", [])}
        self.assertIn("s1.txt", remote)
        self.assertIn("s2.txt", remote)


if __name__ == "__main__":
    unittest.main(verbosity=2)
