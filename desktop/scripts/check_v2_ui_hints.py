#!/usr/bin/env python3
"""O-2/O-3 轻量 UI 接线的静态扫描（stdlib-only，无第三方依赖）。

在 CI（ci.yml v2-client job，Windows runner）中对仓库源码做只读检查：
1. O-2：设置页首次进入一次性提示（Settings.svelte 的 localStorage 一次性标记与提示正文）；
2. O-3：>512 MiB 大文件提示（commands.rs 的 list_large_files 命令与 512 MiB 阈值、
   lib.rs 注册、Dashboard.svelte 的前端接线）。

退出码：0 = 全部接线到位；1 = 有缺失。任何一项缺失说明 UI 增量被回退，门禁拦截。
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]

SETTINGS = ROOT / 'v2/client/src/pages/Settings.svelte'
DASHBOARD = ROOT / 'v2/client/src/pages/Dashboard.svelte'
COMMANDS = ROOT / 'v2/client/src-tauri/src/commands.rs'
LIB = ROOT / 'v2/client/src-tauri/src/lib.rs'

# (文件, 必须出现的标记, 说明)
REQUIRED = [
    (SETTINGS, 'ss_settings_first_visit_hint_shown', 'O-2 一次性标记（localStorage key）'),
    (SETTINGS, 'localStorage.getItem', 'O-2 一次性标记读取'),
    (SETTINGS, '首次使用提示', 'O-2 提示正文'),
    (SETTINGS, 'P2P 直连」默认关闭', 'O-2 裁决口径：P2P 保持默认关闭'),
    (DASHBOARD, 'list_large_files', 'O-3 前端调用 list_large_files'),
    (DASHBOARD, '大文件提示', 'O-3 大文件提示正文'),
    (DASHBOARD, 'estimateMinutes', 'O-3 预期时间估算'),
    (COMMANDS, 'list_large_files', 'O-3 list_large_files 命令定义'),
    (COMMANDS, 'LARGE_FILE_THRESHOLD', 'O-3 大文件阈值常量'),
    (COMMANDS, '512 * 1024 * 1024', 'O-3 阈值 = 512 MiB'),
    (LIB, 'commands::list_large_files', 'O-3 命令注册进 invoke_handler'),
]


def check(root: pathlib.Path = ROOT) -> list[str]:
    """返回缺失项列表（空列表 = 通过）。"""
    missing = []
    for path, marker, desc in REQUIRED:
        full = path if root == ROOT else root / path.relative_to(ROOT)
        try:
            text = full.read_text(encoding='utf-8')
        except OSError as e:
            missing.append(f'{path.name}: 无法读取（{e}）')
            continue
        if marker not in text:
            missing.append(f'{path.name}: 缺少 {desc}（标记 {marker!r}）')
    return missing


def main() -> int:
    missing = check()
    if missing:
        print('O-2/O-3 UI 接线静态扫描：发现缺失', file=sys.stderr)
        for m in missing:
            print(f'  - {m}', file=sys.stderr)
        return 1
    print(f'O-2/O-3 UI 接线静态扫描：通过（{len(REQUIRED)} 项标记齐全）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
