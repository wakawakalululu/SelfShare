"""Command line interface: the user-facing entry point.

Typical use on two machines::

    # server (or any always-on host)
    selfshare server --root D:\\SelfShareData --port 8484
    selfshare vault create work --root D:\\SelfShareData

    # either host: mount a local folder onto that vault
    selfshare mount D:\\同步盘 --url http://192.168.1.10:8484 --vault work --token XXX
    selfshare sync D:\\同步盘
    selfshare watch D:\\同步盘

A local folder mounted this way behaves like a 坚果云 "同步文件夹": every host
that mounts the same vault sees the same tree, with full version history on the
server.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

from . import __version__
from .client import Client, RemoteError
from .config import (
    known_mounts,
    read_config,
    register_mount,
    resolve_folder,
    unregister_mount,
    write_config,
)
from .server import serve
from .store import Registry
from .sync import STATE_DIR, SyncReport, Syncer
from .util import hide_path, human_size, now_iso, norm_rel

# --------------------------------------------------------------------------- #
# pretty output
# --------------------------------------------------------------------------- #
USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(text: str, code: str) -> str:
    return "\033[%sm%s\033[0m" % (code, text) if USE_COLOR else text


def ok(text: str) -> str:
    return _c(text, "32")


def warn(text: str) -> str:
    return _c(text, "33")


def bad(text: str) -> str:
    return _c(text, "31")


def dim(text: str) -> str:
    return _c(text, "90")


def make_client(cfg: Dict[str, Any]) -> Client:
    url = cfg.get("url", "")
    token = cfg.get("token", "")
    vault = cfg.get("vault", "")
    if not url or not token or not vault:
        raise SystemExit("配置不完整: 需要 url / vault / token，请重新执行 mount")
    return Client(url, vault, token, timeout=float(cfg.get("timeout", 60)))


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #
def cmd_server(args: argparse.Namespace) -> int:
    serve(args.root, host=args.host, port=args.port,
          certfile=args.cert, keyfile=args.key, quiet=args.quiet)
    return 0


def cmd_vault(args: argparse.Namespace) -> int:
    reg = Registry(args.root)
    if args.action == "create":
        try:
            info = reg.create_vault(args.vault_id, token=args.token, note=args.note)
        except ValueError as exc:
            print(bad("创建失败: %s" % exc))
            return 1
        print(ok("已创建同步库: %s" % info["vault"]))
        print("  数据目录: %s" % reg.vault_path(info["vault"]))
        print("  访问令牌: %s" % info["token"])
        print(dim("  令牌只显示这一次，请立即抄到另一台主机；泄漏时用 vault rotate 重置。"))
        return 0
    if args.action == "list":
        vaults = reg.list_vaults()
        if not vaults:
            print("还没有同步库，用 `selfshare vault create <id>` 创建")
            return 0
        print("%-20s %-20s %s" % ("ID", "创建时间", "备注"))
        for vid in vaults:
            meta = reg.data["vaults"][vid]
            print("%-20s %-20s %s" % (vid, meta.get("created", "-"), meta.get("note", "")))
        return 0
    if args.action == "pair-code":
        if not args.vault_id:
            print(bad("需要指定同步库名"))
            return 1
        if not reg.exists(args.vault_id):
            print(bad("没有这个同步库: %s" % args.vault_id))
            return 1
        vault = reg.open_vault(args.vault_id)
        try:
            from .pairing import PairCodeStore

            store = PairCodeStore(vault.path)
            info = store.issue(args.vault_id, ttl=args.ttl, note=args.note)
        finally:
            vault.close()
        host = _lan_ip()
        print(ok("配对码已生成"))
        print()
        print("     " + _c(info["code"], "1;36"))
        print()
        print("  有效期至: %s（%d 分钟）" % (info["expires_at"], info["expires_in"] // 60))
        print("  服务端  : http://%s:%d" % (host, args.port))
        print("  同步库  : %s" % args.vault_id)
        print()
        print(dim("  在另一台设备上运行："))
        print(dim('    selfshare pair "D:\同步盘" --url http://%s:%d --code %s'
                  % (host, args.port, info["code"])))
        print(dim("  或在桌面端选择「输入配对码」并粘贴上面这串。"))
        print()
        print(warn("  该码一次性有效，用后作废。"))
        return 0
    if args.action == "rotate":
        try:
            info = reg.rotate_token(args.vault_id)
        except ValueError as exc:
            print(bad(str(exc)))
            return 1
        print(ok("已重置 %s 的令牌" % info["vault"]))
        print("  新令牌: %s" % info["token"])
        print(warn("  所有旧主机需要重新 mount 才能同步。"))
        return 0
    if args.action == "remove":
        if not args.yes:
            print(warn("删除同步库会连同版本历史一起删除，确认请加 --yes"))
            return 1
        if not reg.exists(args.vault_id):
            print(bad("没有这个同步库: %s" % args.vault_id))
            return 1
        shutil.rmtree(reg.vault_path(args.vault_id), ignore_errors=True)
        reg.data["vaults"].pop(args.vault_id, None)
        reg.save()
        print(ok("已删除同步库 %s" % args.vault_id))
        return 0
    if args.action == "info":
        if not reg.exists(args.vault_id):
            print(bad("没有这个同步库: %s" % args.vault_id))
            return 1
        vault = reg.open_vault(args.vault_id)
        try:
            st = vault.stat()
        finally:
            vault.close()
        print("同步库: %s" % args.vault_id)
        print("  文件数  : %d" % st["files"])
        print("  逻辑大小: %s" % human_size(st["bytes"]))
        print("  版本记录: %d" % st["versions"])
        print("  去重块  : %d (%s)" % (st["blobs"], human_size(st["blob_bytes"])))
        print("  当前修订: %d" % st["head_rev"])
        return 0
    print(bad("未知操作"))
    return 1


def cmd_mount(args: argparse.Namespace) -> int:
    folder = os.path.abspath(args.folder)
    os.makedirs(folder, exist_ok=True)
    cfg_path = os.path.join(folder, STATE_DIR, "config.json")
    if os.path.exists(cfg_path) and not args.force:
        print(warn("该目录已经挂载过 (%s)" % cfg_path))
        print(dim("  如需改配置请加 --force，或先 umount"))
        return 1

    token = args.token or os.environ.get("SELFSHARE_TOKEN", "")
    if not token:
        print(bad("缺少令牌: 用 --token 或环境变量 SELFSHARE_TOKEN"))
        return 1
    url = args.url.rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = "http://" + url

    cfg: Dict[str, Any] = {
        "url": url,
        "vault": args.vault,
        "token": token,
        "folder": folder,
        "mount_id": args.vault,
        "created": now_iso(),
        "timeout": args.timeout,
    }

    client = Client(url, args.vault, token, timeout=args.timeout)
    print("连接 %s …" % url)
    try:
        st = client.stat()
    except RemoteError as exc:
        print(bad("连接失败: %s" % exc))
        if exc.status == 401:
            print(dim("  检查令牌是否正确；服务端可用 vault rotate 重新签发。"))
        elif exc.status == 404:
            print(dim("  检查同步库名是否正确；服务端可用 vault list 查看。"))
        return 1
    print(ok("已连接，远端 %d 个文件 (%s)" % (st["files"], human_size(st["bytes"]))))

    write_config(folder, cfg)
    hide_path(os.path.join(folder, STATE_DIR))
    register_mount(folder)
    print(ok("已挂载: %s -> %s/%s" % (folder, url, args.vault)))
    print(dim("  下一步: selfshare sync \"%s\"  拉取远端内容" % folder))
    print(dim("          selfshare watch \"%s\" 开启自动同步" % folder))
    return 0


def cmd_pair(args: argparse.Namespace) -> int:
    """傻瓜式挂载：只需服务端地址 + 配对码。"""
    folder = os.path.abspath(args.folder)
    url = args.url.rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = "http://" + url

    print("正在连接 %s …" % url)
    if not Client.probe(url):
        print(bad("这个地址不是 SelfShare 服务端"))
        print(dim("  确认服务端已启动，且地址形如 http://192.168.1.10:8484"))
        return 1

    print("正在使用配对码 …")
    try:
        info = Client.pair(url, args.code)
    except RemoteError as exc:
        print(bad(str(exc)))
        print(dim("  配对码一次性且默认 30 分钟过期；请在服务端重新生成。"))
        return 1

    token = info["token"]
    vault = info["vault"]
    client = Client(url, vault, token, timeout=args.timeout)
    try:
        stats = client.stat()
    except RemoteError as exc:
        print(bad("连接成功但读取同步库失败：%s" % exc))
        return 1

    from .config import register_mount, write_config

    os.makedirs(folder, exist_ok=True)
    write_config(folder, {
        "url": url,
        "vault": vault,
        "token": token,
        "folder": folder,
        "mount_id": vault,
        "created": now_iso(),
        "timeout": args.timeout,
    })
    hide_path(os.path.join(folder, ".selfshare"))
    register_mount(folder)

    print(ok("已连接"))
    print("  本地文件夹: %s" % folder)
    print("  同步库    : %s（远端 %d 个文件，%s）"
          % (vault, stats["files"], human_size(stats["bytes"])))
    print()
    print("  正在拉取远端内容 …")
    with Syncer(folder, client) as syncer:
        report = syncer.sync()
    _print_report(report)
    print()
    print(ok("完成。之后运行下面任意一条即可自动同步："))
    print("  selfshare watch \"%s\"" % folder)
    print(dim("  桌面端：双击启动 SelfShare，选择该文件夹即可。"))
    return 0


def cmd_umount(args: argparse.Namespace) -> int:
    folder = resolve_folder(args.folder)
    if not os.path.exists(os.path.join(folder, STATE_DIR, "config.json")):
        print(bad("该目录未挂载: %s" % folder))
        return 1
    if not args.keep_state:
        shutil.rmtree(os.path.join(folder, STATE_DIR), ignore_errors=True)
    unregister_mount(folder)
    print(ok("已卸载: %s" % folder))
    print(dim("  本地文件保留；重新 mount 可继续同步。"))
    return 0


def _lan_ip() -> str:
    """取本机对外 IP，用于打印可直接复制的地址。"""
    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def _print_report(report: SyncReport) -> None:
    print(("变  " if report.changed else "稳  ") + report.summary())
    for rel in report.pulls[:20]:
        print(dim("  ↓ %s" % rel))
    if len(report.pulls) > 20:
        print(dim("  ↓ … 共 %d 项" % len(report.pulls)))
    for rel in report.pushes[:20]:
        print(dim("  ↑ %s" % rel))
    if len(report.pushes) > 20:
        print(dim("  ↑ … 共 %d 项" % len(report.pushes)))
    for rel in report.deletes_local:
        print(dim("  - 本地删除 %s" % rel))
    for rel in report.deletes_remote:
        print(dim("  - 远端删除 %s" % rel))
    for rel in report.conflicts:
        print(warn("  * 冲突 %s" % rel))
    for err in report.errors:
        print(bad("  ! %s" % err))


def cmd_sync(args: argparse.Namespace) -> int:
    folder = resolve_folder(args.folder)
    cfg = read_config(folder)
    client = make_client(cfg)
    started = time.time()
    try:
        with Syncer(folder, client, on_log=lambda m: print(dim("  %s" % m))) as syncer:
            report = syncer.sync(dry_run=args.dry_run)
    except RemoteError as exc:
        print(bad("同步失败: %s" % exc))
        return 1
    except RuntimeError as exc:
        print(bad(str(exc)))
        return 1
    _print_report(report)
    print(dim("  用时 %.2fs，远端修订 %d" % (time.time() - started, report.head_rev)))
    if args.verbose:
        for rel in report.skipped:
            print(dim("  跳过 %s" % rel))
    return 0 if not report.errors else 2


def cmd_watch(args: argparse.Namespace) -> int:
    folder = resolve_folder(args.folder)
    cfg = read_config(folder)
    client = make_client(cfg)

    def log(msg: str) -> None:
        print("%s %s" % (dim(now_iso()), msg), flush=True)

    peer = None
    if args.p2p:
        from .peer import PeerNode
        peer = PeerNode(folder, client, quiet=False)
        listen = peer.start()
        log("P2P 节点已启动: %s (peer_id=%s)" % (listen, peer.peer_id))

    def factory() -> Syncer:
        s = Syncer(folder, client)
        if peer:
            s.peer_id = peer.peer_id
        return s

    # one immediate pass so the folder converges before watching
    try:
        with factory() as syncer:
            report = syncer.sync()
        log("首次同步: %s" % report.summary())
    except Exception as exc:
        log("首次同步失败: %s" % exc)

    from .watch import Watcher

    watcher = Watcher(factory, folder, interval=args.interval,
                      debounce=args.debounce, log=log)
    try:
        watcher.run_forever(sync_interval=args.full_interval)
    except KeyboardInterrupt:
        pass
    finally:
        if peer:
            peer.stop()
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    folder = resolve_folder(args.folder)
    cfg = read_config(folder)
    from .sync import LocalState

    state = LocalState(folder)
    try:
        last = state.get("last_sync") or "从未"
        host = state.host_id
        head = state.get("head_rev") or "0"
        local_count = len(state.load())
    finally:
        state.close()
    print("挂载点: %s" % folder)
    print("  服务端  : %s" % cfg.get("url"))
    print("  同步库  : %s" % cfg.get("vault"))
    print("  本机标识: %s" % host)
    print("  上次同步: %s (本地记录修订 %s)" % (last, head))
    print("  已跟踪  : %d 项" % local_count)
    client = make_client(cfg)
    try:
        remote = client.stat()
        print("  远端状态: %d 个文件, %s, 修订 %d" % (
            remote["files"], human_size(remote["bytes"]), remote["head_rev"]))
        if int(head) < int(remote["head_rev"]):
            print(warn("  → 远端有新修订，建议运行 sync"))
        elif int(head) > int(remote["head_rev"]):
            print(warn("  → 本地记录了未来修订（服务端可能被重建）"))
    except RemoteError as exc:
        print(bad("  远端不可达: %s" % exc))
        return 1
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    folder = resolve_folder(args.folder)
    cfg = read_config(folder)
    client = make_client(cfg)
    try:
        data = client.history(args.path, 100)
    except RemoteError as exc:
        print(bad("读取历史失败: %s" % exc))
        return 1
    entries = data.get("entries", [])
    if not entries:
        print("暂无历史记录")
        return 0
    print("%-19s %-6s %-9s %-10s %s" % ("时间", "修订", "动作", "来源", "文件"))
    for e in entries:
        action = "上传" if e["action"] == "put" else "删除"
        print("%-19s %-6s %-9s %-10s %s" % (
            e["time"], e["rev"], action, (e["origin"] or "-")[:10],
            e["path"] + ("  (%s)" % human_size(e["size"]) if e.get("size") else "")))
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    folder = resolve_folder(args.folder)
    cfg = read_config(folder)
    client = make_client(cfg)
    try:
        data = client.history(args.path, 100)
    except RemoteError as exc:
        print(bad("读取历史失败: %s" % exc))
        return 1
    entries = [e for e in data.get("entries", []) if e["action"] == "put" and e["hash"]]
    if not entries:
        print(bad("该文件没有可恢复的历史版本: %s" % args.path))
        return 1
    print("可恢复版本:")
    for idx, e in enumerate(entries, 1):
        print("  [%d] %s  %s  %s" % (idx, e["time"], human_size(e["size"]), e["hash"][:12]))
    pick = args.version or 1
    if pick < 1 or pick > len(entries):
        print(bad("版本序号超出范围"))
        return 1
    chosen = entries[pick - 1]
    dest_rel = args.output or args.path
    dest_rel = norm_rel(dest_rel)
    from .util import abs_path, ensure_parent

    dest = abs_path(folder, dest_rel)
    ensure_parent(dest)
    target = dest
    if os.path.exists(dest) and not args.overwrite:
        base, ext = os.path.splitext(dest)
        target = "%s (恢复 %s)%s" % (base, time.strftime("%Y%m%d-%H%M%S"), ext)
        print(warn("目标已存在，改写为: %s" % os.path.basename(target)))
    client.get_blob(chosen["hash"], target)
    print(ok("已恢复到: %s" % target))
    print(dim("  下次 sync 会把它作为普通改动上传，其它主机随之更新。"))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    mounts = known_mounts()
    if not mounts:
        print("还没有挂载任何同步目录")
        return 0
    print("%-52s %-24s %s" % ("本地目录", "服务端", "同步库"))
    for m in mounts:
        print("%-52s %-24s %s" % (m["path"], m["url"], m["vault"]))
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    folder = os.path.abspath(args.folder)
    os.makedirs(folder, exist_ok=True)
    ignore_file = os.path.join(folder, ".selfshareignore")
    if not os.path.exists(ignore_file):
        sample = (
            "# 与 .gitignore 类似；每行一个模式\n"
            "# 结尾加 / 只匹配目录；! 表示重新包含\n"
            "*.tmp\n"
            "~$*\n"
            ".DS_Store\n"
            "Thumbs.db\n"
            "desktop.ini\n"
            "*.crdownload\n"
            "*.partial\n"
        )
        with open(ignore_file, "w", encoding="utf-8") as fh:
            fh.write(sample)
        print(ok("已写入忽略规则样例: %s" % ignore_file))
    else:
        print(dim("忽略规则已存在: %s" % ignore_file))
    return 0


def cmd_drive(args: argparse.Namespace) -> int:
    """Map the mount onto a drive letter (Windows) or bind path (Linux/mac)."""
    folder = resolve_folder(args.folder)
    letter = args.letter.rstrip(":").upper()
    if os.name == "nt":
        if not (len(letter) == 1 and letter.isalpha()):
            print(bad("盘符必须是单个字母，例如 Z"))
            return 1
        result = subprocess.run(
            ["subst", letter + ":", folder],
            capture_output=True, text=True, shell=False,
        )
        if result.returncode != 0:
            print(bad("挂载盘符失败: %s" % (result.stderr or result.stdout).strip()))
            print(dim("  提示: 先用 `subst %s: /D` 释放该盘符，或换一个字母" % letter))
            return 1
        print(ok("已映射 %s: -> %s" % (letter, folder)))
        print(dim("  重启后失效；需要开机自动映射见 README 的「开机自动挂载」一节。"))
        return 0
    print(warn("非 Windows 系统请用符号链接代替盘符:"))
    print("  ln -s \"%s\" \"%s\"" % (folder, args.letter))
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    folder = resolve_folder(args.folder)
    cfg = read_config(folder)
    problems = 0
    print("检查挂载: %s" % folder)
    # 1. config
    for key in ("url", "vault", "token"):
        if not cfg.get(key):
            print(bad("  ✗ 配置缺少 %s" % key))
            problems += 1
        else:
            shown = cfg[key] if key != "token" else cfg[key][:4] + "…" + cfg[key][-4:]
            print(ok("  ✓ %-6s %s" % (key, shown)))
    # 2. writability
    probe = os.path.join(folder, ".selfshare-write-test")
    try:
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("x")
        os.unlink(probe)
        print(ok("  ✓ 目录可写"))
    except OSError as exc:
        print(bad("  ✗ 目录不可写: %s" % exc))
        problems += 1
    # 3. server
    client = make_client(cfg)
    try:
        st = client.stat()
        print(ok("  ✓ 服务端可达，%d 个文件，修订 %d" % (st["files"], st["head_rev"])))
    except RemoteError as exc:
        print(bad("  ✗ 服务端不可达: %s" % exc))
        problems += 1
    # 4. state db
    from .sync import LocalState

    try:
        state = LocalState(folder)
        tracked = len(state.load())
        state.close()
        print(ok("  ✓ 本地状态库正常，跟踪 %d 项" % tracked))
    except Exception as exc:
        print(bad("  ✗ 本地状态库异常: %s" % exc))
        problems += 1
    print(ok("检查完成，未发现问题") if not problems else bad("发现 %d 个问题" % problems))
    return 0 if not problems else 2


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="selfshare",
        description="跨主机文件夹同步（自建，参考坚果云的同步文件夹体验）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  selfshare vault create work --root D:\\SelfShareData\n"
            "  selfshare server --root D:\\SelfShareData --port 8484\n"
            "  selfshare mount D:\\同步盘 --url http://192.168.1.10:8484 --vault work --token XXX\n"
            "  selfshare sync  D:\\同步盘\n"
            "  selfshare watch D:\\同步盘\n"
        ),
    )
    p.add_argument("-V", "--version", action="version", version="selfshare %s" % __version__)
    sub = p.add_subparsers(dest="command")

    sp = sub.add_parser("server", help="启动同步服务端")
    sp.add_argument("--root", default=os.path.join(os.getcwd(), "selfshare-data"),
                    help="服务端数据目录")
    sp.add_argument("--host", default="0.0.0.0")
    sp.add_argument("--port", type=int, default=8484)
    sp.add_argument("--cert", help="TLS 证书 (PEM)，提供后启用 HTTPS")
    sp.add_argument("--key", help="TLS 私钥 (PEM)")
    sp.add_argument("--quiet", action="store_true", help="不打印访问日志")
    sp.set_defaults(func=cmd_server)

    sp = sub.add_parser("vault", help="管理同步库")
    sp.add_argument("action",
                    choices=["create", "list", "info", "rotate", "remove", "pair-code"])
    sp.add_argument("vault_id", nargs="?", help="同步库名")
    sp.add_argument("--root", default=os.path.join(os.getcwd(), "selfshare-data"))
    sp.add_argument("--token", help="指定令牌（默认随机生成）")
    sp.add_argument("--note", default="", help="备注")
    sp.add_argument("--ttl", type=float, default=1800.0, help="配对码有效期（秒）")
    sp.add_argument("--port", type=int, default=8484, help="服务端端口，用于生成提示")
    sp.add_argument("--yes", action="store_true")
    sp.set_defaults(func=cmd_vault)

    sp = sub.add_parser("mount", help="把本地文件夹挂载到同步库")
    sp.add_argument("folder")
    sp.add_argument("--url", required=True, help="服务端地址，如 http://192.168.1.10:8484")
    sp.add_argument("--vault", required=True, help="同步库名")
    sp.add_argument("--token", help="访问令牌（也可用环境变量 SELFSHARE_TOKEN）")
    sp.add_argument("--timeout", type=float, default=60.0)
    sp.add_argument("--force", action="store_true", help="覆盖已有挂载配置")
    sp.set_defaults(func=cmd_mount)

    sp = sub.add_parser("pair", help="用配对码连接（一条命令完成挂载）")
    sp.add_argument("folder", help="本地文件夹，不存在会自动创建")
    sp.add_argument("--url", required=True, help="服务端地址")
    sp.add_argument("--code", required=True, help="服务端生成的配对码")
    sp.add_argument("--timeout", type=float, default=60.0)
    sp.set_defaults(func=cmd_pair)

    sp = sub.add_parser("umount", help="卸载本地挂载（不删文件）")
    sp.add_argument("folder", nargs="?")
    sp.add_argument("--keep-state", action="store_true", help="保留本地状态库")
    sp.set_defaults(func=cmd_umount)

    sp = sub.add_parser("sync", help="执行一次双向同步")
    sp.add_argument("folder", nargs="?")
    sp.add_argument("--dry-run", action="store_true", help="只显示计划，不落盘")
    sp.add_argument("--verbose", action="store_true")
    sp.set_defaults(func=cmd_sync)

    sp = sub.add_parser("watch", help="持续监视并自动同步")
    sp.add_argument("folder", nargs="?")
    sp.add_argument("--interval", type=float, default=5.0, help="轮询间隔秒")
    sp.add_argument("--debounce", type=float, default=2.0, help="变更静默秒")
    sp.add_argument("--full-interval", type=float, default=120.0,
                    help="无本地变更时的远端巡检间隔秒（0 关闭）")
    sp.add_argument("--p2p", action="store_true",
                    help="启动 P2P 节点：向服务器注册并向其他已认证主机提供 blob")
    sp.set_defaults(func=cmd_watch)

    sp = sub.add_parser("status", help="查看挂载与同步状态")
    sp.add_argument("folder", nargs="?")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("history", help="查看服务端版本历史")
    sp.add_argument("folder", nargs="?")
    sp.add_argument("--path", help="只看某个文件")
    sp.add_argument("--limit", type=int, default=50)
    sp.set_defaults(func=cmd_history)

    sp = sub.add_parser("restore", help="从历史版本恢复文件")
    sp.add_argument("path", help="同步目录内的相对路径")
    sp.add_argument("folder", nargs="?")
    sp.add_argument("--version", type=int, default=1, help="序号，默认最新")
    sp.add_argument("--output", help="恢复到别的相对路径")
    sp.add_argument("--overwrite", action="store_true")
    sp.set_defaults(func=cmd_restore)

    sp = sub.add_parser("list", help="列出所有挂载点")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("init", help="在目录内生成忽略规则样例")
    sp.add_argument("folder", nargs="?", default=".")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("drive", help="把挂载目录映射成盘符 (Windows subst)")
    sp.add_argument("letter", help="盘符，如 Z")
    sp.add_argument("folder", nargs="?")
    sp.set_defaults(func=cmd_drive)

    sp = sub.add_parser("doctor", help="自检挂载配置与连通性")
    sp.add_argument("folder", nargs="?")
    sp.set_defaults(func=cmd_doctor)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    try:
        return args.func(args)  # type: ignore[no-any-return]
    except FileNotFoundError as exc:
        print(bad(str(exc)))
        return 1
    except KeyboardInterrupt:
        print("\n已中断")
        return 130
