# 贡献指南

## 开发环境

- Python 3.9+（服务端与 CLI，无第三方依赖）
- Rust stable（桌面内核）
- Flutter 3.19+（桌面界面，可选）

## 本地验证

提交前请跑完整回归：

```bash
# Python
python -m compileall -q selfshare tests
python tests/test_sync.py
python tests/test_p2p.py
python tests/test_pairing.py

# 跨实现兼容（同一套 Python 用例打到真实 Go 二进制；路径用绝对路径）
# bash / WSL / CI：
SELFSHARE_SERVER_BIN="$(pwd)/v2/server/bin/selfshare-server" python tests/test_sync.py -v
SELFSHARE_SERVER_BIN="$(pwd)/v2/server/bin/selfshare-server" python tests/test_p2p.py -v

# Rust
cd desktop/core
cargo build --release
cargo test --release

# Flutter（如改动 GUI）
cd desktop/app
flutter analyze
flutter build windows --release

# v2（Go 服务端 + Tauri 客户端）
cd v2/server
go test ./... && go vet ./...
cd ../client && npm ci && npm run build
cd src-tauri && cargo build && cargo test --test engine_state

# HTTPS 自签 + GET /api/pair 冒烟（bash/WSL；复现 ci-v2.yml `compat` 同名步骤）
d="$(mktemp -d)"
(cd v2/server && go build -o "$d/selfshare-server" ./cmd/selfshare-server)
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj "/CN=localhost" \
  -keyout "$d/key.pem" -out "$d/cert.pem"
"$d/selfshare-server" --root "$d/data" --host 127.0.0.1 --port 18585 \
  --cert "$d/cert.pem" --key "$d/key.pem" --quiet > "$d/server.log" 2>&1 &
pid=$!
trap 'kill "$pid" 2>/dev/null; rm -rf "$d"' EXIT
for i in $(seq 1 30); do
  curl -kfsS --max-time 2 https://127.0.0.1:18585/api/ping -o "$d/ping.json" 2>>"$d/probe.log" \
    && curl -kfsS --max-time 2 https://127.0.0.1:18585/api/pair -o "$d/pair.json" 2>>"$d/probe.log" && break
  sleep 0.5
done
grep -q '"version":"1.0"' "$d/pair.json" && grep -q '"pairing":true' "$d/pair.json"

# tag 存在性断言（复现 release.yml `publish` 的 Assert requested tag exists；与 dispatch "Existing tag" 输入一致）
TAG="v2.0.0"
test "$(git tag -l "$TAG")" = "$TAG" && git rev-parse --verify --quiet "refs/tags/$TAG"

# 并发上传基准（回到仓库根后执行，需先构建 Go 二进制）
cd ../../..
python v2/scripts/bench_upload.py --server v2/server/bin/selfshare-server.exe
python v2/scripts/bench_ab.py --server-a v2/server/bin/selfshare-server.exe --build-baseline --repeats 3
```

## 远程构建 ↔ 本地验证循环

本机缺少 `cargo` / `go` / `flutter` / `docker` 时，用远程流水线当编译农场，本地只跑测试：

1. **本地开发**：改 `desktop/core/`（Rust）、`v2/server/`（Go）等，本地能跑的层先跑（`compileall`、纯 Python 套件）。
2. **推送触发构建**：push 到 `master` 后 `ci.yml` 自动编译并上传 Rust 内核产物 `selfshare-core-windows`（`selfshare_core.dll`），`ci-v2.yml` 上传 5 平台 Go 二进制 `server-<goos>-<goarch>`。
3. **下载产物**（无 `gh` CLI 也可用；鉴权优先 `GITHUB_TOKEN`，否则复用本机 git 凭据，不回显）：

   ```bash
   python desktop/scripts/ci_fetch.py runs --workflow ci.yml --limit 5
   python desktop/scripts/ci_fetch.py fetch selfshare-core-windows --out .ss-artifacts
   python desktop/scripts/ci_fetch.py fetch server-windows-amd64 --workflow ci-v2.yml --out .ss-artifacts
   ```

4. **本地测试**：

   ```bash
   SELFSHARE_CORE_DLL="$(pwd)/.ss-artifacts/selfshare_core.dll" python tests/test_core_dll.py -v
   SELFSHARE_SERVER_BIN="$(pwd)/.ss-artifacts/selfshare-server-windows-amd64.exe" python tests/test_sync.py -v
   SELFSHARE_SERVER_BIN="$(pwd)/.ss-artifacts/selfshare-server-windows-amd64.exe" python tests/test_p2p.py -v
   ```

5. **回到第 1 步**：按失败输出继续开发。release 便携包（`SelfShare-<ver>-windows-x64.zip`）里的 `selfshare_core.dll` 同样可直接作为 `SELFSHARE_CORE_DLL` 使用；`.ss-artifacts/` 已被 `.gitignore` 忽略。

## 代码约定

- Python 只用标准库，不引入第三方包
- 所有文件写入走 `atomic_write`，避免中断产生半截文件
- 路径必须经 `norm_rel` 规范化，拒绝 `..`
- 冲突处理遵循「保留双方」原则，不得静默覆盖
- 新增 C ABI 时同步更新 `desktop/core/include/selfshare_core.h` 与 `desktop/app/lib/rust_bridge.dart`

## 提交信息

采用 `type(scope): summary` 形式：

```text
feat(p2p): peer registration and discovery
fix(sync): remote delete no longer overwrites local edit
docs(wiki): add FAQ
```

## 测试要求

改动同步逻辑必须补测试，且要覆盖：

- 正常路径
- 冲突路径（双方都改）
- 删除与编辑相撞
- 节点不可达时的回退

## 分支与发布

- 主分支 `master`
- 版本标签 `vX.Y.Z`
- 打标签（或 `workflow_dispatch` 指定 tag）后 `release.yml` 构建 Windows 便携包、v1 服务端包、v2 五平台 Go 二进制与 v2 Tauri 客户端安装包，并创建 Release（8 个资产；历史 `v2.0.0` 为 7 个）。8 资产口径已由演练 run `42424638532` 实证。
- **下载提示**：当前 `get_latest_release` 是演练发布 `v1.1.0`（8 资产，由 `2.0.0` 代码构建，notes 为历史 v1.1.0 说明），按用户决定保留、不删除；要获取稳定版请显式指定 `v2.0.0`（7 资产），不要按 latest 判定版本号。

## CI/CD 工作流

- `ci.yml` / `ci-v2.yml`：PR 与全平台构建测试门禁（Python / Rust / Flutter / Tauri / Go）
- `pages.yml`：`docs/` Jekyll 文档站 -> GitHub Pages
- `release.yml`：`v*` 标签 -> GitHub Release
- `build-test-deploy.yml`：`master` / `v*` 上的发布流水线，先跑构建与回归测试，再构建并冒烟 Docker 镜像，推送到 `ghcr.io/<owner>/<repo>`（`latest`、版本、`sha-xxxxxxx` 标签），最后可选 SSH 滚动部署到自托管服务器

推送 GHCR 用内置 `GITHUB_TOKEN`；远程部署所需的变量与密钥列在 `build-test-deploy.yml` 顶部注释中。未配置 `DEPLOY_HOST` 时只发布镜像，不会接触线上服务。

## 报告问题

请附上：

```bash
selfshare --version
selfshare doctor <同步目录>
```

以及复现步骤、操作系统、是否启用 `--p2p`。**不要粘贴令牌。**
