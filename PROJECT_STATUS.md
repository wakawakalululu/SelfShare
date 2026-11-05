# 项目状态更新｜2026-11-04

> 仓库：`wakawakalululu/SelfShare`
> 基线：分支 `master` @ `42d6764`（`origin/master`）；最近发布标签 `v1.3.0` @ `714e9ee`（2026-11-03）
> 分析方式：源码 / 文档 / 工作流静态审阅 + Git 索引与打包对象比对
> 状态：本机 PATH 与常见安装路径均未找到 `git` 可执行文件，**未执行任何 `commit` / `push`**；本文为待提交内容与提交规范的准备稿
> 维护约定：阶段性交付后更新本文件，提交信息引用本文的 `R*` 风险编号与 `P*` 计划编号

---

## 1. 变更摘要

### 1.1 本次更新内容

- 新增 `PROJECT_STATUS.md`：汇总已完成项、待办项、风险 / 阻塞点、优先级计划与规范提交信息模板。
- 第一轮仅做盘点；**第二轮（2026-11-04）已完成开发、修复与运行测试**，结果见 §1.1.1。

### 1.1.1 本轮修复与验证结果（2026-11-04）

| 编号 | 状态 | 落地内容 |
| --- | --- | --- |
| R1 | 已修复 | 根 `.gitignore` 补齐 `**/target/`、node_modules、`v2/server/bin/`、二进制扩展名等规则 |
| R2 | 已修复 | 新增根 `.github/workflows/ci-v2.yml`（Go 竞态测试、5 平台构建、协议兼容、Docker 冒烟、Tauri 构建），删除嵌套的无效工作流 |
| R3 | 已修复 | 补 `src/styles.css`、Svelte TS 预处理器、Svelte 4 挂载 API、移除缺失的 `icon.icns`；前端构建通过 |
| R4 | 已解除 | `origin/master` 已推送至 `6768cd3`，`v2.0.0` 附注标签已推送；CI / CI v2 / Pages / Release 全部 success |
| R5 | 已修复 | 客户端启用 `selfshare-core/tls` 与 ureq TLS；P2P 由设置开关驱动（不再写死关闭）；HTTPS 端点实测通过 |
| R8 / R9 | 已修复 | 文档站与 wiki 快速开始更新；`v2/ARCHITECTURE.md` 重写；测试数 / C ABI 口径已统一 |
| R10 | 已修复 | 新增 8 个 Go 单测、并发基准、Linux/Windows 二进制与 HTTPS 实测；Docker 镜像构建与 `go test -race` 已由 CI 通过 |
| R11 | 已修复 | 设置持久化、托盘暂停/恢复/一键同步与实时 tooltip、在线节点列表、未接线 IPC 已接入前端 |
| R12 | 已修复 | 生成 `package-lock.json`；根 `ci.yml` 主流程软失败移除；`ci.yml` / `ci-v2.yml` / `pages.yml` 触发分支统一为 `master`；远程 `origin/main` 归档待人工 |
| R7 | 已修复 | 删除 `v2/superseded/`（13 文件 / 14.66 MB），并同步 `v2/README.md`、`v2/ARCHITECTURE.md`、`CHANGELOG.md` 的引用 |
| 发布阻塞点 | 已修复 | `CHANGELOG.md` 锚点改为 `# [v2.0.0]`；`release.yml` notes 提取改用 `index()` 定位、只在一级标题停止，两种 awk 实现均提取 50 行且不含 v1.3.0；输入示例改 `v2.0.0`；已依据 tag 附注补写 `# v1.2.0` 小节 |
| 发布状态 | 已完成 | `v2.0.0` Release 发布 7 个资产、notes 51 行；CI / CI v2 / Pages 全绿；`origin/main` 仅含 `78d0293 Initial commit`，无独有内容 |
| refspec 歧义 | 部分处理 | 本地 tag `master` 已删除，`refs/heads/master` 不再歧义；远程 `refs/tags/master` 待人工删除，推送可固定写 `refs/heads/master:refs/heads/master` |

**运行测试汇总**：Go 20 项 + `go vet` 全绿；Python 兼容套件对接真实 Go 二进制 19 + 5 全绿；
Rust 内核 18 + Tauri 状态测试 2 全绿；`npm ci` / `npm run build` / `cargo build` 通过；
Windows 与 WSL Linux 二进制启动、`/api/ping`、`--version`、HTTPS 均通过；
并发上传基准 8 MiB / 16 并发首次观测 **0.372 s（21.5 MB/s）**，32/32 回读一致；本轮复核见 `v2/RELEASE_SUMMARY.md` §2.2。

