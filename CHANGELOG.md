# [Unreleased]

发布日期：未发布
范围：v1 Python 客户端路径校验加固；CI/发布流水线补齐 v2 产物；v2 门禁收敛。
补充范围：peer 不可达回退独立断言（`tests/test_p2p.py::PeerFallbackTestCase`）；「远程构建 ↔ 本地验证」循环工具；协作规范 / 契约 / 决策文档新增。

## 安全

- 修复 `selfshare.util.abs_path` 缺失根目录约束：`norm_rel` 会保留客户端原始文本，
  Windows 上 `C:/...` 这类盘符路径会让 `os.path.join` 丢弃 vault 根，
  同步清单可读写到 vault 之外。现在与 Rust (`desktop/core/src/util.rs`) 和
  Go (`store.AbsPath`) 一致，落盘前拒绝绝对路径与盘符段（`tests/test_sync.py::SyncTestCase.test_abs_path_cannot_escape_vault`）。
- 影响面：仅 v1 Python 客户端（服务端 `store.py` 走 `norm_rel`，不拼本地路径）。

## 工程

- 根 `ci.yml` 新增 `v2-client`（vite 构建 + `cargo check --all-targets` + `engine_state` 测试）与 `core-dll-smoke`（下载 Rust 产物跑 6 例 DLL 冒烟）；`v2-server` 的 vet / race / Docker 冒烟收敛至 `ci-v2.yml` 权威覆盖，不再三处重复。
- `ci-v2.yml` 触发器补 `tags: ['v*']`：发行标签上必跑 compat 跨实现套件。
- `release.yml`：Release notes 只认 CHANGELOG 一级版本标题（伪 tag 显式失败，不再兑底整份文件）；`contents: write` 收窄至发布 job；`npm ci` 替代 `npm install`；发布资产 glob 互斥（8 个资产）；行尾统一 LF。
- 新增「远程构建 ↔ 本地验证」循环：`desktop/scripts/ci_fetch.py`（Actions 产物 / Release 资产下载 + SHA256 校验，无 `gh` CLI 可用）与 `tests/test_core_dll.py`（Rust 内核 DLL ctypes 冒烟 6 例，`SELFSHARE_CORE_DLL` 门控）；用法见 CONTRIBUTING「远程构建 ↔ 本地验证循环」。
- `Dockerfile` 改为 `--platform=$BUILDPLATFORM` + `TARGETOS/TARGETARCH` 交叉编译，避免多架构构建走 QEMU。
- 新增 `v2/scripts/check.sh` 本地轻量检查；`build-test-deploy.yml` 补齐服务端镜像发布与可选滚动部署。
- `release.yml` 演练（`workflow_dispatch` / `v1.1.0`）真实产出并发布 8 个资产；发布前资产集合与非空校验、便携包内含 `selfshare_core.dll`、Go 二进制 `--version` 均由流水线实证（run `42424638532`）。本地下载 8 资产按 API `digest` 校验，便携包解压即用 + 包内 DLL 6 例冒烟、L1 31 例、L4 26 例通过。演练 Release 按用户决定保留，`get_latest_release` 暂为 `v1.1.0`，稳定版仍为 `v2.0.0`。
- 新增三方名称一致性只读检查 `desktop/scripts/check_abi_names.py`：比对 `selfshare_core.h` 的 19 个 `ss_*` 声明、`rust_bridge.dart` 的 `lookupFunction` 名称与 `tests/test_core_dll.py` 的 `ABI_SYMBOLS`，不一致时打印差异并以非 0 退出；`ci.yml` 在 `core-dll-smoke` job 补步骤于 CI 中执行该脚本（本地可直接运行 `python desktop/scripts/check_abi_names.py`）。`tests/test_core_dll.py` 同步新增 1 例，用 ctypes 调 `ss_find_mount` 传入确定不存在的路径，断言「无匹配」返回 `{"ok":false,"error":"不在任何同步目录内"}`（与 `rust_bridge.dart` 的 `_findMountNoMatchError` 白名单逐字一致），DLL 冒烟由 6 例增至 7 例。
- 本轮（LOOP-20261109-04）：`desktop/scripts/check_abi_names.py` 四方加固（header / dart / abi / `ffi.rs` Rust 导出；注释剥离、跨行声明与泛型解析、纳入 Rust 导出）并新增 `tests/test_check_abi_names.py` 自测（`python tests/test_check_abi_names.py -v`）；`tests/test_core_dll.py` 新增白名单静态一致性与 A 类形状表驱动断言 2 例，DLL 冒烟现为 9 例。

