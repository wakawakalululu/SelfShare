# AGENTS.md · SelfShare 项目协作规范

> 本文件是仓库内所有 AI 编程助手与专家团的**最高优先级**规范。
> 优先级：`AGENTS.md` > `软件开发专家团/SKILL.md` > 各角色子流程 / 参考知识库。
> 若专家团示例路径、流程与本文件冲突，以本文件为准，并在交付说明中写明采用的目录映射。
> 组织方式参考 `genapohub/software-dev-team`（MIT）；仓库内 `数据分析汇报专家团/` 是同结构的专家包，但与本代码库无关，不要改动它。

## 1. 项目定位

自建的跨主机文件夹同步：一台机器 `server`，另一台凭一次性配对码 `pair`，两端内容自动一致，冲突保留双方、不丢数据。

- **v1**：Python 3.9+ 服务端/CLI（`selfshare/`）+ Rust 同步内核（`desktop/core/`）+ Flutter 桌面端（`desktop/app/`）。
- **v2**：Go 1.24 服务端（`v2/server/`）+ Tauri 2 / Svelte 4 客户端（`v2/client/`），同步逻辑仍委托 `desktop/core` 的 `selfshare-core`。
- 两代实现 **HTTP API 兼容、磁盘数据布局一致、可混跑**；老客户端靠 `ServiceVersion = "1.0"` 继续工作。

## 2. 版本口径（禁止混用）

| 概念 | 值 | 依据 |
| --- | --- | --- |
| v1 Python 包 | `1.3.0` | `pyproject.toml:7` |
| Rust `selfshare-core` | `1.0.0` | `desktop/core/Cargo.toml:3` |
| v2 发行版 | `2.0.0` | `v2/server/cmd/selfshare-server/main.go:24`、`v2/client/package.json:3` |
| 协议版本 | `1.0`（**不是发行版本**） | `v2/server/internal/api/api.go:30`、`selfshare/server.py:128` |
| 主分支 / 标签 | `master` / `vX.Y.Z` | `CONTRIBUTING.md:70-72` |

## 3. 目录地图

| 路径 | 职责 | 改动前必读 |
| --- | --- | --- |
| `selfshare/` | v1 服务端、CLI、三方合并、配对、P2P（**仅标准库**） | `selfshare/sync.py` 顶部 8 情形表 |
| `tests/` | Python `unittest` 31 例（sync 20 / p2p 6 / pairing 5）+ 可选 DLL 冒烟 6 例（`test_core_dll.py`，`SELFSHARE_CORE_DLL` 门控）；`external_server.py` 可把同一套用例打到 Go 二进制 | `CONTRIBUTING.md:59-66` |
| `desktop/core/` | Rust 内核 + 19 个 C ABI + 独立 CLI | `desktop/core/include/selfshare_core.h` |
| `desktop/app/` | Flutter GUI / 托盘 / 开机自启 | `desktop/app/lib/rust_bridge.dart` |
| `v2/server/` | Go `net/http` + `modernc.org/sqlite`；API / store / 配对 / peers | `v2/server/internal/api/api.go:3-8` 路由表 |
| `v2/client/` | Svelte 前端 + Tauri Rust（20 个 IPC 命令） | `v2/client/src-tauri/tauri.conf.json` |
| `v2/scripts/` | 构建、检查、并发基准 | `v2/scripts/check.sh` |
| `docs/`、`.github/wiki/` | Jekyll 文档站与 wiki | `docs/_config.yml` |
| `deploy/`、`v2/server/deploy/` | systemd / Windows 计划任务 / Docker 部署 | `deploy/systemd/*.service` |
| `.github/workflows/` | 5 条流水线：`ci.yml`、`ci-v2.yml`、`pages.yml`、`release.yml`、`build-test-deploy.yml` | 对应 yml |
| `PROJECT_STATUS.md` / `v2/RELEASE_SUMMARY.md` / `CHANGELOG.md` | 状态快照 / 发布验证记录 / 对外发布说明 | 文件首节 |