**性能优化（口径校正）**：blob / peers 请求改用不打开 SQLite 的轻量句柄；首次观测由 12.23 s（0.65 MB/s）提升到 0.372 s（21.5 MB/s，约 33 倍），但该倍数**未在同轮受控 A/B 中复现**（同轮基线 1.579 s / 5.07 MB/s vs 优化后 1.732 s / 4.62 MB/s；空闲连跑 3 次 10.5–11.8 MB/s）。基准对负载敏感，不作为量化 SLA；细节见 `v2/RELEASE_SUMMARY.md` §2.2。

### 1.2 工作区相对基线的待提交变更

| 类别 | 规模 | 内容 | 是否应入库 |
| --- | --- | --- | --- |
| 已跟踪文件的本地改动 | 17 个 | `README.md`、`CHANGELOG.md`、`pyproject.toml`、`selfshare/*.py`（10 个）、`desktop/core/src/{client,engine,util}.rs`、`tests/test_{sync,p2p}.py`、`deploy/systemd/selfshare-watch@.service` | 是（按文件类型推断为 v1.3.0 配对流程与核心实现，须以 `git diff` 复核） |
| 待复核 | 6 个 | `.github/workflows/pages.yml`、`deploy/windows/SelfShare-Watch-OnLogon.xml.template`、`desktop/app/assets/app_icon.png`、`desktop/core/tests/integration.rs`、`docs/architecture.md`、`docs/conflicts.md`（Git 包内为 delta 对象，静态比对未能判定） | 提交前用 `git status` / `git diff` 复核 |
| 新增未跟踪源码 | 约 66 个 + 1 个 | `v2/` 的 Go 服务端、Tauri 客户端、Svelte 前端、文档与部署脚本；`tests/external_server.py`（跨实现测试夹具，可让 Python 测试对接 Go 服务端） | 是 |
| 本地构建产物 | 8060 个 / 约 8.29 GB | `v2/client/src-tauri/target/`（6884 个文件）、`v2/server/bin/*.exe`、`v2/superseded/server/selfshare-server.exe`、`v2/client/src-tauri/gen/schemas/*.json` | **否** |
| 已被正确忽略 | — | `desktop/core/target/`、`desktop/app/build/`、`dist/`、`build/`、`__pycache__/`、`*.pyc`、`*.pem` / `*.key` | 否 |

补充事实：Git 索引共 99 个已跟踪文件，`v2/` **完全未纳入版本控制**；`v2/` 目录共 8127 个文件、8.29 GB，其中仅 66 个是源码 / 资源。`origin/main` @ `78d0293` 与 `origin/master` @ `42d6764` 并存且指向不同提交。

### 1.3 提交拆分建议（详见 §5.2）

按原子性拆 3 个提交：`feat(v1)`（已跟踪改动）→ `feat(v2)`（新增源码）→ `docs(status)`（本文件）。**不要使用 `git add -A`**。

---

## 2. 关键进展（已完成）

### 2.1 v1：已发布 `v1.3.0`（2026-11-03）

| 模块 | 已完成 | 主要证据 |
| --- | --- | --- |
| 服务端 / CLI | 内容寻址存储、三方合并双向同步、冲突保留双方、删除语义、全量版本历史、令牌加盐哈希与路径校验 | `selfshare/`、`CHANGELOG.md` |
| 配对流程 | `server` 零配置起步 + 一次性、30 分钟有效的配对码；`POST /api/pair`、`ss_pair` / `ss_probe`、`selfshare pairing` | `README.md`、`CHANGELOG.md`、`selfshare/pairing.py` |
| P2P | 中心认证 + 节点直传、HMAC 双向认证、peer 不可达自动回退中心、TTL / 心跳 | `selfshare/{p2p,peer}.py`、`desktop/core/src/peer.rs` |
| Rust 内核 | 与 Python 协议兼容的 C ABI（实际 19 个 `#[no_mangle]` 导出）、独立 CLI、原子 JSON 状态 | `desktop/core/`、`docs/gui.md` |
| Flutter GUI | 多挂载、进度、托盘、历史恢复、开机自启、isolate 同步 | `desktop/app/`、`deploy/windows/` |
| 工程化 | CI（Python / Rust / Flutter 三个 job）、Release 打包、GitHub Pages 文档站、systemd 与 Windows 计划任务模板 | `.github/workflows/`、`deploy/`、`docs/` |
| 测试 | Python 29 个测试方法（sync 19 / p2p 5 / pairing 5）、Rust 内核 18 个 `#[test]` | `tests/`、`desktop/core/` |