- `selfshare-dev-team` D 轨道契约先行（`LOOP-20261109-05`）：新建 `docs/contracts/storage-layout.md` C3（rel 键规范化，三端 trim 收敛）、更新 `security-contract.md` C6-2（盘符 containment 按宿主 OS 分支冻结）、登记 `OPEN-DECISIONS.md` O-6（v2 变更记录）；Rust `norm_rel` 补 trim 并同步 `state.rs::base_of` 归一，Python / Rust / Go 三端各补 trim 与 OS 分支断言。**D2 盘符语义冻结**，不改 Python / Go 生产代码、`ServiceVersion` 与 C5 形状。

- **D6 / C4-1 修复（`LOOP-20261109-07`）**：新建 `docs/contracts/merge-semantics.md` C4 契约、登记 `OPEN-DECISIONS.md` O-7（已发布行为变更）；Python `store.py` 与 Go `vault.go` 的 `del` 统一为与 `put` 相同的 `base == current` 判据，缺 `base_hash` 且远端有内容时记 `remote_changed` 并跳过，防止畸形/旧客户端静默删除第三方新编辑。正常客户端恒带 base，删除流程不受影响；新增 Python / Go 注入用例（`test_delete_without_base_never_overwrites_new_remote_edit` / `TestCommitDelWithoutBaseRejectsRemoteEdit`），L4 用**新编译** Go 二进制实证。

- 文档口径收敛（`LOOP-20261109-08`）：`PROJECT_STATUS.md` §0 成为「当前状态 + 后续路线」的**唯一权威入口**，§1 起明确标为 2026-11-04 历史快照；`AGENTS.md` §6 移除多轮 run 演进史、改为指向该入口；`v2/RELEASE_SUMMARY.md` 的过时「当前状态（2026-11-08）」行改为历史快照声明。不新增文件、不改代码与契约条款。
- `flutter analyze` 门禁加 `--no-fatal-infos`（`ci.yml` Analyze 步与 `desktop/scripts/build_windows.ps1` 第 2/4 步）：Flutter stable 3.50.0 将 `package:flutter/material.dart` 导入标记为 deprecated info，info 级别不再拦截 CI / 发版（error 与 warning 仍拦截）；LOOP-20261120-02 实证 run `44611255635` 与 `44611482618` 因该环境漂移失败，`ci.yml` 顺带全文件行尾统一为 LF（原 CRLF 曾导致 sed 修改失败）。
- **D7 / P1 假成功修复（`LOOP-20261122-01`）**：Tauri 客户端仪表盘此前丢弃 `sync_mount` / `sync_all_mounts` 的返回状态，同步失败（IPC 正常返回 `state:"error"` + `errors`）也显示「同步完成」。前端改为读取返回状态：单项显示 `同步失败 — <errors 明细>`，全部同步汇总成功/失败计数与明细；不新增 IPC、不改返回形状。新增 `tests/engine_state.rs::sync_once_surfaces_sync_failure_via_status_state_not_err` 钉死 Rust 侧契约（失败走 `Ok(SyncStatus)` 而非 `Err` 并写入 `get_status` 缓存；mount 不存在仍走 `Err`）。
- **P1 存量库只读扫描（`LOOP-20261122-02`）**：新增 `desktop/scripts/scan_vault_db.py`——对 vault.db 的 `files.rel` / `versions.rel` 做只读检测（URI `mode=ro`，`--immutable` 兼容被服务端持有的线上库，全程仅 SELECT），判类 = 首尾空白 + 盘符段（段级去空白后判，trim 暴露的盘符不漏报）+ NULL 防御类；`--json` 输出机器可读结论，退出码 0=clean / 1=异常 / 2=schema 不符。新增 `tests/test_scan_vault_db.py` 9 例（判类正反例、端到端、schema 错误、只读红线：mode=ro 拒写且不留 -wal/-shm）。ci.yml python job 增补 self-tests 步骤。本地部署环境实测：1 files + 1 versions 行 clean（O-6 立项前置条件的结论记录，详见 PROJECT_STATUS §0.3）。

