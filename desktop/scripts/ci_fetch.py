"""从 GitHub Actions / Release 下载构建产物到本地，支撑「本地开发 -> CI 构建 -> 下载产物 -> 本地测试」循环。

本机无 `gh` CLI 时使用；仅标准库。放在 desktop/scripts/ 是因为循环主对象是
Rust 内核产物（selfshare-core-windows = selfshare_core.dll），Go 服务端产物为顺带受益。

用法（仓库根执行）：
    python desktop/scripts/ci_fetch.py runs --workflow ci.yml --limit 5
    python desktop/scripts/ci_fetch.py artifacts --run <run_id>
    python desktop/scripts/ci_fetch.py fetch selfshare-core-windows --out .ss-artifacts
    python desktop/scripts/ci_fetch.py fetch server-windows-amd64 --run <run_id> --out .ss-artifacts
    python desktop/scripts/ci_fetch.py release --tag v2.0.0 --list-only
    python desktop/scripts/ci_fetch.py release --tag v2.0.0 --name selfshare-server-2.0.0.zip
    python desktop/scripts/ci_fetch.py verify <file> --digest sha256:<hex>
    python desktop/scripts/ci_fetch.py verify <file> --release v2.0.0   # 与 --digest 互斥

fetch 默认取该 workflow 在 master 上最新的成功 run 的指定产物；zip 解包到 --out 目录。
fetch / release 为强制校验：API 未带 digest 时不再「仅记录」，直接拒绝视为已校验。
release 取 tag（默认 latest）的发布资产，逐项按 GitHub API 的 digest 做 SHA256 校验，
且落盘前校验资产名为单名（拒绝 .. / 前导 / / 盘符 / 绝对路径）。
Actions artifact（通道 A）与 Release 资产（通道 B）是两条不同来源，不得互相冒充。

鉴权：优先 `GITHUB_TOKEN` 环境变量；否则调用 `git credential fill` 复用本机已存
凭据（只用作请求头，不回显、不落盘）。公开仓库的 runs/artifacts 元数据可匿名读，
产物 zip 下载通常需要登录身份。
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile

API = "https://api.github.com"


def repo_slug() -> str:
    url = subprocess.run(["git", "remote", "get-url", "origin"],
                         capture_output=True, text=True, check=True).stdout.strip()
    path = url.split(":", 1)[-1] if url.startswith("git@") else url.split("//", 1)[-1].split("/", 1)[1]
    return path.removesuffix(".git")


def token() -> str:
    env = os.environ.get("GITHUB_TOKEN", "").strip()
    if env:
        return env
    inp = "protocol=https\nhost=github.com\n\n".encode()
    try:
        out = subprocess.run(["git", "credential", "fill"], input=inp.decode(),
                             capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""
    for line in out.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1].strip()
    return ""


def api(path: str, tok: str, raw: bool = False):
    if raw:
        return download(path, tok)
    req = urllib.request.Request(API + path, headers={
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "selfshare-ci-fetch",
    })
    if tok:
        req.add_header("Authorization", "Bearer %s" % tok)
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read()
    return json.loads(body.decode("utf-8"))


def download(path: str, tok: str, accept: str = "application/vnd.github+json") -> bytes:
    """下载二进制产物。实测（curl A/B）：Actions artifact zip 首跳 Accept 必须是
    application/vnd.github+json（octet-stream 会 415）；Release 资产端点则要求
    application/octet-stream。GitHub 随后 302 到预签名 blob 存储；二跳是裸 GET，
    不得带 Authorization/Accept。"""
    req = urllib.request.Request(API + path, headers={
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "selfshare-ci-fetch",
    })
    if tok:
        req.add_header("Authorization", "Bearer %s" % tok)

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None  # 关闭自动跟随，改在 except 里手动二跳

    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(req, timeout=60) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code in (301, 302, 303, 307):
            with urllib.request.urlopen(exc.headers["Location"], timeout=120) as resp:
                return resp.read()
        raise


def digest_of(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def check_digest(data: bytes, expected: str, label: str, strict: bool = False) -> None:
    """按 GitHub API 的 digest 字段校验；API 未提供时 strict=False 仅记录、strict=True 拒绝视为已校验。"""
    actual = digest_of(data)
    if not expected:
        if strict:
            sys.exit("  %s: digest 不可用，拒绝视为已校验（API 未提供 digest，实际 %s）" % (label, actual))
        print("  %s: digest 不可用（API 未提供），仅记录 %s" % (label, actual))
        return
    if actual.lower() != expected.lower():
        sys.exit("%s 摘要校验失败：expected=%s actual=%s" % (label, expected, actual))
    print("  %s: %s OK" % (label, actual))


def illegal_path(name: str) -> bool:
    """单名非法路径判据：.. 段 / 前导 /（POSIX 绝对路径）/ 盘符（如 C:）。"""
    norm = name.replace("\\", "/")
    return (norm.startswith("/") or ".." in norm.split("/")
            or (len(norm) > 1 and norm[1] == ":"))


def safe_members(zf: zipfile.ZipFile) -> list[str]:
    """拒绝 .. / 绝对路径 / 盘符，避免产物 zip 写出目标目录。"""
    names = zf.namelist()
    for name in names:
        if illegal_path(name):
            sys.exit("产物 zip 含非法路径 %r，拒绝解包" % name)
    return names


def safe_asset_name(name: str) -> str:
    """Release 资产落盘前单名校验，复用 illegal_path 判据，拒绝写出目标目录。"""
    if not name or illegal_path(name):
        sys.exit("Release 资产含非法名称 %r，拒绝落盘" % name)
    return name


def release_data(tok: str, tag: str) -> dict:
    path = ("/repos/%s/releases/latest" % repo_slug()) if tag in ("", "latest") \
        else ("/repos/%s/releases/tags/%s" % (repo_slug(), tag))
    return api(path, tok)


def pick_run(args, tok: str, workflow: str) -> dict:
    if args.run:
        return api("/repos/%s/actions/runs/%d" % (repo_slug(), args.run), tok)
    query = "/repos/%s/actions/workflows/%s/runs?branch=master&status=success&per_page=20" % (
        repo_slug(), workflow)
    runs = api(query, tok).get("workflow_runs", [])
    if not runs:
        sys.exit("workflow %s 在 master 上没有成功 run" % workflow)
    return runs[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_runs = sub.add_parser("runs", help="列出 workflow 最近 run")
    p_runs.add_argument("--workflow", default="ci.yml")
    p_runs.add_argument("--limit", type=int, default=5)

    p_art = sub.add_parser("artifacts", help="列出某 run 的产物")
    p_art.add_argument("--run", type=int, required=True)

    p_fetch = sub.add_parser("fetch", help="下载并解包 Actions artifact（通道 A）")
    p_fetch.add_argument("name", help="产物名，如 selfshare-core-windows / server-windows-amd64")
    p_fetch.add_argument("--workflow", default="ci.yml",
                         help="未指定 --run 时按此 workflow 找最新成功 run（Go 二进制用 ci-v2.yml）")
    p_fetch.add_argument("--run", type=int, default=None)
    p_fetch.add_argument("--out", default=".ss-artifacts")

    p_rel = sub.add_parser("release", help="列出 / 下载 Release 资产（通道 B）")
    p_rel.add_argument("--tag", default="latest", help="标签如 v2.0.0；latest 取最新发布")
    p_rel.add_argument("--name", default=None, help="只下载指定资产名；默认全部")
    p_rel.add_argument("--out", default=None, help="默认 .ss-artifacts/release-<tag>")
    p_rel.add_argument("--list-only", action="store_true", help="只列资产与 digest，不下载")

    p_ver = sub.add_parser("verify", help="校验本地产物 SHA256")
    p_ver.add_argument("file")
    src = p_ver.add_mutually_exclusive_group()
    src.add_argument("--digest", default=None, help="形如 sha256:<hex>")
    src.add_argument("--release", default=None, help="按该 tag 的同名 Release 资产取 digest")

    args = parser.parse_args()
    tok = token()

    if args.cmd == "runs":
        data = api("/repos/%s/actions/workflows/%s/runs?per_page=%d" % (
            repo_slug(), args.workflow, args.limit), tok)
        for r in data.get("workflow_runs", []):
            print("run %-10d %-8s %-9s %s %s" % (
                r["id"], r["status"], r.get("conclusion") or "-", r["head_sha"][:7], r["created_at"]))
        return

    if args.cmd == "artifacts":
        data = api("/repos/%s/actions/runs/%d/artifacts" % (repo_slug(), args.run), tok)
        for a in data.get("artifacts", []):
            print("artifact %-32s %-9s %8.1f MB  id=%d  %s" % (
                a["name"], "expired" if a["expired"] else "live", a["size_in_bytes"] / 1e6,
                a["id"], a.get("digest") or "no-digest"))
        return

    if args.cmd == "fetch":
        run = pick_run(args, tok, args.workflow)
        arts = api("/repos/%s/actions/runs/%d/artifacts" % (repo_slug(), run["id"]), tok).get("artifacts", [])
        match = [a for a in arts if a["name"] == args.name and not a["expired"]]
        if not match:
            sys.exit("run %d 没有可用产物 %r；现有：%s" % (
                run["id"], args.name, ", ".join(a["name"] for a in arts) or "(无)"))
        art = match[0]
        print("run %d (%s) -> %s (%.1f MB)" % (
            run["id"], run["head_sha"][:7], art["name"], art["size_in_bytes"] / 1e6))
        body = download("/repos/%s/actions/artifacts/%d/zip" % (repo_slug(), art["id"]), tok)
        check_digest(body, art.get("digest", ""), art["name"] + ".zip", strict=True)
        os.makedirs(args.out, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(body)) as zf:
            names = safe_members(zf)
            zf.extractall(args.out)
            for n in names:
                print("  %s/%s" % (args.out, n))
        return

    if args.cmd == "release":
        rel = release_data(tok, args.tag)
        tag = rel["tag_name"]
        assets = rel.get("assets", [])
        print("release %s: %d assets" % (tag, len(assets)))
        for a in assets:
            print("  %-45s %10d B  %s" % (
                a["name"], a.get("size", a.get("size_in_bytes", 0)), a.get("digest") or "-"))
        if args.list_only:
            return
        picked = [a for a in assets if not args.name or a["name"] == args.name]
        if not picked:
            sys.exit("release %s 没有资产 %r" % (tag, args.name))
        out = args.out or os.path.join(".ss-artifacts", "release-" + tag)
        os.makedirs(out, exist_ok=True)
        for a in picked:
            safe_asset_name(a["name"])
            body = download("/repos/%s/releases/assets/%d" % (repo_slug(), a["id"]), tok,
                            accept="application/octet-stream")
            check_digest(body, a.get("digest", ""), a["name"], strict=True)
            target = os.path.join(out, a["name"])
            with open(target, "wb") as fh:
                fh.write(body)
            print("  -> %s (%d B)" % (target, len(body)))
        return

    # verify
    with open(args.file, "rb") as fh:
        data = fh.read()
    expected = args.digest
    if args.release:
        rel = release_data(tok, args.release)
        name = os.path.basename(args.file)
        found = [a for a in rel.get("assets", []) if a["name"] == name]
        if not found:
            sys.exit("release %s 中没有同名资产 %r" % (args.release, name))
        expected = found[0].get("digest", "")
    if not expected:
        sys.exit("需要 --digest sha256:<hex> 或 --release <tag>（且资产带 digest 字段）")
    check_digest(data, expected, args.file, strict=True)


if __name__ == "__main__":
    main()