### 2.2 v2：本地收敛版完成，**尚未入库、未经流水线复验**

| 模块 | 已完成 | 主要证据 |
| --- | --- | --- |
| Go 服务端 | 标准库 `net/http` + `modernc.org/sqlite`，模块 `selfshare/server`（Go 1.24）；manifest / commit / history / stat / blob（含 Range）/ blobbulk / pair / peers 路由齐备；TLS（`--cert` / `--key`）；12 项兼容性测试 | `v2/server/`、`v2/README.md:153-161` |
| Tauri 客户端 | 13 个 IPC 命令、系统托盘、5 个 Svelte 页面；通过 `path = "../../../desktop/core"` 复用 `selfshare-core`，不重复实现同步引擎 | `v2/client/src-tauri/`、`v2/client/src/` |
| 兼容性 | 与 Python 服务端 HTTP API 及磁盘数据布局一致；`ServiceVersion` 保持 `1.0` 兼容老客户端；本地端到端手测双向同步 + 冲突保留双方 | `v2/README.md:125-180`、`v2/server/internal/api/api.go:30-31` |
| 部署草案 | Dockerfile / compose / systemd / Makefile / 构建脚本 / v2 CI 草案 | `v2/server/deploy/`、`v2/scripts/build.sh`、`v2/.github/workflows/ci.yml` |

**口径说明**：上述「12 项 Go 测试 / 18 项内核测试 / 端到端手测」均来自 `v2/README.md` 的本地自述；Docker 镜像、性能目标（10x 吞吐、p99 < 100 ms 等）、Tauri 安装包均未由仓库 CI 验证，不能视为发布就绪。

---

## 3. 待解决问题（风险与阻塞点）