- Release 去旧留新（`LOOP-20261120-01`）：新增 `.github/workflows/release-hygiene.yml`（`workflow_dispatch` + 本文件 push 触发，幂等可逆），`gh release edit` 将演练发布 `v1.1.0` 转 prerelease、稳定版固定 `--latest`，`get_latest_release` 口径回归稳定版；README 下载说明同步校正。仅改 release 元数据，不删除任何资产。

测试口径：Python 33 例（sync 22 / p2p 6 / pairing 5）+ 可选 DLL 冒烟 9 例、Rust 内核 25 例（历史 18 例）、Go 24 例（历史 20 例）、Tauri `engine_state` 测试。

---

# [v2.0.2] — 2026-11-22

发布日期：2026-11-22
发布范围：Tauri 客户端补丁版——**D7 / P1 假成功修复**（仪表盘读取 sync IPC 返回状态，失败不再显示「同步完成」）；Go 服务端与 v1 便携包按既定 release 流程重打（服务端代码与 v2.0.1 相同，仅版本号随版推进）。
协议兼容：HTTP `ServiceVersion` 保持 `1.0`，磁盘数据格式不变；本次为纯客户端行为修复，不涉及协议与存储变更。

## 客户端（Rust + Tauri）

- **D7 修复**：`Dashboard.svelte` 的 `syncMount` / `syncAll` 此前丢弃 `sync_mount` / `sync_all_mounts` 返回的 `SyncStatus`，同步失败（IPC 正常返回 `state:"error"` + `errors`）也显示「同步完成」。现在读取返回状态：单项失败显示 `同步失败 — <errors 明细>`，「立即同步全部」汇总成功/失败计数与逐挂载明细；不新增 IPC、不改返回形状。
- 新增 `tests/engine_state.rs::sync_once_surfaces_sync_failure_via_status_state_not_err`：钉死 Rust 侧契约（同步失败封装为 `Ok(SyncStatus)` 并写入 `get_status` 缓存；mount 不存在仍走 `Err`），契约一变测试先红。

## 验证

| 项目 | 结果 |
| --- | --- |
| GitHub Actions `ci-v2.yml` v2-client（`npm run build` + `cargo check --all-targets` + `cargo test --test engine_state`） | 全绿（D7 提交上实证） |
| Tauri Windows 安装包（NSIS，版本 2.0.2） | 流水线构建 + Windows 本机静默安装启动验证 |
| `release.yml` 资产校验（2 zip + 5 二进制 + 1 NSIS，非空 + 集合互斥） | 流水线内建 |

## 升级说明

客户端安装包直接覆盖升级；服务端无行为变更（v2.0.1 服务端可继续使用，二进制仅版本号差异），数据目录通用。

---

# [v2.0.1] — 2026-11-20

发布日期：2026-11-20
发布范围：Go 服务端补丁版——把 2026-11-09 合入 master 的 **C4-1 / O-7 删除安全修复**随版发布为 5 平台二进制；Tauri Windows 安装包仅同步版本号（2.0.0 → 2.0.1，无客户端行为变更）；Windows 便携包与服务端源码包按既定 release 流程重打。
协议兼容：HTTP `ServiceVersion` 保持 `1.0`，磁盘数据格式（`server.json` / `vault.db` / `blobs/`）不变，v1 / v2 客户端与既有数据目录可直接沿用。

