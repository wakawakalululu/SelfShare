"""存量同步库只读扫描：vault.db 的 files.rel / versions.rel 异常检测。

用法（任意 cwd 均可；只依赖标准库 sqlite3，不联网、不写库、不改任何文件）：
    python desktop/scripts/scan_vault_db.py <vault.db 路径> [--json] [--immutable]

背景（docs/decisions/OPEN-DECISIONS.md O-1 / O-6，PROJECT_STATUS §0.3 P1）：
  - C3-1 trim 口径落地（三端 2026-11-09 收敛）之前写入的历史库，rel 可能带
    「首尾空白」（旧实现原样入库）；
  - C3-1-6 把 `C:` 视作普通段（归一化层不拒绝），历史库可能存在「盘符 rel」
    （整串绝对 Windows 路径被当作 rel 入库，O-1 询问服务端是否应拒绝）；
  - O-6 未来是否立项的**前置条件** = 本扫描在部署环境执行并记录结论
    （结论记录进 CHANGELOG / PROJECT_STATUS，不改三端实现）。

扫描口径（正好覆盖路线图两类，不做多余判类）：
  1. whitespace   ：`rel != rel.strip()`（首或尾含空白，含制表 / 全角空格）
  2. drive_letter ：rel 任一段（`/` 与 `\\` 都视作分隔）以 `[A-Za-z]:` 开头
  另含防御类：
  3. null         ：rel 为 NULL（files.rel 为 TEXT PRIMARY KEY，SQLite 允许 NULL；
                     破坏 C3 主键语义，必须上报，不属于「多余判类」）

只读保证：
  - 默认以 URI `file:<path>?mode=ro` 打开（连接层拒绝写；不产生 -wal/-shm）；
  - `--immutable` 改用 `immutable=1`：被服务端持有 / WAL 未合并的库也能打开，
    代价是读不到尚未合并进主库的 WAL 内容（取舍已文档化，用于线上只读巡检）；
  - 全程只 SELECT。

退出码：0 = 扫描完成且无异常；1 = 扫描完成但发现异常；2 = 打不开库或缺表（schema 不符）。
`--json` 输出机器可读结论（含逐条 rel 与类别），便于部署环境批量采集。
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys

TABLES = ("files", "versions")
CATEGORIES = ("whitespace", "drive_letter", "null")
_DRIVE_SEGMENT = re.compile(r"^[A-Za-z]:")


def rel_categories(rel: object) -> list[str]:
    """对单个 rel 值判类；顺序固定为 CATEGORIES，便于稳定断言与批量采集。

    drive_letter 按段级去空白后判定：`"  C:/x "` 这类 rel 在 trim 后会**暴露**
    盘符段（O-6 的核心关切），只看原文会漏报。
    """
    cats: list[str] = []
    if rel is None:
        return ["null"]
    text = str(rel)
    if text != text.strip():
        cats.append("whitespace")
    segments = text.replace("\\", "/").split("/")
    if any(_DRIVE_SEGMENT.match(seg.strip()) for seg in segments):
        cats.append("drive_letter")
    return cats


def scan_connection(conn: sqlite3.Connection) -> dict:
    """扫描已打开的连接；返回逐表结果与结论（不含路径信息）。"""
    existing = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    missing = [t for t in TABLES if t not in existing]
    if missing:
        raise SchemaError(f"缺少表: {', '.join(missing)}（不是 vault.db？）")

    tables: dict[str, dict] = {}
    counts = {cat: 0 for cat in CATEGORIES}
    for table in TABLES:
        findings: list[dict] = []
        total = 0
        for (rel,) in conn.execute(f"SELECT rel FROM {table}"):  # noqa: S608 — 表名来自常量
            total += 1
            cats = rel_categories(rel)
            if cats:
                findings.append({"table": table, "rel": rel, "categories": cats})
                for cat in cats:
                    counts[cat] += 1
        tables[table] = {"total": total, "findings": findings}

    clean = all(v == 0 for v in counts.values())
    return {"tables": tables, "conclusion": {"clean": clean, "counts": counts}}


class SchemaError(Exception):
    """库打不开或表结构与 vault.db 不符。"""


def open_ro(path: str, immutable: bool = False):
    """只读打开 SQLite；mode=ro 保证连接层拒绝写，immutable 用于被占用的线上库。"""
    if immutable:
        uri = f"file:{path}?immutable=1"
    else:
        uri = f"file:{path}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def build_report(path: str, immutable: bool = False) -> dict:
    conn = open_ro(path, immutable)
    try:
        report = scan_connection(conn)
    finally:
        conn.close()
    report["db"] = path
    return report


def print_report(report: dict) -> None:
    print(f"db: {report['db']}")
    for table, data in report["tables"].items():
        print(f"[{table}] rows={data['total']} findings={len(data['findings'])}")
        for item in data["findings"]:
            cats = ", ".join(item["categories"])
            print(f"  - ({cats}) {item['rel']!r}")
    counts = report["conclusion"]["counts"]
    print("conclusion: " + ("clean" if report["conclusion"]["clean"] else "anomalies found")
          + f" | " + ", ".join(f"{k}={v}" for k, v in counts.items()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="只读扫描 vault.db 的 files.rel / versions.rel 异常（whitespace / drive_letter / null）",
    )
    parser.add_argument("db", help="vault.db 路径")
    parser.add_argument("--json", action="store_true", help="输出机器可读结论（JSON）")
    parser.add_argument(
        "--immutable",
        action="store_true",
        help="以 immutable=1 打开（被服务端占用的线上库；读不到未合并的 WAL 内容）",
    )
    args = parser.parse_args(argv)

    try:
        report = build_report(args.db, immutable=args.immutable)
    except SchemaError as exc:
        print(f"schema error: {exc}", file=sys.stderr)
        return 2
    except sqlite3.Error as exc:
        print(f"sqlite error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_report(report)
    return 0 if report["conclusion"]["clean"] else 1


if __name__ == "__main__":
    sys.exit(main())
