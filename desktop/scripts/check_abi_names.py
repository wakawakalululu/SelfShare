"""只读校验 Rust C ABI 四方名称一致：C 头文件 / Dart lookup / Python 冒烟清单 / Rust 导出。

用法（任意 cwd 均可，路径由 __file__ 推出）：
    python desktop/scripts/check_abi_names.py

四方来源（相对仓库根）：
  - desktop/core/include/selfshare_core.h : SS_EXPORT 声明的 ss_*
  - desktop/app/lib/rust_bridge.dart      : lookupFunction<...>('ss_*')
  - tests/test_core_dll.py                : ABI_SYMBOLS 赋值里的字符串字面量
  - desktop/core/src/ffi.rs               : #[no_mangle] pub ... extern "C" fn ss_*

契约对应（docs/contracts/abi-ipc.md）：
  - C5-1：C ABI 声明面以 selfshare_core.h 为基准；本脚本只读取「名字」，
    不解析返回形状，且把四方平等比对，避免掩盖下游独有符号；数量由解析
    结果推出，不写死。
  - C5-6：新增 ABI 须同步多处声明面，代码侧 4 方（Rust 导出 / 头文件 /
    Dart 绑定 / Python 冒烟清单）由本脚本自动守名；文档侧（desktop/README.md、
    docs/gui.md）属文档口径，有意不纳入扫描面以免脚本对措辞敏感。

只读声明面检查：不改 C ABI 声明 / 返回形状 / 数量，不改 IPC，不写任何文件，
不联网，不调用 git，仅标准库；四方不等时打印差异并 exit 1。
"""

from __future__ import annotations

import io
import re
import sys
import tokenize
from pathlib import Path

# 本文件在 <root>/desktop/scripts/，parents[2] 即仓库根（上溯两级）：
# parents[0]=scripts, parents[1]=desktop, parents[2]=<root>。
ROOT = Path(__file__).resolve().parents[2]

FILES = {
    "header": "desktop/core/include/selfshare_core.h",
    "dart": "desktop/app/lib/rust_bridge.dart",
    "abi": "tests/test_core_dll.py",
    "rust": "desktop/core/src/ffi.rs",
}
LABELS = ("header", "dart", "abi", "rust")

# 通用注释剥离：字符串字面量优先匹配（保留），// 与 /* */ 注释删除。
# 头文件 / Dart 用单双引号版（Dart 的 'ss_xxx' 是单引号字符串）；
# Rust 用仅双引号版，避免生命周期标记 <'a> 被误当成字符串起点而漏剥注释，
# 同时保护 "http://" / "C" 这类含 // 或引号的双引号字符串。
# 已知边界：不处理 Dart 三引号字符串 / Rust 原始字符串 r#"..."#（本仓库未出现）。
_C_COMMENTS = re.compile(
    r"""("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|/\*.*?\*/|//[^\n]*""", re.S
)
_RUST_COMMENTS = re.compile(
    r"""("(?:\\.|[^"\\])*")|/\*.*?\*/|//[^\n]*""", re.S
)


def _strip_comments(text: str, *, single_quotes: bool = True) -> str:
    pattern = _C_COMMENTS if single_quotes else _RUST_COMMENTS
    return pattern.sub(lambda m: m.group(1) or "", text)


# ① 头文件：剥注释后在「整段文本」上捕获 ss_xxx( ，兼容声明拆行/多行参数，
#    不再逐行只取 ';' 结尾（原型里的 ss_ 名称后紧跟 '('，不会误抓注释里的调用）。
_HEADER_NAME = re.compile(r"\b(ss_[A-Za-z0-9_]+)\s*\(")

# ② Dart：lookupFunction<Native, Dart>('ss_xxx')，剥注释后匹配。
#    (?:[^<>]|<[^<>]*>)* 配 re.S：既允许任意换行，也允许一层 <> 嵌套
#    （如 Pointer<Utf8>），不会被第一个 '>' 截断。现仓库 19 处泛型参数全是
#    typedef 标识符，无嵌套，故此简单正则足够，无需完整 Dart 泛型解析器。
_DART_LOOKUP = re.compile(
    r"lookupFunction\s*<(?:[^<>]|<[^<>]*>)*>\s*\(\s*['\"](ss_[A-Za-z0-9_]+)['\"]",
    re.S,
)