| 编号 | 等级 | 问题 | 证据 | 影响 |
| --- | --- | --- | --- | --- |
| R1 | P0 | `v2/client/src-tauri/target/`（6884 个文件、约 8 GB）、`v2/server/bin/*.exe`、`v2/superseded/server/*.exe` 未被忽略 | 根 `.gitignore` 仅忽略 `desktop/core/target/`、通用 `build/` `dist/` | `git add -A` 会污染仓库并可能触发体积限制 |
| R2 | P0 | v2 的 CI 位于 `v2/.github/workflows/ci.yml`，GitHub Actions 只识别仓库根 `.github/workflows/` | `.github/workflows/ci.yml` 无 Go / Tauri job；`release.yml` 只发 v1 资产 | v2 的 `go test -race`、Tauri 构建、Docker 冒烟从未在流水线执行 |
| R3 | P0 | Tauri 前端存在构建阻塞疑点：`index.html` 引用不存在的 `/src/styles.css`；`dist/index.html` 仅为 `Loading...` 占位且被忽略；`tauri.conf.json` 引用不存在的 `icons/icon.icns` | `v2/client/index.html:7`、`v2/client/dist/index.html:1`、`v2/client/src-tauri/tauri.conf.json:43` | `npm run build` / `npm run tauri build` 可能直接失败或产出空壳安装包 |
| R4 | P0 | 本机无 `git` 可执行文件（`where.exe git` 与常见安装路径均无结果）；仓库 reflog 只有一条 `clone` 记录 | 环境探测、`.git/logs/HEAD` | 无法在本地执行 `status` / `diff` / `commit` / `push`，提交需换环境或由 IDE 内置 Git 完成 |
| R5 | P1 | v2 客户端能力回退：`watcher::spawn(..., false, ...)` 明确关闭 P2P；`selfshare-core/tls` 未启用，而 Go 服务端支持 HTTPS | `v2/client/src-tauri/src/sync/engine.rs:220-221`、`desktop/core/Cargo.toml:21-27` | 连不上 HTTPS 服务端；v2 无 P2P 数据面，与 README 宣传的 `--p2p` 不一致 |
| R6 | P1 | v2 无发布管线、版本口径不统一 | `release.yml` 只发 v1；客户端 `2.0.0` vs 服务端 `ServiceVersion "1.0"`；CHANGELOG 无 v2 章节；缺 `v1.2.0` 章节（release notes 提取会回退到整份文件） | 无法交付 v2 资产，用户无法判断版本关系 |
| R7 | P1 | `v2/superseded/server/` 保留有致命缺陷的旧实现（首次启动空指针崩溃、peers 全为 stub、bulk 判定错误），且自带 Makefile / Dockerfile / exe；两 Go 模块并存但无 `go.work` | `v2/superseded/server/internal/api/server.go:39-41,445-456`、`v2/ARCHITECTURE.md:4` | 误执行 / 误构建；从 `v2/` 跑 `go test ./...` 会漏模块或报错 |
| R8 | P1 | 文档漂移：文档站与 wiki 仍以 `vault create` + `mount --token` 为主流程，与 v1.3.0 的 `server` + `pair` 冲突 | `docs/index.md:35-47`、`docs/install.md:37`、`.github/wiki/快速开始.md:11-15` | 新用户按文档操作会走已非主推的四步流程 |
| R9 | P1 | 文档数字口径不一致；v2 架构文档正文含收敛前设计草图 | `README.md:96` 与 `CHANGELOG.md:58-61` 的测试数口径 vs 实际 29 / 18；`docs/gui.md:7` 称 17 个 C ABI，实际 19 个 `#[no_mangle]`；`v2/ARCHITECTURE.md:63,198,210,232` 仍写 `chi`、`SELFSHARE_*`、`--data-dir` 及不存在的目录 | 评审与排障依据不可信 |
| R10 | P1 | v2 验证缺口：Docker 未构建、性能目标未测、CI 未复验、`pairing` / `peers` / `registry` 无独立单测、blob Range 仅支持单段 | `v2/README.md:157-161`、`v2/server/internal/api/handlers.go:159` | 发布前缺少可复现的质量证据 |
| R11 | P2 | v2 客户端功能缺口：设置页仅写 `localStorage`、设备页无列表、托盘「暂停 / 恢复」只打日志、4 个 IPC 命令前端未接线 | `v2/client/src/pages/Settings.svelte:8-27`、`v2/client/src-tauri/src/tray.rs:38-43` | GUI 可见但不可用的开关，易被误认为已实现 |
| R12 | P2 | 构建可复现性与流程细节：缺 `package-lock.json`（`package.json` 全为 `^` 浮动版本，Rust 侧已有 `Cargo.lock`）；CI 中 `\|\| true` / `set +e` 掩盖失败；`master` 与 `main` 指向不同提交、主分支口径不清；`release.yml` 输入示例仍为 `v1.2.0` | `.github/workflows/ci.yml:54,85,109`、`pages.yml:39`、`.git/packed-refs` | 构建结果随时间漂移、失败被吞、分支与发布来源不清 |
| R13 | P2 | 已知产品边界（非缺陷，需持续披露）：公网 NAT 穿透 / 中继、分块增量传输未实现；单文件 2 GiB 上限；不保留 Windows ACL / 符号链接 / 空目录；P2P 仅限局域网 | `README.md:87-92`、`CHANGELOG.md:131-137`、`.github/wiki/常见问题.md:91,105` | 影响适用范围与用户预期 |

---

## 4. 后续计划（下一步优先级建议）

### P0 — 提交 / 合并前必须完成（阻塞项）

1. **清理待提交范围（R1、R4）**：在 `.gitignore` 增加 `v2/client/src-tauri/target/`、`v2/server/bin/`、`v2/**/gen/schemas/`（或明确决定入库）、`*.exe` / `*.pdb` / `*.lib` / `*.rlib` / `*.o` 等规则；验收：`git status --short` 中无 `target/`、无二进制文件、无密钥文件，待提交对象总量在 MB 级。
2. **让 v2 的 CI 真正生效（R2）**：把 `v2/.github/workflows/ci.yml` 的 4 个 job 合并进根 `.github/workflows/ci.yml`（或新增根 `ci-v2.yml`），保留 `go test -race` / `go vet`、5 平台构建、Tauri 构建、Docker 冒烟；验收：PR 上可见 v2 检查项且全绿。
3. **打通 Tauri 前端构建（R3）**：补齐或移除 `/src/styles.css` 引用、由 `npm run build` 生成真实 `dist/`、补齐 `icon.icns` 或按平台裁剪 bundle 图标；验收：干净的 `npm install && npm run tauri build` 产出可启动的安装包。
4. **确认提交环境（R4）**：在装有 Git 的环境（或 IDE 内置 Git）执行 `git status` / `git diff --stat` 复核 17 + 6 个改动文件，再按 §5.2 提交；验收：提交信息与 diff 一致、无产物与令牌入库。

