#!/usr/bin/env python3
"""Go 服务端并发上传基准：同时验证吞吐与内容寻址的正确性。

用法：
    python v2/scripts/bench_upload.py --server v2/server/bin/selfshare-server.exe
    python v2/scripts/bench_upload.py --server <path> --files 64 --size-kb 256 --workers 16

服务端零配置起步时会生成随机令牌，因此这里先用 Python 的 Registry 在临时目录
建一个固定令牌的同步库，再让 Go 服务端读取同一份 server.json——这也顺带验证了
两种实现共享磁盘格式。
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from selfshare.store import Registry  # noqa: E402

TOKEN = "tok-bench-1234567890abcdef"
VAULT = "bench"
LISTEN_RE = re.compile(r"listening on http://127\.0\.0\.1:(\d+)")


def start_server(binary: str):
    root = tempfile.mkdtemp(prefix="selfshare-bench-")
    log = None
    proc = None
    try:
        Registry(root).create_vault(VAULT, token=TOKEN)
        log_path = os.path.join(root, "server.log")
        log = open(log_path, "wb")
        proc = subprocess.Popen(
            [binary, "--root", root, "--host", "127.0.0.1", "--port", "0", "--quiet"],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
                    match = LISTEN_RE.search(fh.read())
                if match:
                    return proc, root, log, "http://127.0.0.1:" + match.group(1)
            except OSError:
                pass
            if proc.poll() is not None:
                raise RuntimeError("服务端提前退出，日志：" + log_path)
            time.sleep(0.1)
        raise RuntimeError("服务端未在 30 秒内报告端口")
    except BaseException:
        # 启动失败/超时时也要回收进程与临时目录，避免 bench_ab 反复运行后残留。
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        if log is not None:
            log.close()
        shutil.rmtree(root, ignore_errors=True)
        raise


def put_blob(base: str, digest: str, payload: bytes) -> int:
    req = urllib.request.Request(
        f"{base}/api/v/{VAULT}/blob/{digest}",
        data=payload,
        method="PUT",
        headers={
            "Authorization": "Bearer " + TOKEN,
            "Content-Type": "application/octet-stream",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        resp.read()
        return resp.status


def get_blob(base: str, digest: str) -> bytes:
    req = urllib.request.Request(
        f"{base}/api/v/{VAULT}/blob/{digest}",
        headers={"Authorization": "Bearer " + TOKEN},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", required=True, help="selfshare-server 可执行文件")
    ap.add_argument("--files", type=int, default=32)
    ap.add_argument("--size-kb", type=int, default=256)
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()

    payloads = [os.urandom(args.size_kb * 1024) for _ in range(args.files)]
    digests = [hashlib.sha256(p).hexdigest() for p in payloads]
    proc, root, log, base = start_server(os.path.abspath(args.server))
    try:
        started = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            statuses = list(pool.map(lambda i: put_blob(base, digests[i], payloads[i]), range(args.files)))
        elapsed = time.perf_counter() - started

        assert all(s == 200 for s in statuses), f"上传存在失败状态: {statuses}"
        for digest, payload in zip(digests, payloads):
            data = get_blob(base, digest)
            assert hashlib.sha256(data).hexdigest() == digest, f"回读内容损坏: {digest}"

        total = len(payloads) * args.size_kb * 1024
        result = {
            "engine": "go",
            "files": args.files,
            "workers": args.workers,
            "total_mb": round(total / 1048576, 2),
            "elapsed_s": round(elapsed, 3),
            "throughput_mb_s": round(total / 1048576 / elapsed, 2),
            "uploads_ok": sum(1 for s in statuses if s == 200),
            "readback_verified": len(digests),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        log.close()
        shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
