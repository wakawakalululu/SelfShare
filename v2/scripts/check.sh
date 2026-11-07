#!/bin/bash
# 本地轻量检查回路：只做编译级校验，不跑打包/镜像（那些交给 GitHub Actions）。
# 用法: ./scripts/check.sh [fast]
#   fast  = go vet + cargo check（默认）
#   full  = 额外跑 go test 与内核 cargo test（较慢）
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
MODE="${1:-fast}"

echo "== [1/3] Go server: vet =="
(cd "$ROOT/server" && go vet ./...)

if [ "$MODE" = "full" ]; then
  echo "== [2/3] Go server: test =="
  (cd "$ROOT/server" && go test ./...)
  echo "== [3/3] Rust: core tests =="
  (cd "$ROOT/../desktop/core" && cargo test --quiet)
else
  echo "== [2/3] Go server: build =="
  (cd "$ROOT/server" && go build ./...)
  echo "== [3/3] Rust: core + tauri client check =="
  (cd "$ROOT/../desktop/core" && cargo check --quiet)
  (cd "$ROOT/client/src-tauri" && cargo check --quiet)
fi

echo "OK"
