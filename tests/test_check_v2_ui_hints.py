"""O-2/O-3 轻量 UI 静态扫描自测：desktop/scripts/check_v2_ui_hints.py。

加载方式与 test_check_abi_names.py / test_scan_vault_db.py 相同（importlib 直载）。
正向用例对真实仓库源码跑 check()（应全部命中）；负向用例在临时目录篡改
接线标记（应逐类报缺失），证明扫描真的在断言而不是恒过。
"""

from __future__ import annotations

import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "desktop" / "scripts" / "check_v2_ui_hints.py"

_spec = importlib.util.spec_from_file_location("check_v2_ui_hints_under_test", SCRIPT)
if _spec is None or _spec.loader is None:
    raise RuntimeError("无法加载 desktop/scripts/check_v2_ui_hints.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


class CheckV2UiHintsTest(unittest.TestCase):
    def test_repo_passes(self):
        """真实仓库：O-2/O-3 接线标记齐全，check() 无缺失。"""
        self.assertEqual(mod.check(), [])

    def test_every_required_marker_maps_to_a_real_file(self):
        """标记表里的每个文件都必须真实存在（防止路径漂移导致空转）。"""
        for path, marker, desc in mod.REQUIRED:
            self.assertTrue(path.is_file(), f"{path} 不存在（{desc}）")
            self.assertTrue(marker, f"{desc} 的标记为空")

    def _copy_repo_layout(self, tmp: Path) -> Path:
        for path, _, _ in mod.REQUIRED:
            rel = path.relative_to(ROOT)
            dst = tmp / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(path, dst)
        return tmp

    def test_missing_o2_flag_reported(self):
        """篡改 Settings.svelte 的一次性标记 → 报 O-2 缺失。"""
        with tempfile.TemporaryDirectory() as td:
            root = self._copy_repo_layout(Path(td))
            s = root / mod.SETTINGS.relative_to(ROOT)
            s.write_text(
                s.read_text(encoding="utf-8").replace(
                    "ss_settings_first_visit_hint_shown", "removed_marker"
                ),
                encoding="utf-8",
            )
            missing = mod.check(root=root)
            self.assertTrue(any("Settings.svelte" in m for m in missing), missing)

    def test_missing_o3_command_reported(self):
        """篡改 commands.rs 的命令名 → 报 O-3 命令缺失。"""
        with tempfile.TemporaryDirectory() as td:
            root = self._copy_repo_layout(Path(td))
            c = root / mod.COMMANDS.relative_to(ROOT)
            c.write_text(
                c.read_text(encoding="utf-8").replace("list_large_files", "removed_fn"),
                encoding="utf-8",
            )
            missing = mod.check(root=root)
            self.assertTrue(
                any("commands.rs" in m and "list_large_files" in m for m in missing),
                missing,
            )

    def test_missing_threshold_reported(self):
        """篡改 512 MiB 阈值常量 → 报 O-3 阈值缺失。"""
        with tempfile.TemporaryDirectory() as td:
            root = self._copy_repo_layout(Path(td))
            c = root / mod.COMMANDS.relative_to(ROOT)
            c.write_text(
                c.read_text(encoding="utf-8").replace("512 * 1024 * 1024", "1 * 1 * 1"),
                encoding="utf-8",
            )
            missing = mod.check(root=root)
            self.assertTrue(any("512" in m for m in missing), missing)


if __name__ == "__main__":
    unittest.main()
