# 项目状态与后续路线｜2026-11-22（单一事实源）

> **本文 §0 是当前状态与后续路线的唯一权威入口**；§1 起为 2026-11-04 基线（`42d6764`）的历史盘点快照，R1–R12 已全部闭环，**不再作为当前口径维护**。
> 仓库：`wakawakalululu/SelfShare`；基线：`master` == `origin/master`（2026-11-22 刷新，见 §0.2）
> 发布：稳定版 **`v2.1.0`**（8 资产，latest，P2P 可观测性随版，**semver 口径生效：功能进 minor**）；`v2.0.4`（R5 P2P 数据面）、`v2.0.3`（O-2/O-3 UI）、`v2.0.2`（D7）、`v2.0.1` 补丁版存档；演练 `v1.1.0` 已转 prerelease（保留不删除，`release-hygiene.yml` 幂等固定 latest 口径）
> 验证基线：L1 33 / L4 28 / DLL 冒烟 9 / Rust 25+1（D7 契约） / Go 24 / ABI 四方 19；ci.yml、ci-v2.yml、build-test-deploy、release.yml、release-hygiene.yml、cut-release.yml 六条流水线全绿实证
> 维护约定：阶段性交付后只更新本文 §0 与 `CHANGELOG.md [Unreleased]`；`AGENTS.md` 只留规范与门禁、不放演进史；过程性记录归 `.codebuddy/skills/软件开发专家团/memory/`（不入库）

---

## 0. 当前状态与后续路线（唯一入口）

### 0.1 权威文档地图（避免同一事实多处维护）

| 想查什么 | 唯一去哪 |
| --- | --- |
| 当前状态、后续路线 | **本文 §0** |
| 编码 / 提交 / 门禁红线 | `AGENTS.md` |
| 契约 C1–C6 | `docs/contracts/`：`abi-ipc.md`(C5)、`storage-layout.md`(C3)、`merge-semantics.md`(C4)、`security-contract.md`(C6)、`requirement-card.md`(需求卡) |
| 决策与未决项 | `docs/decisions/OPEN-DECISIONS.md`（O-1~O-7）、`ADR-001`、`ADR-002` |
| 本地 / CI 验证命令 | `CONTRIBUTING.md`（当前命令）、`AGENTS.md` §6（分层门禁） |
| v2.0.0 发布当时的验证数据 | `v2/RELEASE_SUMMARY.md`（**历史快照**） |
| 过程日志 / 交接卡 | `.codebuddy/skills/软件开发专家团/memory/`（不入库） |

### 0.2 当前状态（收敛后）

| 维度 | 事实 |
| --- | --- |
| 代码 | 2026-11-23 刷新：**P2P 可观测性已落地**（只读 `p2p_status` IPC + 设备页本机节点状态，随 `v2.1.0` 发布，`LOOP-20261123-02`）；此前 2026-11-22：C4-1（`1c4a5fd`）已随 `v2.0.1` 发布；**D7 / P1 假成功已修复**（`LOOP-20261122-01`）；**P2 断言加固已闭环**（`LOOP-20261122-03`）；**O-2/O-3 轻量 UI 已落地**（随 `v2.0.3` 发布）；**Flutter 桥接冒烟 8 例入 gui 门禁**（`LOOP-20261122-05`）；**R5 P2P 数据面已接通**（手动同步按 `enable_p2p` 开关走 peer 优先 + 中心回退，随 `v2.0.4` 发布，`LOOP-20261122-06`） |
| 契约 | C3 rel 键规范化、C4 合并语义、C5 ABI/IPC 形状（冻结）、C6 路径 containment 均已落盘；O-1~O-3 已裁决（O-2/O-3 的 UI 增量已实现），O-5/O-6 维持冻结 |
| 发布 | **`v2.1.0` 8 资产稳定版（latest）**；`v2.0.4`（R5 P2P 数据面）、`v2.0.3`（O-2/O-3）、`v2.0.2`（D7）、`v2.0.1`（C4-1）与 `v2.0.0` 存档；`release-hygiene.yml` 幂等固定 latest=最新补丁版；演练 `v1.1.0` 已转 prerelease |
| 验证 | 上述历史基线继续有效；新增：Python 50 例对 release 二进制回归（v2.0.0 49/50 → v2.0.1 起 50/50）、ci-v2 9/9（含 Tauri Windows 构建）、release 8 资产端到端、hygiene 断言、WSL 服务端 + Windows GUI 本机联调（截图证据）；O-2/O-3 接线静态扫描门禁 + 5 例自测、Flutter 桥接冒烟 8 例入 ci.yml |
| 遗留 | §0.3 路线图 P1/P2/P3 全部闭环（2026-11-22）；仅余环境受限余量（darwin / linux-arm64 实机与真一次性 VM 安装，须硬件）。无 P0/P1/P2 未闭环项；新增工作按「一次迭代一个目标」在 §0.3 增行 |