## 服务端（Go）

- **C4-1 / O-7 随版发布**：`del` 统一为与 `put` 相同的 `base == current` 判据，缺 `base_hash` 且远端有内容时记 `remote_changed` 并跳过，畸形 / 旧客户端不再静默删除第三方新编辑（`TestCommitDelWithoutBaseRejectsRemoteEdit`）。该修复 2026-11-09 合入 master（`1c4a5fd`），v2.0.0 二进制（tag `1c8559c`，2026-11-04）未包含；LOOP-20261120-01 回归实测：v2.0.0 二进制 49/50，master CI 产物 50/50，本版以此收敛。

## 验证

| 项目 | 结果 |
| --- | --- |
| GitHub Actions `ci-v2.yml`（Go race / vet、5 平台构建、Python 兼容、Docker 冒烟、Tauri 构建） | 9/9 全绿 |
| Python 50 例回归（`SELFSHARE_SERVER_BIN` 对接本版 linux/amd64 二进制） | 50/50（含 C4-1 回归用例） |
| `release.yml` 发布前资产校验（2 zip + 5 二进制 + 1 NSIS，非空 + 集合互斥 + linux 二进制 `--version` 冒烟） | 流水线内建 |

## 升级说明

停止旧服务端 → 替换为本版二进制（或镜像）→ 用原 `--root` 数据目录启动；无需迁移，可随时回滚到 v2.0.0（数据格式相同）。

---

# [v2.0.0] — 2026-11-04

发布日期：2026-11-04
发布范围：Go 服务端 `selfshare-server` 2.0.0（5 平台二进制 + Docker 镜像）、Rust + Tauri 客户端源码与构建配置、CI/Release 工作流与文档。
协议兼容：HTTP `ServiceVersion` 保持 `1.0`，v1 客户端（Python CLI / Rust core / Flutter GUI）可直连；`server.json`、`vault.db`、`blobs/` 等数据目录可原样复用。

## v2：Go 服务端 + Rust/Tauri 客户端收敛

### 部署

- Go 服务端支持单二进制（5 平台交叉编译、`--version`）与 Docker（镜像内置 `HEALTHCHECK`、compose、systemd）。
- 新增根级 `.github/workflows/ci-v2.yml`：Go 竞态测试 / 多平台构建 / Python 协议兼容 / Docker 冒烟 / Tauri 构建。
- 删除 `v2/.github/workflows/ci.yml`（GitHub Actions 不会识别嵌套路径）。

### 客户端（Rust + Tauri）

- 补齐设置持久化、P2P 开关、巡检间隔、TLS（直连 HTTPS 服务端）、托盘实时状态与暂停/恢复/一键同步、在线节点列表。
- 仪表盘接入统计与轮询；设备页支持连接探测、配对令牌复制、节点列表；设置页只暴露真实生效的配置项。
- 修复前端构建：TypeScript 预处理器、缺失的 `styles.css`、Svelte 4 挂载 API、缺失的 `icon.icns`；生成 `package-lock.json`。
- 新增 `tests/engine_state.rs`（设置往返、暂停/恢复状态）。

### 服务端（Go）

- 新增配对码 / peers / registry 共 8 个单元测试，Go 测试共 20 项；`go vet` 零问题。
- 高频 blob / peers 请求改用不打开 SQLite 的轻量句柄：32×256 KiB、16 并发基准首次观测由 12.23 s / 0.65 MB/s 提升到 0.372 s / 21.5 MB/s；同轮受控 A/B 未复现该倍数（见 `v2/RELEASE_SUMMARY.md` §2.2）。
- 新增 `v2/scripts/bench_upload.py`（并发上传 + 摘要回读校验）。

### 工程与文档

- 补齐 `v2/` 构建产物忽略规则，避免约 8 GB 产物误入库。
- 重写 `v2/ARCHITECTURE.md`，清理收敛前的过期设计描述；更新 `v2/README.md`、文档站与 wiki 的快速开始。

