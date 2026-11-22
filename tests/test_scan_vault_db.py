"""存量库只读扫描器自测：desktop/scripts/scan_vault_db.py（O-1 / O-6 立项前置工具）。

夹具全部用临时 sqlite 文件构造（不触真实库、不联网）；加载方式与
test_check_abi_names.py 相同（importlib 直载脚本，便于 CI 与本地同口径）。
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "desktop" / "scripts" / "scan_vault_db.py"

_spec = importlib.util.spec_from_file_location("scan_vault_db_under_test", SCRIPT)
if _spec is None or _spec.loader is None:
    raise RuntimeError("无法加载 desktop/scripts/scan_vault_db.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def _fixture(rows: list[tuple[str, object]]) -> str:
    """建临时 vault.db（与真实 schema 的 rel 列对齐），返回路径。"""
    fd, path = tempfile.mkstemp(prefix="vault-", suffix=".db")
    import os

    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE files (rel TEXT PRIMARY KEY, hash TEXT, size INTEGER, mtime REAL, rev INTEGER)"
    )
    conn.execute(
        "CREATE TABLE versions (id INTEGER PRIMARY KEY AUTOINCREMENT, rel TEXT NOT NULL, hash TEXT, size INTEGER, rev INTEGER)"
    )
    for table, rel in rows:
        conn.execute(f"INSERT INTO {table} (rel) VALUES (?)", (rel,))  # noqa: S608 — 表名来自测试常量
    conn.commit()
    conn.close()
    return path


def _run_json(path: str) -> tuple[int, dict]:
    """跑 main --json，捕获 stdout 解析，返回 (exit_code, report)。"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = mod.main([path, "--json"])
    return code, json.loads(buf.getvalue())


class ScannerCategoryTests(unittest.TestCase):
    """判类函数：路线图两类的正反例 + NULL 防御类。"""

    def test_clean_rel_has_no_categories(self):
        self.assertEqual(mod.rel_categories("docs/readme.md"), [])
        self.assertEqual(mod.rel_categories("a/b/c.txt"), [])
        self.assertEqual(mod.rel_categories(""), [])  # 空串由上层拒绝，不属于扫描类

    def test_whitespace_leading_trailing_and_fullwidth(self):
        self.assertEqual(mod.rel_categories("  padded.txt"), ["whitespace"])
        self.assertEqual(mod.rel_categories("padded.txt\t"), ["whitespace"])
        self.assertEqual(mod.rel_categories("\u3000padded.txt"), ["whitespace"])  # 全角空格

    def test_drive_letter_both_separators_and_inner_segment(self):
        self.assertEqual(mod.rel_categories("C:/Users/evil.txt"), ["drive_letter"])
        self.assertEqual(mod.rel_categories("c:\\Users\\evil.txt"), ["drive_letter"])  # 反斜杠 + 小写
        self.assertEqual(mod.rel_categories("docs/C:trap.txt"), ["drive_letter"])  # 非首段
        self.assertNotEqual(
            mod.rel_categories("drive_letter_note.txt"), ["drive_letter"]
        )  # 文件名含字样不算

    def test_null_rel_gets_defensive_category(self):
        self.assertEqual(mod.rel_categories(None), ["null"])

    def test_combined_categories_are_ordered_and_complete(self):
        self.assertEqual(mod.rel_categories("  C:/x.txt "), ["whitespace", "drive_letter"])


class ScannerEndToEndTests(unittest.TestCase):
    """端到端：临时库 → main() --json → 退出码与结论逐项断言。"""

    def test_clean_db_exit_0_and_clean_conclusion(self):
        path = _fixture([("files", "docs/readme.md"), ("versions", "docs/readme.md")])
        try:
            code, report = _run_json(path)
            self.assertEqual(code, 0)
            self.assertTrue(report["conclusion"]["clean"])
            self.assertEqual(report["conclusion"]["counts"], {
                "whitespace": 0, "drive_letter": 0, "null": 0,
            })
            self.assertEqual(report["tables"]["files"]["total"], 1)
            self.assertEqual(report["tables"]["versions"]["total"], 1)
            self.assertEqual(report["tables"]["files"]["findings"], [])
        finally:
            Path(path).unlink(missing_ok=True)

    def test_anomalies_detected_with_table_attribution_and_exit_1(self):
        path = _fixture([
            ("files", "  padded.txt  "),      # whitespace
            ("files", "C:/Users/evil.txt"),   # drive_letter
            ("files", None),                  # null（防御类）
            ("versions", "docs\\C:trap.txt"), # 反斜杠盘符
        ])
        try:
            code, report = _run_json(path)
            self.assertEqual(code, 1)
            self.assertFalse(report["conclusion"]["clean"])
            counts = report["conclusion"]["counts"]
            self.assertEqual(counts["whitespace"], 1)
            self.assertEqual(counts["drive_letter"], 2)  # files 1 + versions 1（反斜杠形态）
            self.assertEqual(counts["null"], 1)
            files_findings = report["tables"]["files"]["findings"]
            self.assertEqual(len(files_findings), 3)
            by_cat = {c for f in files_findings for c in f["categories"]}
            self.assertEqual(by_cat, {"whitespace", "drive_letter", "null"})
            self.assertEqual(len(report["tables"]["versions"]["findings"]), 1)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_missing_tables_is_schema_error_exit_2(self):
        fd, path = tempfile.mkstemp(prefix="not-vault-", suffix=".db")
        import os

        os.close(fd)
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE other (x TEXT)")
        conn.commit()
        conn.close()
        try:
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                code = mod.main([path])
            self.assertEqual(code, 2)
            self.assertIn("缺少表", buf.getvalue())
        finally:
            Path(path).unlink(missing_ok=True)

    def test_readonly_open_refuses_writes_and_leaves_no_side_files(self):
        """只读红线：mode=ro 连接上执行写必须被拒绝；扫描后目录不留 -wal/-shm。"""
        path = _fixture([("files", "normal.txt")])
        conn = mod.open_ro(path)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("INSERT INTO files (rel) VALUES ('nope.txt')")
        finally:
            conn.close()
        parent = Path(path).parent
        leftovers = [p.name for p in parent.iterdir() if p.name.startswith(Path(path).name) and p.name != Path(path).name]
        self.assertEqual(leftovers, [])
        Path(path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