### 0.3 后续路线（按优先级，一次迭代一个目标）

| 优先级 | 项 | 内容 | 验收命令 |
| --- | --- | --- | --- |
| ~~P1~~ | ~~D7~~ ✅ 已闭环（`LOOP-20261122-01`） | Dashboard 读取 sync IPC 返回状态，失败显示明细；`engine_state` 新增契约钉死测试 | `cargo test --test engine_state`、`npm run build`（ci-v2 v2-client 全绿） |
| ~~P1~~ | ~~存量库只读扫描~~ ✅ 已闭环（`LOOP-20261122-02`） | `desktop/scripts/scan_vault_db.py`（mode=ro / `--immutable`，whitespace / drive_letter / null 判类，`--json` 结论）；本地部署库实测 1 files + 1 versions 行 clean；结论记录见 CHANGELOG | `python tests/test_scan_vault_db.py`（ci.yml self-tests 步骤） |
| ~~P2~~ | ~~O-2 / O-3 轻量 UI~~ ✅ 已闭环（`LOOP-20261122-04`，随 `v2.0.3` 发布） | 设置页首次进入一次性提示（localStorage 一次性标记，O-2 裁决口径）；新增 `list_large_files` IPC（只读遍历本地目录，>512 MiB 阈值），仪表盘按挂载提示大文件与耗时估算（~10 MB/s 基准，标注估算）；接线静态扫描门禁（11 标记）+ 5 例自测入 ci.yml | `npm run build` + 静态扫描（ci.yml v2-client 步骤 + python self-tests） |
| ~~P2~~ | ~~`flutter test` 冒烟~~ ✅ 已闭环（`LOOP-20261122-05`） | `desktop/app/test/rust_bridge_smoke_test.dart` 8 例桥接冒烟（宿主机 VM 直跑 dart:ffi，加载 gui job 前置构建的真实 DLL：裸 JSON 三函数 / ok_json 幂等 / C5-3 白名单 / 错误通道 / 不可达 probe）；`ci.yml` gui job 增补 `flutter test` 步骤；不为 `ss_find_mount` 硬接业务调用点 | `flutter test`（CI gui job「Bridge layer smoke tests」步骤） |
| ~~R5~~ | ~~P2P 数据面（Tauri）~~ ✅ 已闭环（`LOOP-20261122-06`，随 `v2.0.4` 发布） | 手动同步 `sync_once` 按 `enable_p2p` 开关（默认关闭，O-2 口径）走 peer 优先拉取 + 中心静默回退（C6 §3 HMAC 不变）；后台监控路径的 P2P（R11）不变；新增 `engine_state` 契约测试钉死「开关开启不改 IPC 失败形状」；数据面路由由内核层 `test_p2p.py` + Rust 集成覆盖 | `cargo test --test engine_state`、`cargo check --all-targets`（ci/ci-v2 双绿） |
| ~~P2~~ | ~~断言加固~~ ✅ 已闭环（`LOOP-20261122-03`） | `integration.rs` 的 `ss_progress` 子串断言改 `serde_json` 反序列化进 `ProgressSnapshot`（形状改动显式失败，不再静默假通过）；`ProgressSnapshot` 补 `Deserialize`（纯增量，C ABI JSON 不变） | `cargo test --release --test integration`（ci.yml rust job 双平台全绿） |
| ~~P2~~ | ~~隔离环境冒烟~~ ✅ 可达子项已闭环（`LOOP-20261122-07`） | NSIS 真实安装 + GUI 窗口（v2.0.3 / v2.0.4 两轮静默安装，截图证据）；并发基准（v2.0.4 release 二进制：8 MiB / 16 并发 0.096 s = **83.49 MB/s**，32/32 上传 + 32/32 回读一致，`bench_upload.py`）；非 Windows 产物实机（linux-amd64 64 例回归 + Windows 原生 `--version`=2.0.4）。**环境受限余量**：darwin / linux-arm64 实机（无 macOS、无 qemu）、真一次性 VM 安装（当前为既有 Windows 宿主）——须硬件，非代码缺口 | `python v2/scripts/bench_upload.py --server <release 二进制>`、Windows 原生执行 |
| ~~P3~~ | ~~工程债~~ ✅ 已闭环（`LOOP-20261122-07`） | ① `abi-ipc.md` 行号近似引用全部改符号/小节锚点（ffi.rs::ok_json 等；h 文件清单锚点保留，由 `check_abi_names.py` 机械锁定），并修正已过时的「integration.rs 子串断言」描述（现为反序列化断言）；② CI 重复收敛：`build-test-deploy.yml` 移除与 ci-v2 `server-test` / `compat`、ci.yml `python` 重复的 test-server / test-python 两 job，收敛为「构建 + 发布 + 部署」链路（Docker 冒烟保留为发布前置门）；③ CHANGELOG 历史锚点统一（v1.x 段 `# v1.3.0 发布说明` → `# [v1.3.0]` 等，8 个版本锚点 awk 提取全部非空） | 全文检索（行号引用清零、job 引用无残留）+ CI 时长对比（btd 收敛前后） |
| ~~提案P2~~ | ~~P2P 可观测性（R11 余量）~~ ✅ 已闭环（`LOOP-20261123-02`，随 `v2.1.0` 发布） | 只读 `p2p_status` IPC（`enabled/watching/node/peers` 快照，中心不可达以空列表容错）；内核 `WatchHandle::peer_node()` 暴露本机节点（peer_id + 监听地址）；设备页新增本机节点状态行；`engine_state` 新契约测试钉死「关闭时不虚报节点」 | `cargo test --test engine_state`、`cargo check --all-targets`（ci/ci-v2 双绿） |

