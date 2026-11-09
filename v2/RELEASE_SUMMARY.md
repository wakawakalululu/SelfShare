# SelfShare v2 发布总结与验证记录

| 项 | 值 |
| --- | --- |
| 适用对象 | 项目维护者与贡献者 |
| 版本 | 服务端 `2.0.0`（`--version`）；HTTP `ServiceVersion` 保持 `1.0` 以兼容 v1 客户端 |
| 记录日期 | 2026-11-04（2026-11-05 推送与 CI 复核更新） |
| 基线 | `master` `42d67645af534c5eec3c43668311604616381745`；`v1.3.0` tag `714e9ee91cfe0e69ad9fb25e4c3fdc9a37f36d85` |
| 状态 | **本表全文（含 §2 起）是 v2.0.0 发布当时（2026-11-04/05）的历史验证记录，不作当前口径**。当前基线、稳定版 / 演练发布关系、验证例数与后续路线以 `PROJECT_STATUS.md` §0 为唯一入口；`AGENTS.md` §6 为分层门禁。当时数据：v2.0.0 附注 tag `1c8559c`、Release 7 资产、notes 51 行；下文数字（L1 31 / L4 26 / DLL 6 例）仅为当时实测 |
| 数据来源 | 本机命令输出 + GitHub Actions / Releases API；对照 `v2/README.md`「验证状态」、`PROJECT_STATUS.md` §1.1.1、`CHANGELOG.md` `[v2.0.0]` |

---

## 1. 改动概述

### 1.1 Go 服务端（`v2/server`）

| 位置 | 改动 | 目的 | 影响范围 |
| --- | --- | --- | --- |
| `internal/api/api.go`、`internal/store/vault.go` | 新增 `store.OpenBlobStore`（仅创建 `blobs/` 目录的轻量句柄）；`blob` / `blobbulk` / `peers` / `peer` 路由改用它；`Vault.Close()` 兼容 `db == nil` | 消除高频请求「打开 SQLite → PRAGMA → schema 检查 → 关闭」的开销；manifest / commit / history / stat 仍走完整 `OpenVault`，保留 Windows 上按需开关 DB 以便删库/整目录拷贝 | 仅上述 4 类路由；鉴权、请求格式、磁盘布局不变 |
| `cmd/selfshare-server/main.go` | 新增 `--version`（输出 `2.0.0`）、`serverVersion` 常量 | 部署后快速校验二进制 | 入口参数，不影响运行逻辑 |
| `internal/store/pairing_test.go`、`peers_test.go`、`registry_test.go` | 新增 8 个单元测试 | 覆盖配对码一次性/过期/吊销/归一化、节点注册/心跳/注销/TTL/库隔离、建库/令牌校验/磁盘格式复用 | Go 测试用例数 12 → 20 |
| `Dockerfile` | 新增 `HEALTHCHECK`（`wget` 探测 `/api/ping`） | 镜像自带存活检查 | 镜像运行阶段 |
| `v2/scripts/bench_upload.py` | 新增并发上传基准（PUT + sha256 回读校验） | 可复跑的性能回归与正确性验证 | 新增脚本，不参与服务端构建 |
| `release.yml` | 新增 `v2-server-assets` job 与 `publish` 资产清单 | Release 附带 5 平台 Go 二进制 | 发布流程 |

保持不变：标准库 `net/http` + `modernc.org/sqlite`（纯 Go、`CGO_ENABLED=0`）、HTTP API 全路由、Bearer 鉴权、流式 blob 写入（sha256 校验 + 临时文件 `Sync` → `Rename`）、`server.json` / `vault.db` / `blobs/aa/<sha256>` / `paircodes.json` / `peers.json` 与 v1 逐字节兼容。

### 1.2 Rust + Tauri 客户端（`v2/client`）