# ③ Python：tokenize 天然把 # 注释作为 COMMENT、字符串作为 STRING，
#    因此注释里的 'ss_ghost' 不计入；用括号深度计数定位整个 ABI_SYMBOLS
#    赋值，避免旧版非贪婪 \) 在首个右括号处截断。
_ABI_STRING = re.compile(r"['\"](ss_[A-Za-z0-9_]+)['\"]")

# ④ Rust：#[no_mangle] 后紧跟 pub [unsafe] extern "C" fn ss_xxx(。
#    先剥 // / /* */ 注释，文档注释里的假 fn 不会计入；允许中间夹其它属性。
_RUST_EXPORT = re.compile(
    r'#\s*\[\s*no_mangle\s*\]\s*'
    r'(?:#\s*\[[^\]]*\]\s*)*'
    r'pub\s+(?:unsafe\s+)?extern\s+"C"\s+fn\s+'
    r'(ss_[A-Za-z0-9_]+)\s*\('
)


def parse_header(text: str) -> set[str]:
    return set(_HEADER_NAME.findall(_strip_comments(text)))


def parse_dart(text: str) -> set[str]:
    return set(_DART_LOOKUP.findall(_strip_comments(text)))


def parse_abi(text: str) -> set[str]:
    names: set[str] = set()
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return names
    state = 0  # 0 找 NAME / 1 找 '=' / 2 找 '(' / 3 在赋值块内
    depth = 0
    for tok in tokens:
        if state == 0:
            if tok.type == tokenize.NAME and tok.string == "ABI_SYMBOLS":
                state = 1
        elif state == 1:
            if tok.type == tokenize.OP and tok.string == "=":
                state = 2
            elif tok.type in (tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT,
                              tokenize.INDENT, tokenize.DEDENT):
                pass
            else:
                state = 0
        elif state == 2:
            if tok.type == tokenize.OP and tok.string in "([{":
                depth, state = 1, 3
            elif tok.type in (tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT,
                              tokenize.INDENT, tokenize.DEDENT):
                pass
            else:
                state = 0
        else:  # state == 3
            if tok.type == tokenize.STRING:
                match = _ABI_STRING.search(tok.string)
                if match:
                    names.add(match.group(1))
            elif tok.type == tokenize.OP:
                if tok.string in "([{":
                    depth += 1
                elif tok.string in ")]}":
                    depth -= 1
                    if depth == 0:
                        state = 0
    return names


def parse_rust(text: str) -> set[str]:
    cleaned = _strip_comments(text, single_quotes=False)
    return set(_RUST_EXPORT.findall(cleaned))


def main() -> int:
    try:
        texts = {
            key: (ROOT / rel).read_text(encoding="utf-8")
            for key, rel in FILES.items()
        }
    except OSError as exc:
        print(f"ERROR: 无法读取源文件: {exc}")
        return 1

    sides = {
        "header": parse_header(texts["header"]),
        "dart": parse_dart(texts["dart"]),
        "abi": parse_abi(texts["abi"]),
        "rust": parse_rust(texts["rust"]),
    }

    print(" / ".join(f"{label}: {len(sides[label])}" for label in LABELS))

    # 防止正则/tokenize 失效导致 0/0/0/0 被误判为一致。
    empty = [label for label in LABELS if not sides[label]]
    if empty:
        print("ERROR: 解析结果为空（源文件形态已变化？）: " + ", ".join(empty))
        return 1

    union = set().union(*sides.values())
    common = set.intersection(*sides.values())
    if union == common:  # 并集等于交集 <=> 四方集合相等
        print(f"OK: 四方 C ABI 名称一致 ({len(union)})")
        return 0

    # missing in X：并集中有、X 没有；extra in X：X 有、但非四方共有。
    print("MISMATCH")
    for label in LABELS:
        missing = sorted(union - sides[label])
        extra = sorted(sides[label] - common)
        if missing:
            print(f"missing in {label}: {', '.join(missing)}")
        if extra:
            print(f"extra in {label}: {', '.join(extra)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