> 说明：O-5（C ABI 形状 v2 统一）与 O-6（盘符语义统一）**不列入实施路线**——均属不可兼容 v2 变更，按红线维持冻结；若立项须先明确大版本、存量库扫描、三端同步与 L3/L4 实证。

### 0.3.1 下一阶段提案（2026-11-23 起草，**待用户裁决**——裁决前不动工）

> 背景与依据：§0.3 既有项已全部闭环（LOOP-20261122-01～07）；本节基于 §0.2 遗留（环境受限余量）、OPEN-DECISIONS 未决项（O-1/O-6 待真实部署数据、O-4 分析复核维持现状）与本轮实测（material_ui 迁移、P2P 数据面接线、发版流程双跑发现、semver 口径瑕疵）起草。**以下各行均为提案，未立项**；裁决后按「一次迭代一个目标」逐行上移至 §0.3 正式表。

| 提案优先级 | 项 | 内容与动机 | 验收命令 / 证据 |
| --- | --- | --- | --- |
| ~~提案 P2~~ | ~~v2 客户端 P2P 可观测性~~ ✅ **已裁决立项并上移 §0.3 正式表**（2026-11-23，随 `v2.1.0` 发布） | 后台监控已按 `enable_p2p` 起本机节点并注册（watcher），但节点状态 / 监听地址 / 已注册 peer 只在 watcher 内部消息里，前端不可查。新增 `p2p_status` IPC（只读），设备页展示本机节点与在线 peer；手动同步不自起节点的行为保持 | `npm run build` + `cargo check --all-targets` + `engine_state` 新契约测试 |
| 提案 P2 | 文档站 / wiki 口径刷新 | `docs/`（Jekyll）与 `.github/wiki/` 仍含 pre-v2.0.x 口径（latest 版本号、P2P 说明、自托管部署）；全文检索 + 逐页刷新到 v2.0.4 事实（latest、enable_p2p 语义、NSIS 安装） | 全文检索（旧口径清零）+ pages.yml 绿 |
| 提案 P3 | `bench_ab` 常态化 | 现 A/B 基准仅手动运行；新增 `workflow_dispatch`（不进 push 门禁，AGENTS §5.7 不作 SLA）周期采集吞吐数据落 artifact，为性能回归提供纵向样本 | workflow_dispatch 实跑 + artifact 非空 |
| 提案 P3 | 真实部署环境 `scan_vault_db` 采集指引 | O-1/O-6 立项仍缺真实部署数据；产出 runbook（`--json` 汇总格式、--immutable 用法、脱敏要求）+ 可选 `workflow_dispatch` 采集模板；数据到位后再裁决 O-1/O-6 | runbook 评审 + 采集样例 |
| 提案 P3 | 发版流程余量收敛 | 本轮发现：PAT 切 tag 会自动触发 release.yml（v2.0.4 跑了 #17/#18 两次，幂等无害但浪费）。收敛为「切 tag 即自动发版」或「GITHUB_TOKEN 切 tag + 手动 dispatch」二选一，并更新 cut-release.yml 说明 | 发版演练一次（run 编号 + 资产计数） |
| 提案 口径 | semver 约定立此存照 | v2.0.4 把 P2P 数据面功能放在补丁位，属 semver 口径瑕疵。约定：**功能类进 minor（下一功能版 = v2.1.0），补丁位只收修复**；已在库的 v2.0.4 不追改（不发修订版） | 无（口径条目）；下次发版按此执行 |

> 环境受限余量（darwin / linux-arm64 实机、真一次性 VM 安装）不设提案行——须硬件到位，属条件触发项。

---

## 1. 变更摘要（2026-11-04 历史快照，不作当前口径）

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

### 2.2 v2：本地收敛版完成（2026-11-04 历史快照，现已闭环；当时尚未入库、未经流水线复验）