### P1 — v2 首个可用版本前

5. **能力对齐（R5）**：启用 `selfshare-core/tls` 或明确「v2 仅 HTTP」；决定是否恢复 P2P 数据面，并把结论同步到 README / docs；验收：HTTPS 端到端用例通过，文档与实现一致。
6. **发布与版本（R6）**：扩展 `release.yml` 产出 Go 多平台二进制与 Tauri Windows 安装包；统一 `2.0.0` / `ServiceVersion` 口径；CHANGELOG 补 `[Unreleased]` 与缺失的 `v1.2.0` 章节；验收：打 `v2.0.0` 标签能自动发布对应资产与 notes。
7. **收敛旧实现与模块（R7）**：删除 `v2/superseded/` 或移至仓库外归档；若保留，去掉其 Makefile / Dockerfile / exe 并加 `README` 警示；必要时补 `go.work` 或写明唯一构建入口；验收：仓库根执行构建脚本不会误触旧模块。
8. **文档一致性（R8、R9）**：把 `docs/`、`desktop/README.md`、`.github/wiki/` 的快速开始改为 `server` + `pair`；统一测试数 / C ABI 数口径；按 `v2/README.md` 重写 `v2/ARCHITECTURE.md` 早期章节；验收：全文检索无 `chi` / `SELFSHARE_*` / `--data-dir`，Pages 构建通过。
9. **补齐验证证据（R10）**：在 CI 中构建 Docker 镜像并跑 `/api/ping` 冒烟；为 `pairing` / `peers` / `registry` 补单测；记录性能基线；验收：v2 README 的「验证状态」每条都能指向一次流水线运行记录。

### P2 — 后续迭代

10. **补齐 GUI 功能（R11）**：设置持久化走 IPC、设备列表、托盘暂停 / 恢复接引擎、清理未使用的 IPC 命令。
11. **工程化收尾（R12）**：生成并提交 `package-lock.json`、去掉会吞掉失败的 `|| true` / `set +e`、明确 `master` 为唯一主分支并同步或归档 `main`、更新 `release.yml` 输入示例。
12. **产品能力（R13）**：按需求排期公网 NAT 穿透 / 中继、分块增量传输；在此之前保持限制说明可见。

---

## 5. 提交规范与可追溯性

### 5.1 格式要求

遵循 `CONTRIBUTING.md` 的 `type(scope): summary`：subject 用英文、祈使语气、不超过 72 字符；body 必含 **基线 / 范围 / 验证 / 未验证 / 关联编号 / 追溯引用**，并声明测试来源。禁止在提交信息或正文中粘贴令牌。

### 5.2 建议的三个原子提交

```text
feat(v1): land v1.3.0 pairing flow and core updates

Baseline: master 42d6764 (v1.3.0 tag 714e9ee)
Scope: 17 tracked files (README/CHANGELOG/pyproject, selfshare/*,
       desktop/core/src/*, tests/*, deploy/systemd/*), plus
       tests/external_server.py.
Verify: python tests/test_sync.py / test_p2p.py / test_pairing.py (29 OK);
        cargo test (desktop/core, 18 OK).
Note: adjust subject after reviewing `git diff` (R4).
Refs: PROJECT_STATUS.md §1.2, §2.1
```

```text
feat(v2/server): Go server, unit tests and blob fast path

Baseline: master 42d6764
Scope: v2/server (net/http + modernc sqlite), 20 Go tests, --version,
       Dockerfile HEALTHCHECK, Makefile, systemd unit,
       v2/scripts/bench_upload.py.
Verify: go test ./... (20 OK); go vet ./... (0 issue);
        Python compat suite against Go binary (19 + 5 OK);
        WSL linux/amd64 binary /api/ping OK; HTTPS self-signed OK.
Perf: 32x256KiB / 16 workers: first observation 12.23s -> 0.372s;
      controlled A/B did not reproduce the 33x claim (v2/RELEASE_SUMMARY.md §2.2).
Unverified locally: go test -race (no gcc/cgo), Docker image (no engine);
                    both covered by .github/workflows/ci-v2.yml.
Refs: PROJECT_STATUS.md §1.1.1, §2.2, R10
```

