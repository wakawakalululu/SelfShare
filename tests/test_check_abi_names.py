"""check_abi_names.py 的注入自测：仅标准库、只读仓库、篡改只在 tempdir 副本。

    python tests/test_check_abi_names.py -v
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "desktop" / "scripts" / "check_abi_names.py"

_spec = importlib.util.spec_from_file_location("check_abi_names_under_test", SCRIPT)
if _spec is None or _spec.loader is None:
    raise RuntimeError("无法加载 desktop/scripts/check_abi_names.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def _load(name: str) -> str:
    """只读真实仓库文件（绝不写入）。"""
    return (ROOT / mod.FILES[name]).read_text(encoding="utf-8")


class ParseInjectionTests(unittest.TestCase):
    """注入文本一律先落到 tempdir 副本再读出，调用可 import 的 parse_*。"""

    @staticmethod
    def _parse(fn, text: str):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "snippet.txt"
            path.write_text(text, encoding="utf-8")
            return fn(path.read_text(encoding="utf-8"))

    def test_comments_never_yield_ghost_symbols(self):
        # Dart：// 与 /* */ 注释里的假 lookup 不计入
        dart = """
        // lookupFunction<_A, _B>('ss_ghost_line')
        /* lookupFunction<_A, _B>('ss_ghost_block') */
        final x = lib.lookupFunction<_A, _B>('ss_real');
        """
        self.assertEqual(self._parse(mod.parse_dart, dart), {"ss_real"})

        # 头文件：注释里的假声明不计入
        header = """
        // SS_EXPORT char *ss_ghost_line(void);
        /* SS_EXPORT char *ss_ghost_block(void); */
        SS_EXPORT char *ss_real(void);
        """
        self.assertEqual(self._parse(mod.parse_header, header), {"ss_real"})

        # Python：# 注释里的假字面量不计入
        abi = "ABI_SYMBOLS = (\n    'ss_real',  # 'ss_ghost_hash'\n)\n"
        self.assertEqual(self._parse(mod.parse_abi, abi), {"ss_real"})

        # Rust：/// 与 // 注释里的假导出不计入
        rust = """
        /// #[no_mangle] pub extern "C" fn ss_ghost_doc() {}
        // #[no_mangle] pub extern "C" fn ss_ghost_line() {}
        #[no_mangle]
        pub unsafe extern "C" fn ss_real() {}
        """
        self.assertEqual(self._parse(mod.parse_rust, rust), {"ss_real"})

    def test_multiline_declarations_are_recognized(self):
        header = """
        SS_EXPORT char *
        ss_cross_line(
            const char *a,
            const char *b
        );
        /* 拆行 + 注释也不干扰 */
        """
        self.assertIn("ss_cross_line", self._parse(mod.parse_header, header))

        dart = """
        final y = lib.lookupFunction<
            _TwoArgNative,
            _TwoArgDart
          >(
            'ss_cross_line_lookup'
          );
        final z = lib.lookupFunction<Fn<Pointer>, _B>('ss_nested');
        """
        self.assertEqual(
            self._parse(mod.parse_dart, dart),
            {"ss_cross_line_lookup", "ss_nested"},
        )

    def test_abi_tokenize_ignores_comments_and_handles_nested_parens(self):
        text = """
        # ABI_SYMBOLS = ("ss_ghost_outside",)
        ABI_SYMBOLS = (
            "ss_a", ("ss_b", "ss_c"),  # "ss_ghost_hash"
            "ss_d",
        )
        OTHER = ("ss_not_in_block",)
        """
        self.assertEqual(
            self._parse(mod.parse_abi, text),
            {"ss_a", "ss_b", "ss_c", "ss_d"},
        )

    def test_rust_parses_all_real_exports(self):
        rust = self._parse(mod.parse_rust, _load("rust"))
        header = self._parse(mod.parse_header, _load("header"))
        self.assertEqual(rust, header)
        self.assertEqual(len(rust), 19)


class MainConsistencyTests(unittest.TestCase):
    def _run_main(self, root: Path):
        old = mod.ROOT
        mod.ROOT = root
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                rc = mod.main()
        finally:
            mod.ROOT = old
        return rc, buf.getvalue()

    def _run_with_mutation(self, mutate):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            for rel in mod.FILES.values():
                dst = root / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes((ROOT / rel).read_bytes())
            mutate(root)
            return self._run_main(root)

    def _replace_one(self, rel: str, old: str, new: str):
        def mutate(root: Path) -> None:
            target = root / rel
            text = target.read_text(encoding="utf-8")
            self.assertIn(old, text)
            target.write_text(text.replace(old, new, 1), encoding="utf-8")

        return self._run_with_mutation(mutate)

    def test_real_repo_four_way_ok(self):
        rc, out = self._run_main(ROOT)
        self.assertEqual(rc, 0, out)
        self.assertIn("header: 19 / dart: 19 / abi: 19 / rust: 19", out)
        self.assertIn("OK: 四方 C ABI 名称一致 (19)", out)

    def test_tampered_dart_lookup_is_mismatch(self):
        rc, out = self._replace_one(
            mod.FILES["dart"], "'ss_plan'", "'ss_plan_tampered'"
        )
        self.assertEqual(rc, 1, out)
        self.assertIn("MISMATCH", out)
        self.assertIn("missing in dart", out)
        self.assertIn("extra in dart", out)

    def test_missing_rust_export_is_mismatch(self):
        rc, out = self._replace_one(
            mod.FILES["rust"],
            'pub extern "C" fn ss_shutdown(',
            'pub extern "C" fn ss_shutdown_retired(',
        )
        self.assertEqual(rc, 1, out)
        self.assertIn("MISMATCH", out)
        self.assertIn("missing in rust", out)

    def test_empty_parse_never_silently_passes(self):
        rc, out = self._replace_one(
            mod.FILES["abi"], "ABI_SYMBOLS = (", "ABI_SYMBOLS = ()  # ("
        )
        self.assertEqual(rc, 1, out)
        self.assertIn("解析结果为空", out)
        self.assertNotIn("OK: 四方", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