`v2/deploy/docker/`、`v2/.github/workflows/` 为空目录；GitHub Actions 只识别仓库根 `.github/workflows/`，**不要**在 `v2/` 下新建工作流。

## 4. 命令速查（以 `CONTRIBUTING.md` 与 CI 为准）

```bash
# Python v1（仓库根）
python -m compileall -q selfshare tests
python tests/test_sync.py -v
python tests/test_p2p.py -v
python tests/test_pairing.py -v
python selfshare.py server
python selfshare.py pair <dir> --url http://<host>:8484 --code SS-XXXX-XXXX-XXXX

# 跨实现兼容（同一套 Python 用例打到真实 Go 二进制；路径用绝对路径）
# PowerShell:
$env:SELFSHARE_SERVER_BIN = (Resolve-Path 'v2/server/bin/selfshare-server.exe').Path
python tests/test_sync.py -v
python tests/test_p2p.py -v
Remove-Item Env:SELFSHARE_SERVER_BIN
# bash / WSL / CI:
SELFSHARE_SERVER_BIN="$(pwd)/v2/server/bin/selfshare-server" python tests/test_sync.py -v

# 远程构建 ↔ 本地验证循环（本机无 cargo/go 时用 CI 产物；详见 CONTRIBUTING「远程构建 ↔ 本地验证循环」）
python desktop/scripts/ci_fetch.py fetch selfshare-core-windows --out .ss-artifacts
SELFSHARE_CORE_DLL="$(pwd)/.ss-artifacts/selfshare_core.dll" python tests/test_core_dll.py -v

# Rust 内核
cd desktop/core && cargo build --release && cargo test --release
cargo test --release --test integration -- --test-threads=1

# Go 服务端
cd v2/server && go test ./... && go vet ./... && go test -race ./...
make build            # 输出到 bin/selfshare-server（被忽略）
make docker            # 镜像 + /api/ping 冒烟

# Tauri 客户端（frontendDist 指向 ../dist，必须先跑前端构建）
cd v2/client && npm ci && npm run build
cd src-tauri && cargo build && cargo test --test engine_state

# Flutter 桌面端（改 GUI 时）
cd desktop/app && flutter analyze && flutter build windows --release

# 基准（手动，不进 PR 门禁；需先构建 Go 二进制）
python v2/scripts/bench_upload.py --server v2/server/bin/selfshare-server.exe
```

Windows runner 上跑 CLI 冒烟需 `PYTHONUTF8=1` / `PYTHONIOENCODING=utf-8`（`ci.yml:18-21`）。Go 二进制**只认命令行参数**（唯一例外：内部读 `SELFSHARE_SEAL_KEY`，跨实现混跑勿设置，见 `v2/README.md` 服务端配置一节）。

两处实测易踩坑（2026-11-07 多代理评审核实）：

- `make build` 产出 `bin/selfshare-server`（**无扩展名**）；Windows 本地的 `.exe` 由 `make build-windows` 或 `v2/scripts/build.sh server-windows` 产出，别把它当 `make build` 的默认产物。
- `v2/server/internal/store/registry.go:256` 实际会读 `SELFSHARE_SEAL_KEY`，Python 端不读；部署文档曾写「不读 `SELFSHARE_*`」，2026-11-08 已改为「唯一例外 `SELFSHARE_SEAL_KEY`」并加混跑警示（`v2/README.md`、`v2/server/Dockerfile`、`docker-compose.yml`）。显式设置该变量会让两端 `token_sealed` 解封密钥不同、配对兑换跨实现失败。**处置待拍板（`docs/decisions/OPEN-DECISIONS.md` O-4），拍板前不要在部署里设置它。**

## 5. 代码与协议红线（违反即打回）