### 验证结论

- Go 20/20 + `go vet` 0 issue；Python 29（其中 24 项对接真实 Go 二进制）；Rust 内核 18 + Tauri 2；前端 42 模块构建通过。
- Windows 与 WSL Linux 二进制运行、HTTPS `/api/ping`、并发基准首次观测 0.372 s / 21.5 MB/s（约 33 倍，同轮 A/B 未复现）与 32/32 回读一致均通过。
- Docker 镜像构建、Linux `go test -race`、Tauri 安装包打包与 Release 发布由 CI 覆盖（本机无 Docker 引擎 / gcc）；详见 `v2/RELEASE_SUMMARY.md`。

### 发布资产与升级

- Release 资产：`dist/*.zip`（v1 便携包与服务端包）+ `dist/v2/selfshare-server-*` 五个平台二进制；Docker 镜像由 `v2/server/Dockerfile` 构建。
- 升级：停止旧服务端 → 替换二进制或镜像 → 用原 `--root` 数据目录启动；数据格式兼容，无需迁移。
- 回滚：v1 与 v2 服务端共享磁盘格式，停止 v2 后用同一数据目录启动 v1 服务端即可。

### 工程收尾

- `CHANGELOG.md` 版本锚点改为 `[v2.0.0]`，`release.yml` 的 notes 提取兼容方括号标题，避免回退整份 CHANGELOG。
- 清理 `v2/superseded/` 早期缺陷实现；统一 CI / Pages 触发分支为 `master`；移除根 `ci.yml` 主流程软失败。

---

# v1.3.0 发布说明

发布日期：2026-11-03

## 重点：从「配置」变成「配对」

之前连接一台新设备需要：建库 → 抄令牌 → 填地址 → 填库名，四步手工操作。现在只需**一串配对码**。

### 服务端零配置起步

```bash
python selfshare.py server
```

首次启动自动创建同步库 `default`，并直接打印：

```text
     地址  : http://192.168.1.10:8484
     配对码: SS-XXXX-XXXX-XXXX
```

### 客户端一条命令

```bash
selfshare pair D:\同步盘 --url http://192.168.1.10:8484 --code SS-XXXX-XXXX-XXXX
```

自动完成：换令牌 → 写配置 → 首次同步。

### 桌面端两个输入框

「连接同步文件夹」对话框从 4 个字段缩减为 **文件夹 + 配对码**，地址栏带「测试连接」按钮即时校验。

## 配对码的安全设计

- **一次性**：兑换成功后立即作废，重复使用返回失败
- **有时效**：默认 30 分钟，最长 24 小时
- **不含令牌**：码本身只是搬运载体，兑换时才下发真实令牌
- **服务端可吊销**：`vault pair-code` 可随时查看未使用的码

令牌现在用服务端本地密钥加密存储（`token_sealed`），以便配对时还原。这是有意的取舍：能防 `grep server.json` 直接读到令牌，但不防服务端被完全攻陷——配对码的一次性与短时效已经压缩了攻击窗口。

## 文档

README 从 210 行精简到 100 行，三步快速开始放在最顶部。

## 新增

- `selfshare pairing` 模块与 5 个端到端测试
- `POST /api/pair`（唯一无需令牌的写接口）
- FFI：`ss_pair`、`ss_probe`
- CI 增加 pairing 测试步骤

## 验证

| 项目 | 结果 |
| --- | --- |
| Python 同步 | 15/15 |
| Python P2P | 3/3 |
| Python 配对 | 5/5 |
| Rust 单元 + 集成 | 6 + 9 |
| flutter analyze | 0 issue |
| Windows GUI 构建与冒烟 | 通过 |
| GitHub Actions | 7/7 全绿 |

# v1.2.0 发布说明

发布日期：2026-11-03（tag `baddac95`，指向提交 `27c3a25`）