| 位置 | 改动 | 目的 | 影响范围 |
| --- | --- | --- | --- |
| `src-tauri/Cargo.toml` | `selfshare-core` 启用 `features = ["tls"]`；客户端 `ureq` 启用 `json, tls` | 引导端点与同步数据面均可直连 `--cert/--key` 的 HTTPS 服务端 | 依赖特性；离线编译通过 |
| `src-tauri/src/sync/state.rs`、`sync/engine.rs`、`sync/mod.rs` | 新增 `Settings` / `PeerEntry` DTO；`settings.json` 持久化；`pause_all` / `resume_all` / `sync_all` / `tray_state` / `list_peers`；`start_watch` 从设置读取巡检间隔与 P2P 开关；`list_mounts` 反映 `paused` | 配置可持久化、全局暂停/恢复、一键同步、在线节点查询；P2P 不再写死关闭 | 引擎编排层；同步算法仍委托 `desktop/core` |
| `src-tauri/src/commands.rs`、`lib.rs` | 新增 7 个 IPC：`get_settings`、`save_settings`、`pause_sync_all`、`resume_sync_all`、`is_sync_paused`、`sync_all_mounts`、`list_peers`；注册命令总数 20 | 把此前未接线的能力与前端联通 | IPC 层 |
| `src-tauri/src/tray.rs` | 托盘 `with_id("main")`；菜单「立即同步全部 / 暂停同步 / 恢复同步 / 退出」直接作用于 `SyncEngine`；每 5 秒刷新 tooltip | 参考 [syncthingtray](https://github.com/Martchus/syncthingtray) 的实时状态与菜单控制 | 托盘层；暂停时 `start_watch` 拒绝启动 |
| `src/pages/*.svelte`、`src/App.svelte` | 仪表盘轮询 + 统计 + 暂停/恢复/一键同步/导航；设备页连接探测、配对令牌复制、在线节点列表；设置页改用后端持久化且只暴露生效字段；文件夹页预填默认服务器地址；App 显示 `get_version` 版本号 | 前端与新增 IPC 联调 | 5 个页面 + 应用壳 |
| `svelte.config.js`、`src/styles.css`、`src/main.ts`、`index.html`、`src-tauri/tauri.conf.json` | 补 `vitePreprocess()`、全局样式、Svelte 4 `new App()` 挂载、移除 `/src/styles.css` 直链、移除不存在的 `icon.icns` | 修复前端构建失败与打包缺图标 | 前端工程；`package-lock.json` 生成 |
| `src-tauri/tests/engine_state.rs` | 新增 2 个集成测试（设置往返、暂停/恢复状态） | 不依赖 GUI 验证新增引擎逻辑 | 测试层 |

### 1.3 工程与文档

| 位置 | 改动 | 目的 |
| --- | --- | --- |
| 根 `.gitignore` | 追加 `**/target/`、`**/node_modules/`、`v2/server/bin/`、`v2/client/dist/`、`v2/client/src-tauri/gen/schemas/` 与 `*.o/*.d/*.rlib/*.rmeta/*.pdb/*.lib/*.dll/*.so/*.dylib/*.exe` | 阻断约 8 GB 构建产物误入库 |
| `.github/workflows/ci-v2.yml` | 新增根级 v2 工作流，含 `server-test`、`server-build`、`compat`、`docker`、`client` 五个 job | 覆盖 Go 竞态测试、5 平台构建、协议兼容、Docker 冒烟、Tauri 构建；删除 GitHub 不识别的 `v2/.github/workflows/ci.yml` |
| `.github/workflows/release.yml` | `publish.needs` 改为 `[windows-bundle, v2-server-assets]`；新增下载 `v2-server-assets` 步骤；`files` 增加 `dist/v2/selfshare-server-*` | 同一 Release 同时发布 v1 与 v2 服务端资产 |
| `v2/ARCHITECTURE.md` | 重写 | 清除收敛前草图中的 `chi`、`SELFSHARE_*`、`--data-dir`、客户端自带 SyncEngine 等失效描述 |
| `v2/README.md`、根 `README.md`、`CHANGELOG.md`、`CONTRIBUTING.md`、`PROJECT_STATUS.md` | 更新验证状态、部署入口、`[Unreleased]` 记录、v2 验证命令、提交模板与追溯索引 | 使文档与实现一致 |
| `docs/index.md`、`docs/gui.md`、`desktop/README.md`、`.github/wiki/快速开始.md` | 快速开始改为 v1.3.0 配对流程；C ABI 口径 17 → 19 | 消除文档漂移 |
| `CHANGELOG.md`、`.github/workflows/{ci.yml,ci-v2.yml,pages.yml,release.yml}`、`v2/README.md`、`v2/ARCHITECTURE.md` | v2.0.0 发布准备：版本锚点、notes 提取修复、主分支统一、软失败移除、删除 `v2/superseded/` 并同步引用 | 使 Release notes 与目标版本一致，消除误构建与 CI 掩盖失败 |

---

## 2. 测试验证结果

### 2.1 汇总

| 类别 | 测试项 | 方法 / 命令 | 结果 | 关键数据 |
| --- | --- | --- | --- | --- |
| Go 单元测试 | `go test ./...` | 本机 Go 1.24、`GOPROXY=off` | 通过 | **20/20**；12 个原有 API/存储兼容测试 + 8 个新增单测 |
| Go 静态检查 | `go vet ./...` | 同上 | 通过 | 0 issue |
| Go 编译 | `go build -trimpath` | Windows + 交叉编译 linux/amd64 | 通过 | 生成 `selfshare-server.exe` 与 linux/amd64 二进制 |
| Python 原生回归 | `tests/test_sync.py`、`test_p2p.py`、`test_pairing.py` | 本机 Python 3.13 | 通过 | **29/29**（19 + 5 + 5） |
| Python 协议兼容 | `SELFSHARE_SERVER_BIN=<Go 二进制>` + `test_sync.py` / `test_p2p.py` | 对**真实 Go 进程**跑 v1 套件 | 通过 | **24/24**（19 + 5）；覆盖三方合并、冲突保留、删除传播、历史、P2P HMAC |
| Rust 同步内核 | `cd desktop/core && cargo test --offline` | 离线 | 通过 | **18/18**（7 单元 + 11 集成） |
| Tauri 客户端 | `cargo build --offline`（含 `tls`）、`cargo test --test engine_state` | 离线 | 通过 | 编译 0 error；2/2 状态测试 |
| 前端构建 | `npm install`（生成 lock）、`npm run build` | Vite + Svelte 4 | 通过 | 42 模块，生成真实 `dist/`；无 a11y 警告 |
| 二进制部署（Windows） | `selfshare-server.exe --version` + Python 兼容套件 | 本机 | 通过 | `2.0.0`；自动建 `default` 库并打印配对码 |
| 二进制部署（Linux） | WSL Ubuntu 24.04 运行 linux/amd64 二进制 | `/api/ping`、日志、数据目录 | 通过 | `--version 2.0.0`；`server.json` / `vaults/default/vault.db` / `blobs/` 布局正确 |
| HTTPS | 自签证书 + `--cert` / `--key` | `Invoke-WebRequest -SkipCertificateCheck` 访问 `/api/ping` | 通过 | `{"service":"selfshare","version":"1.0","engine":"go","vaults":1}`；客户端 TLS 已编译启用 |
| 并发基准 | `v2/scripts/bench_upload.py --files 32 --size-kb 256 --workers 16` | 16 并发 PUT + 逐项 GET 回读 | 通过（正确性） | 32/32 摘要一致；首次观测 0.372 s / 21.5 MB/s，本轮复核与口径校正见 §2.2 |
| Docker | WSL 内 `wget -qO-` 与 `wget --spider` 探测 `/api/ping` | 仅验证 HEALTHCHECK 与 compose 等价命令 | 通过 | 两种命令均成功；镜像构建与容器内健康检查**未实测**，见 §4.1 |
| 配置与静态检查 | `read_lints`、PyYAML 解析 4 个工作流 | 本机 | 通过 | lint 0；`ci-v2.yml` 5 / `ci.yml` 3 / `pages.yml` 1 / `release.yml` 3 个 job 解析正常 |

### 2.2 并发基准：首次观测与本轮复核

固定负载：32 个 256 KiB 随机内容块（共 8 MiB），16 并发 PUT，逐项 GET 校验 sha256。

**首次观测**（低负载、单独运行，非受控条件）：

| 指标 | 优化前 | 优化后 | 变化 |
| --- | --- | --- | --- |
| 总耗时 | 12.23 s | 0.372 s | 下降约 97.0% |
| 吞吐 | 0.65 MB/s | 21.5 MB/s | 约 33 倍 |
| 成功上传 / 回读一致 | 32/32 | 32/32 | 不变 |

**本轮复核**（2026-11-04 晚，同机；临时把 `api.go` 还原为「所有请求都打开完整 Vault」构建同轮基线，测后已恢复并用 `go test ./...` 验证）：

| 场景 | 优化前（同轮基线） | 优化后 | 说明 |
| --- | --- | --- | --- |
| 空闲、同轮 A/B | 1.579 s / 5.07 MB/s | 1.732 s / 4.62 MB/s | 差异落在测量噪声内，**未复现 33 倍** |
| 空闲、优化后连跑 3 次 | — | 0.676 / 0.680 / 0.759 s；10.5–11.8 MB/s | 无其它测试并行 |
| 与 Python / Rust / 交叉编译并行 | — | 10.963 s / 0.73 MB/s | 负载干扰显著 |

**口径结论**：基准对 CPU、磁盘负载与缓存状态高度敏感。首次观测的「约 33 倍」是低负载单次结果，未在同轮 A/B 中复现，不能作为量化 SLA；`OpenBlobStore` 消除了每请求打开 SQLite 的确定性开销，方向正确，但收益需在固定硬件、预热、多次取中位数的受控环境中重新量化。所有场景的 32/32 上传与 sha256 回读均通过。

**改动依据**：`blob` / `blobbulk` / `peers` 请求原先每请求执行 `OpenVault`（`sql.Open` + `PRAGMA busy_timeout/journal_mode/synchronous` + 6 条 `CREATE TABLE IF NOT EXISTS` + `INSERT ... ON CONFLICT`）；改为 `OpenBlobStore` 后只做文件系统操作，完整 Vault 仍按需打开、用完即关。

复跑（从仓库根，需空闲环境）：

```bash
# 单次基准（正确性 + 吞吐）
python v2/scripts/bench_upload.py --server v2/server/bin/selfshare-server.exe \
  --files 32 --size-kb 256 --workers 16

# 同轮 A/B：固定 seed、预热、ABBA 交替、多次中位数；
# --build-baseline 用 go build -overlay 生成「优化前」二进制，不改仓库源码
python v2/scripts/bench_ab.py --server-a v2/server/bin/selfshare-server.exe \
  --build-baseline --go go --repeats 3 --out bench-ab.json
```

`bench_ab.py` 输出每侧中位数与 MAD、两个二进制的 sha256，结论为
`no_significant_difference` 或 `directional_only`，**不报告倍数、不做阈值断言**；
脚本不进入 push / PR 门禁（共享 runner 负载抖动大）。

### 2.3 统计口径

- Go 20 = `api_test.go` 7 + `vault_test.go` 5 + `pairing_test.go` 3 + `peers_test.go` 3 + `registry_test.go` 2。
- Python 29 = `test_sync.py` 19 + `test_p2p.py` 5 + `test_pairing.py` 5；其中 24 项通过 `SELFSHARE_SERVER_BIN` 对接 Go 二进制（另 5 项为配对码 CLI 测试，仅对 Python 服务端）。
- Rust 18 = 7 单元 + 11 集成；Tauri 引擎状态测试 2 项单独统计。
- 首次观测倍数按吞吐 `21.5 / 0.65 ≈ 33`、耗时降幅 `1 − 0.372 / 12.23 ≈ 97.0%`；该倍数**未在本轮同轮 A/B 中复现**，见 §2.2。
- 基准为单次本机测量（Windows 临时目录），不作为跨硬件 SLA；复核以受控同轮 A/B 与多次中位数为准。

---

## 3. 部署方式

### 3.1 二进制部署

**获取**：GitHub Release 资产 `selfshare-server-<os>-<arch>[.exe]`，或自行构建：

```bash
cd v2/server
make build                 # 当前平台，输出 bin/selfshare-server
make build-all             # 5 个目标平台
# 或
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags="-s -w" \
  -o bin/selfshare-server-linux-amd64 ./cmd/selfshare-server
```

| 目标平台 | `GOOS/GOARCH` | 产物 |
| --- | --- | --- |
| Linux x86_64 | `linux/amd64` | `selfshare-server-linux-amd64` |
| Linux ARM64 | `linux/arm64` | `selfshare-server-linux-arm64` |
| Windows x86_64 | `windows/amd64` | `selfshare-server-windows-amd64.exe` |
| macOS Intel | `darwin/amd64` | `selfshare-server-darwin-amd64` |
| macOS Apple Silicon | `darwin/arm64` | `selfshare-server-darwin-arm64` |

**启动**（零配置，首次启动自动建 `default` 库并打印地址与 30 分钟有效的配对码）：

```bash
./selfshare-server --root /var/lib/selfshare --host 0.0.0.0 --port 8484
./selfshare-server --version
```

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--root` | `selfshare-data` | 数据根目录，可直接复用 v1 数据目录 |
| `--host` | `0.0.0.0` | 监听地址 |
| `--port` | `8484` | `0` 表示由系统分配随机端口 |
| `--cert` / `--key` | 空 | 同时提供则启用 HTTPS（`ServeTLS`） |
| `--quiet` | `false` | 不打印访问日志与启动配对码 |
| `--version` | — | 打印发行版本并退出 |

要点：服务端**只认命令行参数**，不读 `SELFSHARE_*` 环境变量；`--cert`/`--key` 需成对提供；校验顺序为 `--version` → `curl /api/ping` → 用配对码在客户端 `pair`；systemd 部署可用 `v2/server/deploy/selfshare.service`（专用用户 + 目录加固）。

### 3.2 Docker 部署

```bash
cd v2/server
docker build -t selfshare-server:2 .
docker run -d --name selfshare -p 8484:8484 \
  -v selfshare-data:/data selfshare-server:2
# 或
docker compose up -d
```

自定义监听地址/端口时通过 `CMD` 传参（ENTRYPOINT 固定为二进制）：

```bash
docker run -d --name selfshare -p 8585:8585 -v selfshare-data:/data \
  selfshare-server:2 --root /data --host 0.0.0.0 --port 8585
```

镜像内置特性：

| 特性 | 配置 |
| --- | --- |
| 多阶段构建 | `golang:1.24-alpine`（含 `ca-certificates`、`tzdata`）→ `alpine:3.20` |
| 纯静态二进制 | `CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w"`，无 cgo / gcc 依赖 |
| 非 root 运行 | `adduser -D -u 10001 selfshare` + `USER selfshare`，`WORKDIR /data` |
| 健康检查 | `HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3`，`wget -qO- http://127.0.0.1:8484/api/ping`；运行阶段选 alpine 而非 scratch 即为此保留 `wget` |
| 持久化 / 端口 | `VOLUME ["/data"]`、`EXPOSE 8484` |
| 启动方式 | `ENTRYPOINT ["/usr/local/bin/selfshare-server"]` + `CMD ["--root","/data","--host","0.0.0.0","--port","8484"]` |
| 编排 | `docker-compose.yml` 提供端口映射、命名卷与 `healthcheck`（`curl -fsS` 探测 `/api/ping`） |

注意：`HEALTHCHECK` 与 compose 的 `healthcheck` 端口写死为 `8484`，改端口时需同步修改两处；镜像构建与容器内健康检查本次**未实测**（§4.1）。

---

## 4. 未验证项与风险

### 4.1 因环境限制未实测的项目

| 项目 | 本机限制 | 覆盖方 | 推送后实测结论（2026-11-05） |
| --- | --- | --- | --- |
| Docker 镜像构建与容器内 HEALTHCHECK | 本机与 WSL 均无 Docker 引擎；仅验证 `wget` 等价命令 | `ci-v2.yml` → `docker` | **success**：`docker build` + `docker run` + `/api/ping` 冒烟通过 |
| Linux 竞态检测 `go test -race` | Windows 侧无 gcc / cgo | `ci-v2.yml` → `server-test` | **success**：race 无告警、vet 0 issue |
| Tauri 安装包打包（NSIS / MSI） | 本机只执行 `cargo build` | `ci-v2.yml` → `client` | **success**：`npm ci` → `npm run build` → `npm run tauri build` 完成并上传 exe artifact |
| `npm ci` 可复现安装 | 本机用 `npm install` 生成 lock | `ci-v2.yml` → `client` | **success**（同一 job 内通过） |
| 5 平台二进制运行 | 仅 Windows amd64 与 WSL linux/amd64 实测 | `ci-v2.yml` → `server-build`、`release.yml` → `v2-server-assets` | 5 个交叉编译 job **全部 success**；linux/arm64、darwin 双架构实机运行仍待人工 |
| Release 发布流程 | 需 tag 或 `workflow_dispatch` + 推送 | `release.yml` → `windows-bundle` / `v2-server-assets` / `publish` | **success**：3 个 job 全绿，`v2.0.0` Release 已发布，7 个资产、notes 51 行 |
| GitHub Pages 文档站 | 需推送触发 | `pages.yml` | **success**（deploy 与 pages build and deployment 均成功） |
| Git 提交 / 推送 | 曾因凭据认证失败，凭据更新后恢复 | 不适用 | **已完成**：`master` 与 `v2.0.0` 附注标签均已推送 |
| 根 CI 的 Windows Python job | `CLI smoke` 中文提示在非 UTF-8 stdout 下抛 `UnicodeEncodeError` | 根 `ci.yml` | 首次 **failure**；加 `PYTHONIOENCODING=utf-8` / `PYTHONUTF8=1` 后，最新运行 **7/7 job success**（含 Windows GUI build） |

**最终 CI 结论（2026-11-05）**：`CI`（run `41984388379`）与 `CI v2`（run `41984388385`）均
`completed/success`；`Pages` / `Release` 亦 success。同分支前一次运行被 `concurrency` 取消（cancelled）；
tag `v2.0.0` 触发的根 CI 仍为历史 failure（tag 指向修复前提交 `1c8559c`），不影响已发布资产。

**2026-11-05 06:59 更新**：`v2.0.0` Release 资产为 `SelfShare-2.0.0-windows-x64.zip`、
`selfshare-server-2.0.0.zip` 与 5 个 `selfshare-server-<os>-<arch>`；Release notes 共 51 行，
取自 `CHANGELOG.md` 的 `# [v2.0.0]` 小节，不含 `v1.3.0` 标题。`v2.0.0` tag 仍指向 `1c8559c`，
后续修复不进入已发布资产。

### 4.2 剩余风险

| 编号 | 风险 | 现状 | 处置建议 |
| --- | --- | --- | --- |
| R-A | `master` 与 `origin/main` 指向不同提交（分叉） | **已处理（CI 口径）**：`ci.yml` / `ci-v2.yml` / `pages.yml` 的 `branches` 统一为 `[master]`。分叉分析：`origin/main` 仅含 `78d0293 Initial commit`，无独有功能；`master` 相对其新增 97 文件 / 13383 行 | 待人工：确认 `main` 无使用者后 `git push origin --delete main`；主分支口径以 `master` 为准 |
| R-B | `v2/superseded/server/` 保留早期 chi 实现（配对码空指针、peers stub），且自带 go.mod/Makefile/Dockerfile | **已处理**：目录已删除（13 文件 / 14.66 MB）；`v2/README.md`、`v2/ARCHITECTURE.md`、`CHANGELOG.md` 引用已同步 | 已完成；复核提交中的删除记录 |
| R-C | 根 `ci.yml` 存在 `\|\| true` / `set +e` 软失败 | **已处理并复验**：CLI smoke 去掉 `\|\| true`；Rust 测试改用 `set -o pipefail`；诊断步骤显式 `set +e`。CI 复验发现 Windows Python job 因 `selfshare/cli.py:104` 中文提示 + 非 UTF-8 stdout 抛 `UnicodeEncodeError` | 已加 `PYTHONIOENCODING=utf-8` / `PYTHONUTF8=1` 并保持严格失败；最新 CI 运行 7/7 job success，无需再处理 |
| R-D | `CHANGELOG.md` 缺 `v1.2.0` 小节；`release.yml` 输入示例为 `v1.2.0`；顶部为 `# [Unreleased]` | **已处理**：锚点改为 `# [v2.0.0] — 2026-11-04` 并补全小节；awk 改用 `index()` 匹配、只在一级标题停止，两种 awk 实现均提取 50 行且不含 v1.3.0 标题；输入示例改 `v2.0.0`；已依据 tag 附注与提交历史补写 `# v1.2.0` 小节 | 已完成；重发 `v1.2.0` 时 notes 不再回退整份文件 |
| R-E | `ServiceVersion "1.0"` 与发行版本 `2.0.0` 并存 | 有意保持协议兼容，但易误解 | 文档已区分；API 变更时再提升协议版本 |
| R-F | P2P 默认关闭，且仅支持局域网直连（中心服务端做节点发现与 HMAC 授权） | 设置在 GUI 中开启后生效；无 NAT 穿透/中继 | 如需公网直连，后续补穿透或中继 |
| R-G | 单文件上限 2 GiB、整文件重传、不支持多段 Range；ACL/符号链接/空目录不保留 | v1 既有设计，v2 沿用 | 列入产品迭代，不阻塞本次发布 |
| R-H | CI 依赖外部资源（setup-go/setup-node、`npm ci`、Docker Hub 基础镜像、WiX/NSIS 下载） | 本机验证均为离线缓存 | CI 实跑全部成功，风险已释放 |
| R-I | Tauri 客户端仅 Windows 安装包由 CI 产出；macOS / Linux 客户端无构建与发布 | `ci-v2.yml/client` 已 success 并上传 exe artifact，但 `release.yml` 未包含该资产 | 后续把客户端安装包接入 Release，并扩展 macOS / Linux 平台矩阵 |
| R-J | `v2/client/src-tauri/gen/schemas/`、`dist/`、`bin/` 等生成物已被忽略但本地仍存在 | 不会入库（`git ls-files` 校验 0 命中） | 保持忽略规则；提交时勿使用 `git add -A` |
| R-K | 仓库存在与分支同名的 tag `master`，导致 `git push origin master` 报 `src refspec master matches more than one` | 本地 tag 已删除（`refs/heads/master` 不再歧义）；远程 `refs/tags/master`（`176710f`）仍在 | 待人工：确认无依赖后 `git push origin :refs/tags/master`；推送也可固定写 `refs/heads/master:refs/heads/master` |

---

## 5. 后续建议

### P0：推送后确认（已完成）

1. 【已完成】`ci-v2.yml` 五个 job 全绿（run `41984388385`）：`server-test` race/vet、`server-build` 5 平台、`compat` 24 项 Python 套件、`docker` 镜像与 `/api/ping` 冒烟、`client` NSIS/MSI 打包。
2. 【已完成】`pages.yml` 文档站发布成功，快速开始页与 wiki 已更新为配对流程。
3. 【已完成】`release.yml`（tag `v2.0.0`）三个 job 全绿，Release 发布 7 个资产、notes 51 行取自 `# [v2.0.0]` 小节。
4. 【已完成】根 `ci.yml`（run `41984388379`）7/7 job success；Windows Python 编码缺陷已修复并复验，未恢复 `\|\| true`。
5. 【已完成】提交与推送：`master` 与 `v2.0.0` 附注标签均已推送，工作区干净，`git ls-files` 无构建产物。
6. 待人工：tag `v2.0.0` 触发的历史 CI 失败记录（tag 指向修复前提交），可在 Actions 中忽略，或用 `workflow_dispatch` 对最新代码重跑。

### P1：发布后收尾

5. 【已完成】删除 `v2/superseded/`（13 文件 / 14.66 MB），并同步 `v2/README.md`、`v2/ARCHITECTURE.md`、`CHANGELOG.md` 的引用（R-B）。
6. 【已完成】统一 `ci.yml` / `ci-v2.yml` / `pages.yml` 触发分支为 `[master]`（R-A）；分叉分析确认 `origin/main` 无独有内容，归档仍需人工执行。
7. 在 linux/arm64、darwin/amd64、darwin/arm64、windows/amd64 上分别运行二进制并做 `/api/ping` 与一次 `pair` → `sync` 冒烟（§4.1 第 5 项）。
8. 【已完成】移除根 `ci.yml` 主流程软失败（R-C）；`release.yml` 输入示例与 notes 提取已修复，并补齐 `# v1.2.0` 小节（R-D）；本地同名 tag `master` 已删除（R-K）。

### P2：后续迭代

9. 把 `v2/scripts/bench_upload.py` 纳入定时性能基线，记录不同硬件/平台数据。
10. 将 `ci-v2.yml/client` 产出的 Windows 安装包接入 `release.yml`，并补齐 macOS / Linux 客户端构建与发布（R-I）。
11. 产品能力：增量分块传输、多段 Range、NAT 穿透 / 中继、多用户 ACL（R-F、R-G）。
12. 真实设备端到端 GUI 手测：托盘 tooltip 状态变化、暂停/恢复、设置项对 `watcher::spawn` 的生效、P2P 双节点在线列表与直连回退。

---

## 附录：证据索引

| 内容 | 位置 |
| --- | --- |
| 架构与性能优化说明 | `v2/ARCHITECTURE.md` §2 |
| 验证状态与构建/部署命令 | `v2/README.md`「验证状态」「构建」 |
| 本轮修复与验证汇总 | `PROJECT_STATUS.md` §1.1.1、§5 |
| 变更清单 | `CHANGELOG.md` `# [v2.0.0] — 2026-11-04`（并补 `# v1.2.0 发布说明` 小节） |
| 本地验证命令 | `CONTRIBUTING.md`「本地验证」 |
| CI / 发布定义 | `.github/workflows/ci-v2.yml`、`release.yml`、`ci.yml`、`pages.yml` |
| 性能基准脚本 | `v2/scripts/bench_upload.py`（单次）、`v2/scripts/bench_ab.py`（同轮 A/B、overlay 基线、中位数/MAD） |
| 部署模板 | `v2/server/Dockerfile`、`docker-compose.yml`、`deploy/selfshare.service` |
