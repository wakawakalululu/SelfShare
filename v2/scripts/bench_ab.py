#!/usr/bin/env python3
"""同轮 A/B 并发上传基准：固定负载、预热、ABBA 交替、多次取中位数。

用途：复核 v2/RELEASE_SUMMARY.md §2.2 的性能口径。脚本**不做倍数或阈值断言**，
"no_significant_difference" 是合法结论；共享 runner 的负载抖动大，因此不进入
push / PR 门禁，只用于手动运行或 workflow_dispatch。

示例：
  # 比较两个已有二进制
  python v2/scripts/bench_ab.py --server-a v2/server/bin/selfshare-server.exe \
      --server-b v2/server/bin/selfshare-server-baseline.exe --repeats 3

  # 由当前源码用 go build -overlay 生成「优化前」基线（不改仓库源码）
  python v2/scripts/bench_ab.py --server-a v2/server/bin/selfshare-server.exe \
      --build-baseline --go /path/to/go --repeats 3 --out bench-ab.json

注意：A/B 应使用相同构建参数；--build-baseline 会用与 CI 一致的
`CGO_ENABLED=0`、`-trimpath`、`-ldflags=-s -w` 构建，并额外构建一份不带
overlay 的参考二进制，确认 overlay 确实生效（否则静默退化为 A=B）。
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import platform
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from bench_upload import get_blob, put_blob, start_server  # noqa: E402

REPO = SCRIPT_DIR.parent.parent
SERVER_DIR = REPO / "v2" / "server"
API_GO = SERVER_DIR / "internal" / "api" / "api.go"
# 优化前行为：所有 action 都走完整 Vault（OpenVault）。与 api.go 的文本耦合，
# 若该段重构需同步更新；go build -overlay 保证仓库源码不被改动。
FAST_PATH = 'if action == "blob" || action == "blobbulk" || action == "peers" || action == "peer" {'


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_baseline(go: str, out: str) -> str:
    text = API_GO.read_text(encoding="utf-8")
    if FAST_PATH not in text:
        raise RuntimeError(f"未找到 blob 快速路径条件，overlay 需同步更新：{API_GO}")
    tmp = tempfile.mkdtemp(prefix="selfshare-ab-overlay-")
    try:
        patched = Path(tmp) / "api.go"
        patched.write_text(text.replace(FAST_PATH, "if false {", 1), encoding="utf-8")
        overlay = Path(tmp) / "overlay.json"
        # Go overlay 的 Replace 键需与构建时路径一致；统一用正斜杠。
        key = str(API_GO).replace(os.sep, "/")
        value = str(patched).replace(os.sep, "/")
        overlay.write_text(json.dumps({"Replace": {key: value}}), encoding="utf-8")

        env = dict(os.environ)
        env["CGO_ENABLED"] = "0"
        common = [go, "build", "-trimpath", "-ldflags=-s -w"]
        subprocess.run(
            common + ["-overlay", str(overlay), "-o", out, "./cmd/selfshare-server"],
            cwd=str(SERVER_DIR), env=env, check=True,
        )
        # overlay 映射未命中时 go build 不报错，只是产物与未打补丁时相同。
        reference = os.path.join(tmp, "reference")
        subprocess.run(
            common + ["-o", reference, "./cmd/selfshare-server"],
            cwd=str(SERVER_DIR), env=env, check=True,
        )
        if file_sha256(out) == file_sha256(reference):
            raise RuntimeError("overlay 未生效：基线二进制与未打补丁版本相同，请检查 Replace 路径")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def run_once(binary: str, payloads, digests, workers: int) -> float:
    proc = root = log = None
    try:
        proc, root, log, base = start_server(binary)
        started = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            statuses = list(
                pool.map(lambda i: put_blob(base, digests[i], payloads[i]), range(len(payloads)))
            )
        elapsed = time.perf_counter() - started
        if any(status != 200 for status in statuses):
            raise RuntimeError(f"{binary}: 上传存在失败状态 {statuses}")
        for digest in digests:
            if hashlib.sha256(get_blob(base, digest)).hexdigest() != digest:
                raise RuntimeError(f"{binary}: 回读摘要不一致 {digest}")
        return elapsed
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        if log is not None:
            log.close()
        if root:
            shutil.rmtree(root, ignore_errors=True)


def summarize(name: str, samples: list[float], total_mb: float) -> dict:
    median = statistics.median(samples)
    mad = statistics.median([abs(x - median) for x in samples])
    return {
        "name": name,
        "samples_s": [round(x, 4) for x in samples],
        "median_s": round(median, 4),
        "mad_s": round(mad, 4),
        "throughput_median_mb_s": round(total_mb / median, 2),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server-a", required=True, help="被测服务端二进制")
    ap.add_argument("--server-b", help="对照服务端二进制")
    ap.add_argument("--build-baseline", action="store_true", help="用 overlay 构建优化前基线作为 B")
    ap.add_argument("--go", default=os.environ.get("GO", "go"), help="go 可执行文件")
    ap.add_argument("--files", type=int, default=32)
    ap.add_argument("--size-kb", type=int, default=256)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--warmup", type=int, default=1, help="每侧预热轮数，不计入统计")
    ap.add_argument("--repeats", type=int, default=3, help="ABBA 轮数，每侧得到 2×repeats 个样本")
    ap.add_argument("--seed", type=int, default=20261107)
    ap.add_argument("--out", help="结果 JSON 落盘路径")
    args = ap.parse_args()

    if bool(args.server_b) == bool(args.build_baseline):
        ap.error("--server-b 与 --build-baseline 必须二选一")
    if min(args.repeats, args.files, args.size_kb, args.workers) < 1 or args.warmup < 0:
        ap.error("--repeats / --files / --size-kb / --workers 必须为正整数，--warmup 非负")

    server_a = os.path.abspath(args.server_a)
    tmpdir = None
    if args.build_baseline:
        tmpdir = tempfile.mkdtemp(prefix="selfshare-ab-bin-")
        suffix = ".exe" if os.name == "nt" else ""
        server_b = build_baseline(args.go, os.path.join(tmpdir, "selfshare-server-baseline" + suffix))
    else:
        server_b = os.path.abspath(args.server_b)
    for path in (server_a, server_b):
        if not os.path.isfile(path):
            raise SystemExit(f"二进制不存在: {path}")

    # 固定负载：同一 seed 保证 A/B 两侧输入完全一致，生成过程在计时之外。
    payloads = [
        random.Random(args.seed + i).randbytes(args.size_kb * 1024) for i in range(args.files)
    ]
    digests = [hashlib.sha256(payload).hexdigest() for payload in payloads]
    total_mb = args.files * args.size_kb * 1024 / 1048576
    binaries = {"a": server_a, "b": server_b}

    try:
        for _ in range(args.warmup):
            for key in ("a", "b"):
                run_once(binaries[key], payloads, digests, args.workers)
        samples: dict[str, list[float]] = {"a": [], "b": []}
        for _ in range(args.repeats):
            for key in ("a", "b", "b", "a"):  # ABBA 抵消时间漂移与缓存先后
                samples[key].append(run_once(binaries[key], payloads, digests, args.workers))

        left = summarize("a", samples["a"], total_mb)
        right = summarize("b", samples["b"], total_mb)
        # 判据使用未舍入的原始值，避免 round 造成边界误判。
        med_a, med_b = statistics.median(samples["a"]), statistics.median(samples["b"])
        mad_a = statistics.median([abs(x - med_a) for x in samples["a"]])
        mad_b = statistics.median([abs(x - med_b) for x in samples["b"]])
        diff = abs(med_a - med_b)
        noise = max(0.1 * min(med_a, med_b), 2 * max(mad_a, mad_b))
        result = {
            "note": "environment-sensitive; no ratio or SLA claim; see v2/RELEASE_SUMMARY.md section 2.2",
            "files": args.files,
            "size_kb": args.size_kb,
            "workers": args.workers,
            "total_mb": round(total_mb, 2),
            "seed": args.seed,
            "warmup": args.warmup,
            "repeats": args.repeats,
            "order": "ABBA",
            "binary_a": {"path": server_a, "sha256": file_sha256(server_a)},
            "binary_b": {"path": server_b, "sha256": file_sha256(server_b)},
            "a": left,
            "b": right,
            "conclusion": "directional_only" if diff > noise else "no_significant_difference",
            "python": platform.python_version(),
            "platform": platform.platform(),
        }
        text = json.dumps(result, ensure_ascii=False, indent=2)
        print(text)
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(text + "\n", encoding="utf-8")
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