- P2P 数据面扩展到 Python 与 Rust 两侧，GUI 接入 P2P 开关并完成 Windows 构建验证（提交 `b698089`、`1a5c1d3`、`27c3a25`；tag 附注：`P2P on both Python and Rust, GUI P2P toggle, verified Windows build`）。
- 该版本发布时未在本文件记录条目；以上依据 tag 附注与提交历史补写，用于补齐版本锚点，避免 `release.yml` 提取 notes 时回退整份 CHANGELOG。

---

# v1.1.0 发布说明

发布日期：2026-11-02

## 本次发布内容

### 1. 跨主机同步（服务端模式）

- 内容寻址存储：按 SHA-256 去重，同一内容只存一份
- 双向同步：三方合并（本地 / base 快照 / 远端），只传变化
- **冲突保留双方**：生成 `name (冲突副本-从 HOST 时间).ext`，任何一方的编辑都不会被覆盖
- 删除语义：不丢数据——远端删除 + 本地改动时保留本地并重新上传
- 全量版本历史，可按文件列出、可恢复任意历史版本
- 令牌加盐哈希存储，比较用常量时间；路径含 `..` 一律拒绝

### 2. P2P 同步（认证在中心，数据在节点）

- 节点向中心服务端注册监听地址与持有的 blob 哈希
- 拉取时优先查在线 peer，用 `HMAC(token, vault:peer:digest:nonce)` 双向认证后直连
- peer 不可达或没有该 blob 时自动回退到中心服务器
- 元数据（manifest / commit / history）始终走中心，保证全局一致
- 节点 TTL 300 秒，心跳 30 秒，下线自动剔除

用法：

```bash
python selfshare.py watch D:\同步盘 --p2p
```

### 3. Rust 同步内核

- 与 Python 服务端协议完全兼容，可与 Python 客户端混合部署
- 稳定 C ABI：19 个 `ss_*` 导出，配套 `selfshare_core.h`
- 提供独立 CLI（`selfshare-cli`）用于无 GUI 验证
- 本地状态用原子 JSON 快照，避免 SQLite 的 C 依赖

### 4. Flutter 桌面 GUI

- 多同步文件夹管理、即时同步与预演
- 实时进度、服务端容量/版本/修订统计
- 自动 watch、系统托盘常驻、关闭隐藏
- 版本历史浏览与一键恢复
- Windows 登录自启开关（计划任务）
- 同步操作在独立 isolate 执行，不阻塞 UI

### 5. 部署

- Windows 计划任务：GUI 托盘模式 + 纯 CLI watch 模式，两份 XML 模板和安装脚本
- 服务端 systemd：专用用户、自动重启、`ProtectSystem=strict` 等加固
- Linux 用户级 `selfshare-watch@.service`

## 验证结果

| 项目 | 结果 |
| --- | --- |
| Python 同步测试 | 15/15 通过 |
| Python P2P 测试 | 3/3 通过 |
| Rust 单元测试 | 6/6 通过 |
| Rust 集成测试（对接真实 Python 服务端） | 6/6 通过 |
| `flutter analyze` | No issues found |
| `flutter build windows --release` | 成功 |
| GUI 冒烟（窗口创建、稳定运行） | 通过，180 MB / 55 线程 |
| Rust P2P 集成测试 | 3/3 通过（HMAC 一致、节点服务、坏 MAC 拒绝） |
| 端到端 P2P 实测 | 通过，客户端输出 `<- peer:127.0.0.1:49376` |

## 已知边界

- P2P 面向局域网直连；公网 NAT 穿透（打洞/中继）尚未实现
- Rust Core 默认 HTTP；公网部署建议在 Nginx/Caddy 终止 TLS
- 单文件上限 2 GiB；改动为整文件传输
- 不保留 Windows ACL、符号链接、空目录
- GUI 当前一次管理一个活动 watch；多目录可分别用 CLI 计划任务

## 升级说明

v1.0.0 是内部首个可用版本（仅 Python 服务端 + CLI）。本版本未改动服务端存储格式和 HTTP 协议，旧数据目录可直接沿用。
