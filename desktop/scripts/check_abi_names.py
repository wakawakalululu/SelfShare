"""只读校验 Rust C ABI 三方名称一致：C 头文件 / Dart lookup / Python 冒烟清单。

用法（任意 cwd 均可，路径由 __file__ 推出）：
    python desktop/scripts/check_abi_names.py

三方来源（相对仓库根）：
  - desktop/core/include/selfshare_core.h : SS_EXPORT 声明的 ss_*
  - desktop/app/lib/rust_bridge.dart      : lookupFunction<...>('ss_*')
  - tests/test_core_dll.py                : ABI_SYMBOLS 元组内的字符串

契约对应（docs/contracts/abi-ipc.md）：
  - C5-1：C ABI 导出 19 个，清单以 selfshare_core.h:15-33 为准，ss_free 是唯一
    void 返回（其余为 char*）；本脚本只读取声明面的「名字」，不解析返回形状，
    且把头文件与 Dart / Python 平等比对，避免掩盖下游独有符号。
  - C5-6：新增 ABI 须同步 5 处，其中前 3 处（头文件 / Dart 绑定 / Python 冒烟
    清单）由本脚本自动守名；后 2 处（desktop/README.md、docs/gui.md）属文档
    口径，由文档侧维护，有意不纳入扫描面以免脚本对措辞敏感。

只读声明面检查：不改 C ABI 声明 / 返回形状 / 数量，不改 IPC，不写任何文件，
不联网，不调用 git，仅标准库；三方不等时打印差异并 exit 1。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# 本文件在 <root>/desktop/scripts/，parents[2] 即仓库根（上溯两级）：
# parents[0]=scripts, parents[1]=desktop, parents[2]=<root>。
ROOT = Path(__file__).resolve().parents[2]

FILES = {
    "header": "desktop/core/include/selfshare_core.h",
    "dart": "desktop/app/lib/rust_bridge.dart",
    "abi": "tests/test_core_dll.py",
}
LABELS = ("header", "dart", "abi")

# ① 头文件：先剥 /*...*/ 与 // 注释，再只取以 ';' 收尾的声明行，
#    捕获 ss_xxx( 中的函数名；兼容 `char *ss_xxx(` 与 `void ss_free(`。
_HEADER_NAME = re.compile(r"\b(ss_[A-Za-z0-9_]+)\s*\(")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"//[^\n]*")

# ② Dart：lookupFunction<Native, Dart>('ss_xxx')，赋值可能跨行，
#    故在整段文本上匹配；泛型参数是 typedef 名、不含嵌套 '>'。
_DART_LOOKUP = re.compile(
    r"lookupFunction\s*<[^>]*>\s*\(\s*['\"](ss_[A-Za-z0-9_]+)['\"]"
)

# ③ Python：只取 ABI_SYMBOLS = (...) 块内的字符串字面量，避免把文件里
#    其它 ss_* 调用、docstring、断言消息误算进来。
_ABI_BLOCK = re.compile(r"\bABI_SYMBOLS\s*=\s*\((.*?)\)", re.S)
_ABI_STRING = re.compile(r"['\"](ss_[A-Za-z0-9_]+)['\"]")


def parse_header(text: str) -> set[str]:
    text = _BLOCK_COMMENT.sub("", text)
    text = _LINE_COMMENT.sub("", text)
    names: set[str] = set()
    for line in text.splitlines():
        if not line.strip().endswith(";"):
            continue
        names.update(_HEADER_NAME.findall(line))
    return names


def parse_dart(text: str) -> set[str]:
    return set(_DART_LOOKUP.findall(text))


def parse_abi(text: str) -> set[str]:
    match = _ABI_BLOCK.search(text)
    if match is None:
        return set()
    body = _LINE_COMMENT.sub("", match.group(1))
    return set(_ABI_STRING.findall(body))


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
    }

    for label in LABELS:
        print(f"{label}: {len(sides[label])}")

    # 防止正则失效导致 0/0/0 被误判为一致。
    empty = [label for label in LABELS if not sides[label]]
    if empty:
        print("ERROR: 解析结果为空（源文件形态已变化？）: " + ", ".join(empty))
        return 1

    union = set().union(*sides.values())
    common = set.intersection(*sides.values())
    if union == common:  # 并集等于交集 <=> 三个集合相等
        print(f"OK: 三方 C ABI 名称一致 ({len(union)})")
        return 0

    # missing in X：并集中有、X 没有；extra in X：X 有、但非三方共有。
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