1. **数据不丢**：冲突一律保留双方，`名字 (冲突副本-从 主机 时间).ext`；删除撞编辑保留编辑；`head_rev` 单调递增、`versions` 只追加；禁止静默覆盖。
2. **协议兼容**：改 `/api/*` 路由、错误码、`server.json` / `vaults/<id>/vault.db` / `blobs/aa/<sha256>` / `paircodes.json` / `peers.json` 布局，必须 Python 与 Go 两端同步改，并跑通跨实现兼容套件；`ServiceVersion` 不得当发行版本改。
3. **原子写与路径**：所有元数据/配置写入走 `atomic_write*`（同目录临时文件 + fsync + replace）；相对路径统一经 `norm_rel`、拒绝 `..`；blob 摘要严格 `^[0-9a-f]{64}$`。
4. **安全**：Bearer / `X-Vault-Token`、配对码、`*.pem` / `*.key` / `.env` / `server.env`、`token_sealed` 密钥不得出现在代码、文档、提交信息、日志与示例里；`config.json` 落盘 `0600`；鉴权顺序保持「先判 vault 存在性再校验令牌」，避免 401 泄露路由差异。
5. **依赖纪律**：Python 只用标准库；Rust / Go / Node 新增依赖必须同步 `Cargo.lock` / `go.sum` / `package-lock.json`。
6. **产物不入库**：`**/target/`、`**/node_modules/`、`v2/server/bin/`、`v2/client/dist/`、`src-tauri/gen/schemas/`、各类二进制与密钥文件已由 `.gitignore` 忽略；**禁止 `git add -A` / `git add .`**，一律显式路径暂存。
7. **不虚构验证**：测试、构建、冒烟必须实跑；未跑的项目在交付说明里标「未验证」。并发基准对负载敏感，**不得当作量化 SLA**（`v2/RELEASE_SUMMARY.md` §2.2）。
8. **最小变更**：迭代与 BugFix 不重写既有实现、回归率 0；新增 C ABI 必须同步 `desktop/core/include/selfshare_core.h` 与 `desktop/app/lib/rust_bridge.dart`，新增 IPC 必须接线到前端页面。

## 6. 验证要求

改动同步逻辑必须补测试，至少覆盖：正常路径、双方都改、删除与编辑相撞、peer 不可达时回退中心。

| 层 | 内容 | 对应 CI |
| --- | --- | --- |
| L1 | Python 31 例（sync 20 / p2p 6 / pairing 5）+ 可选 DLL 冒烟 6 例（`test_core_dll.py`，`SELFSHARE_CORE_DLL` 门控） | `ci.yml` `python`；DLL 冒烟已补 CI job，待流水线实跑确认 |
| L2 | Rust 内核 18 例 + 集成测试 | `ci.yml` `rust` |
| L3 | Go 20 例 + `go vet` + `go test -race` | `ci-v2.yml` `server-test` |
| L4 | 跨实现：Python 兼容套件对接真实 Go 二进制 | `ci-v2.yml` `compat` |
| L5 | 前端 `npm run build` + Tauri `cargo check --all-targets`；`engine_state` 2 例 | `ci-v2.yml` `client` 前端构建；`ci.yml` `v2-client` 已补 `cargo test --test engine_state`（已补 CI job，待流水线实跑确认） |
| L6 | Flutter `analyze` + Windows 构建 | `ci.yml` `gui` |
| L7 | Docker 镜像 `/api/ping`、二进制 `--version` / HTTPS、Release 资产 | `ci.yml` `v2-server`、`release.yml` |

没跑过的层要写明原因（如无 Docker 引擎、无 gcc/cgo、无 Flutter SDK），不得用「应该没问题」代替。

**当前验证缺口（静态盘点，不是已承诺能力）**：DLL 冒烟 6 例与 `engine_state` 2 例已补 CI job（本轮 W1，仅在 `ci.yml` 增加 job / 步骤，尚未 push 实跑，待流水线实跑确认，**不得声称已被 CI 覆盖**）；HTTPS 自签与 `/api/pair` 冒烟仍无 CI。涉及这些场景时必须补用例并说明验证方式。四类必测中「peer 不可达回退」的缺口已于 2026-11-08 补独立断言（`tests/test_p2p.py::PeerFallbackTestCase`）。