```text
feat(v2/client): Tauri tray control, settings, peers and TLS

Baseline: master 42d6764
Scope: v2/client Rust + Svelte sources, package-lock.json, Cargo.toml
       (selfshare-core/tls), tests/engine_state.rs.
Verify: npm ci; npm run build (42 modules); cargo build;
        cargo test --test engine_state (2 OK); 19 IPC commands wired.
Refs: PROJECT_STATUS.md §1.1.1, R3/R5/R11
```

```text
chore(ci,docs): enable v2 CI/release assets and refresh docs

Baseline: master 42d6764
Scope: .gitignore, .github/workflows/ci-v2.yml, release.yml,
       README/CHANGELOG/CONTRIBUTING/docs/wiki, v2/README.md,
       v2/ARCHITECTURE.md, PROJECT_STATUS.md.
Verify: static workflow review + local test runs listed above.
Unverified: GitHub Actions / Release pipeline (requires push);
            this environment has no git CLI, no commit/push performed.
Refs: PROJECT_STATUS.md §1-§5
```

### 5.3 提交前检查清单

- [ ] `git status --short` 复核改动清单，确认无 `target/` / `bin/` / `*.exe` / `*.key`
- [ ] `git diff --stat` 与提交信息描述一致；`git diff --check` 无空白错误
- [ ] 已按 P0-1 补齐 `.gitignore`，且未使用 `git add -A`
- [ ] P0-2 的 v2 CI 已迁入仓库根并跑通
- [ ] 提交信息含基线 commit / 标签、验证与未验证项、`R*` / `P*` 编号
- [ ] 未粘贴令牌、密钥、配对码或本机绝对路径

### 5.4 安全的暂存方式（显式路径，勿用 `-A`）

```bash
git add PROJECT_STATUS.md
git add README.md CHANGELOG.md pyproject.toml selfshare/ tests/ \
        desktop/core/src/ deploy/systemd/selfshare-watch@.service
git add v2/README.md v2/ARCHITECTURE.md v2/scripts/ \
        v2/server/cmd/ v2/server/internal/ v2/server/deploy/ \
        v2/server/go.mod v2/server/go.sum v2/server/Makefile \
        v2/server/Dockerfile v2/server/docker-compose.yml
git add v2/client/index.html v2/client/package.json v2/client/svelte.config.js \
        v2/client/tsconfig.json v2/client/vite.config.ts v2/client/src/ \
        v2/client/src-tauri/Cargo.toml v2/client/src-tauri/Cargo.lock \
        v2/client/src-tauri/build.rs v2/client/src-tauri/tauri.conf.json \
        v2/client/src-tauri/src/ v2/client/src-tauri/icons/ \
        v2/client/src-tauri/capabilities/
```

说明：R1 已修复，`**/target/`、`node_modules/`、`bin/`、二进制扩展名等均被忽略；仍建议显式路径，
因为 `v2/superseded/`（R7 待决策）与生成物目录不宜随本次提交入库。新增文件还需加入：
`.github/workflows/ci-v2.yml`、`v2/client/package-lock.json`、`v2/client/src/styles.css`、
`v2/client/src-tauri/tests/engine_state.rs`、`v2/server/internal/store/*_test.go`、
`v2/scripts/bench_upload.py`。`v2/.github/workflows/ci.yml` 已删除（迁移到根）。

### 5.5 追溯索引

| 项 | 值 |
| --- | --- |
| 基线提交 | `42d67645af534c5eec3c43668311604616381745`（`master` / `origin/master`） |
| 发布标签 | `v1.1.0` / `v1.2.0` / `v1.3.0`（`714e9ee91cfe0e69ad9fb25e4c3fdc9a37f36d85`） |
| 另一远程分支 | `origin/main` @ `78d0293a9e03cdb90bf9fa430c8752a7014a45cd` |
| 分析日期 | 2026-11-04（含当日第二轮开发与运行测试） |
| 分析范围 | 根目录 v1（99 个已跟踪文件）、`v2/`（8127 个文件）、`.github/workflows/`、`docs/`、`.github/wiki/`、`deploy/` |
| 运行验证 | Go 20 + vet、Python 29（其中 24 对接 Go 二进制）、Rust 18 + 2、前端构建、Tauri 编译、Windows/WSL 二进制、HTTPS、并发基准首次观测 21.5 MB/s（同轮 A/B 未复现 33 倍）；详见 `v2/RELEASE_SUMMARY.md` §2.2 |
| 未执行操作 | `git add` / `git commit` / `git push`（本机无 `git`）；GitHub Actions / Release 需推送后验证 |