| 模块 | 已完成 | 主要证据 |
| --- | --- | --- |
| Go 服务端 | 标准库 `net/http` + `modernc.org/sqlite`，模块 `selfshare/server`（Go 1.24）；manifest / commit / history / stat / blob（含 Range）/ blobbulk / pair / peers 路由齐备；TLS（`--cert` / `--key`）；12 项兼容性测试 | `v2/server/`、`v2/README.md:153-161` |
| Tauri 客户端 | 13 个 IPC 命令、系统托盘、5 个 Svelte 页面；通过 `path = "../../../desktop/core"` 复用 `selfshare-core`，不重复实现同步引擎 | `v2/client/src-tauri/`、`v2/client/src/` |
| 兼容性 | 与 Python 服务端 HTTP API 及磁盘数据布局一致；`ServiceVersion` 保持 `1.0` 兼容老客户端；本地端到端手测双向同步 + 冲突保留双方 | `v2/README.md:125-180`、`v2/server/internal/api/api.go:30-31` |
| 部署草案 | Dockerfile / compose / systemd / Makefile / 构建脚本 / v2 CI 草案 | `v2/server/deploy/`、`v2/scripts/build.sh`、`v2/.github/workflows/ci.yml` |

**口径说明**：上述「12 项 Go 测试 / 18 项内核测试 / 端到端手测」均来自 `v2/README.md` 的本地自述；Docker 镜像、性能目标（10x 吞吐、p99 < 100 ms 等）、Tauri 安装包当时均未由仓库 CI 验证、不能视为发布就绪（2026-11-04 历史快照，现已闭环）。

---

## 3. 待解决问题（风险与阻塞点）

| 编号 | 等级 | 问题 | 证据 | 影响 |
| --- | --- | --- | --- | --- |
| R1 | P0 | `v2/client/src-tauri/target/`（6884 个文件、约 8 GB）、`v2/server/bin/*.exe`、`v2/superseded/server/*.exe` 未被忽略 | 根 `.gitignore` 仅忽略 `desktop/core/target/`、通用 `build/` `dist/` | `git add -A` 会污染仓库并可能触发体积限制 |
| R2 | P0 | v2 的 CI 位于 `v2/.github/workflows/ci.yml`，GitHub Actions 只识别仓库根 `.github/workflows/` | `.github/workflows/ci.yml` 无 Go / Tauri job；`release.yml` 只发 v1 资产 | v2 的 `go test -race`、Tauri 构建、Docker 冒烟在 2026-11-04 前从未在流水线执行（现已闭环） |
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
Unverified (2026-11-04 snapshot, since closed by CI): GitHub Actions / Release pipeline (requires push);
            this environment had no git CLI, no commit/push performed at that time.
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
因为 `v2/superseded/` 已删除（R7 闭环）且生成物不应入库。新增文件还需加入：
`.github/workflows/ci-v2.yml`、`v2/client/package-lock.json`、`v2/client/src/styles.css`、
`v2/client/src-tauri/tests/engine_state.rs`、`v2/server/internal/store/*_test.go`、
`v2/scripts/bench_upload.py`、`v2/scripts/bench_ab.py`。`v2/.github/workflows/ci.yml` 已删除（迁移到根）。

### 5.5 追溯索引

| 项 | 值 |
| --- | --- |
| 基线提交 | `42d67645af534c5eec3c43668311604616381745`（`master` / `origin/master`） |
| 发布标签 | `v1.1.0` / `v1.2.0` / `v1.3.0`（`714e9ee91cfe0e69ad9fb25e4c3fdc9a37f36d85`）/ `v2.0.0`（`1c8559c`，附注 tag，Release 7 资产） |
| 另一远程分支 | `origin/main` @ `78d0293a9e03cdb90bf9fa430c8752a7014a45cd`（仅含 Initial commit，待人工归档） |
| 分析日期 | 2026-11-04（含当日第二轮开发与运行测试；2026-11-07 状态见 §1.1.1） |
| 分析范围 | 根目录 v1（99 个已跟踪文件）、`v2/`（8127 个文件）、`.github/workflows/`、`docs/`、`.github/wiki/`、`deploy/` |
| 运行验证 | Go 20 + vet、Python 29（其中 24 对接 Go 二进制）、Rust 18 + 2、前端构建、Tauri 编译、Windows/WSL 二进制、HTTPS、并发基准首次观测 21.5 MB/s（同轮 A/B 未复现 33 倍）；CI / CI v2 / Pages / Release 实跑全绿，详见 `v2/RELEASE_SUMMARY.md` §2.2、§4.1 |
| 已执行操作 | `git add` / `git commit` / `git push` 已完成，`master` 与 `v2.0.0` tag 均已推送，工作区干净 |
| 仍待人工 | 删除远程 `origin/main` 与 `refs/tags/master`；darwin / linux-arm64 二进制实机冒烟 |