## 7. 交付物归档映射（专家团按此落盘，不另建体系）

| 类型 | 位置 |
| --- | --- |
| 需求边界 / 增量需求卡 / API 契约 / 存储布局 / 同步语义 / ABI 与 IPC 契约 | `docs/contracts/` |
| 架构决策、未决项 | `docs/decisions/ADR-XXX.md`、`docs/decisions/OPEN-DECISIONS.md` |
| 过程性验证记录（命令输出、本机路径） | `.codebuddy/skills/软件开发专家团/memory/YYYY-MM-DD.md`；发布级验证结论并入 `v2/RELEASE_SUMMARY.md` |
| 用户文档、口径修订 | `docs/`、`.github/wiki/`、`README.md`、`v2/README.md`、`CHANGELOG.md` |
| 阶段性复盘、风险编号 | `PROJECT_STATUS.md`（`R*` 风险 / `P*` 计划） |
| 专家团记忆 | `.codebuddy/skills/软件开发专家团/memory/`（`MEMORY.md`、`project-tracker.md`、当日日志） |

上述目录按需要创建，不要预建空目录；已有文档优先更新，避免同一事实多处维护。

`docs/` 是 Jekyll 文档站 source（`pages.yml`），`docs/_config.yml` 已配置 `exclude: [qa]`；`docs/contracts/` 与 `docs/decisions/` 公开，qa 为站点层剪枝。**内部验证记录、含本机路径或进程信息的材料不得放入 `docs/`**（过程性正文归 `.codebuddy/skills/软件开发专家团/memory/`，`docs/qa/` 仅留简短索引）。

## 8. 提交、分支与发布

- 提交信息 `type(scope): summary`（英文祈使、≤72 字符）；body 必含 **基线 / 范围 / 验证 / 未验证 / 关联编号（R*、P*）/ 追溯引用**，模板见 `PROJECT_STATUS.md` §5.2。
- 主分支 `master`；`origin/main` 仅含 Initial commit、待人工归档；远程同名 tag `master` 会造成 refspec 歧义，需要写全 `refs/heads/master:refs/heads/master`。
- `git commit` 由主控统一执行；**`git push` 必须用户明确说出「push / 推送 / 推远程」才可执行**，「保证发布顺畅」不算授权。
- `v*` 标签触发 `release.yml`：Windows 便携包、v1 服务端包、Go 五平台二进制、Tauri NSIS 安装包，按 `release.yml:208-211` 的 glob 共 **8 个资产**（`v2.0.0` 历史发布为 7 个，新增 `v2-client-bundle` 后为 8 个，待流水线实跑确认）；`dist/v2/*.exe` 会重复命中 Windows 服务端 exe。notes 从 `CHANGELOG.md` 的 `# [vX.Y.Z]` 一级标题提取，标题格式不能改。

## 9. 专家团使用

- 位置 `软件开发专家团/`，主控 `SKILL.md`，专家包入口 `agents/lead.md`，清单 `.box-agent-plugin/plugin.json`。
- 触发：新功能、改同步/配对/P2P 逻辑、修 Bug、API 或数据布局变更、发布与文档口径核对、跨栈一致性评审。
- 启用顺序：**先读本文件 → 再读 `memory/MEMORY.md` 与 `project-tracker.md` → 判轨道 → 定最小阵容 → 过 G0**。
- 两种执行模式（多代理并行 / 单代理切换视角）门禁一致。子代理禁止 git 写操作、禁止嵌套委派、禁止共享 TodoList；主控亲自跑构建与测试验收，子代理自证不算验收。
- 收尾：写回记忆，输出决策面板（结论先行、比选表、待拍板清单），并把未验证项、遗留项单列。

## 10. 已知产品边界（不是缺陷，改动前先确认是否要维持）

P2P 仅局域网、无公网穿透/中继；单文件 2 GiB 上限、改一次整体重传、无分块增量；不保留 Windows ACL / 符号链接 / 空目录；服务端单机 SQLite，面向个人与小团队。上述限制必须在 README / docs 中保持可见。
