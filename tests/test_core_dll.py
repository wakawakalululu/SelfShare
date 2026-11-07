"""Rust 内核 DLL 冒烟测试：验证「CI 构建 -> 下载产物 -> 本地测试」循环中的产物可用性。

通过 `SELFSHARE_CORE_DLL` 指向 selfshare_core.dll（CI 产物 `selfshare-core-windows`
或 release 便携包内同名文件）时启用；未设置时整组跳过，
与 `external_server.py` 的 `SELFSHARE_SERVER_BIN` 门控同型：

    SELFSHARE_CORE_DLL=/path/to/selfshare_core.dll python tests/test_core_dll.py -v

只做无副作用的 ABI 冒烟（版本 / 初始化 / 关停 / 只读状态 / 不可达探测），不做挂载同步；
行为级验证由 Rust 侧 `cargo test`（CI L2）与桌面端覆盖。
"""

from __future__ import annotations

import ctypes
import json
import os
import unittest

DLL_PATH = os.environ.get("SELFSHARE_CORE_DLL")

# 与 desktop/core/include/selfshare_core.h 的 19 个导出一一对应；新增 ABI 时同步两处。
ABI_SYMBOLS = (
    "ss_free", "ss_init", "ss_version", "ss_mount", "ss_pair", "ss_probe",
    "ss_unmount", "ss_mount_info", "ss_find_mount", "ss_sync", "ss_plan",
    "ss_progress", "ss_watch_start", "ss_watch_stop", "ss_watch_status",
    "ss_history", "ss_restore", "ss_remote_stat", "ss_shutdown",
)


@unittest.skipUnless(DLL_PATH, "SELFSHARE_CORE_DLL 未设置：跳过 DLL 冒烟（下载 CI/release 产物后运行）")
class CoreDllTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dll = ctypes.WinDLL(DLL_PATH) if os.name == "nt" else ctypes.CDLL(DLL_PATH)
        cls.dll.ss_free.argtypes = [ctypes.c_void_p]
        cls.dll.ss_free.restype = None

    def _json_call(self, name):
        """调用无参 ABI：restype 用 void_p 保留指针所有权，解析后交还 ss_free。"""
        func = getattr(self.dll, name)
        func.argtypes = []
        func.restype = ctypes.c_void_p
        ptr = func()
        self.assertIsNotNone(ptr, "%s returned NULL" % name)
        try:
            return json.loads(ctypes.string_at(ptr).decode("utf-8"))
        finally:
            self.dll.ss_free(ptr)

    def _str_call(self, name, value):
        """调用单字符串参数 ABI；返回 UTF-8 JSON，指针同样交还 ss_free。"""
        func = getattr(self.dll, name)
        func.argtypes = [ctypes.c_char_p]
        func.restype = ctypes.c_void_p
        ptr = func(value.encode("utf-8"))
        self.assertIsNotNone(ptr, "%s returned NULL" % name)
        try:
            return json.loads(ctypes.string_at(ptr).decode("utf-8"))
        finally:
            self.dll.ss_free(ptr)

    def test_all_abi_symbols_present(self):
        # setUpClass 之外显式断言一次，失败信息更直观
        missing = [n for n in ABI_SYMBOLS if not hasattr(self.dll, n)]
        self.assertEqual(missing, [], "DLL 缺少导出符号")

    def test_version_reports_core_version_and_host_id(self):
        data = self._json_call("ss_version")
        # ss_version 直连 JSON（不走 ok_json 包装）；口径见 AGENTS.md §2：内核发行版本 1.0.0
        self.assertEqual(data.get("version"), "1.0.0")
        self.assertTrue(data.get("host_id"), "host_id 不应为空")

    @staticmethod
    def _unwrap(payload):
        """ok_json 形状：{\"ok\": true, \"data\": {...}}（ffi.rs::ok_json）。"""
        assert payload.get("ok") is True, payload
        return payload["data"]

    def test_init_idempotent_and_shutdown_clean(self):
        first = self._unwrap(self._json_call("ss_init"))
        self.assertEqual(first.get("version"), "1.0.0")
        second = self._unwrap(self._json_call("ss_init"))
        self.assertEqual(second.get("version"), "1.0.0")
        done = self._unwrap(self._json_call("ss_shutdown"))
        self.assertTrue(done.get("shutdown"))

    def test_progress_and_watch_status_are_plain_json(self):
        # ffi.rs:415 / :523 直接返回裸 JSON（不经 ok_json 包装），形状与 ok_json 不同
        progress = self._json_call("ss_progress")
        self.assertIsInstance(progress, dict, "ss_progress 应返回 JSON 对象")
        status = self._json_call("ss_watch_status")
        self.assertIsInstance(status, dict, "ss_watch_status 应返回 JSON 对象")
        self.assertIs(status.get("watching"), False, "未启动 watcher 时应为 false")

    def test_watch_stop_is_idempotent(self):
        # ffi.rs:501-514：未启动 watcher 时重复 stop 仍返回 ok_json，且不改变状态
        for _ in range(2):
            done = self._unwrap(self._json_call("ss_watch_stop"))
            self.assertIs(done.get("watching"), False)
        self.assertIs(self._json_call("ss_watch_status").get("watching"), False)

    def test_probe_unreachable_returns_false_without_crash(self):
        # client.rs:386-394：连接失败返回 false；不启动服务端，不读写任何数据
        data = self._unwrap(self._str_call("ss_probe", "http://127.0.0.1:1/"))
        self.assertIs(data.get("ok"), False, "不可达地址不应被判定为 SelfShare 服务端")


if __name__ == "__main__":
    unittest.main(verbosity=2)
