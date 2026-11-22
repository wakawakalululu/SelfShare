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
- **P2 断言加固（`LOOP-20261122-03`）**：`desktop/core/tests/integration.rs::ffi_pair_failure_resets_progress` 对 `ss_progress` 快照的断言从子串匹配改为 serde_json 反序列化进 `ProgressSnapshot`（快照必须可解析、`state` 复位为 `error` 且不得停留 `syncing`、`last_error` / `message` 非空）——进度 JSON 形状改动（字段改名/缺失/类型变化）时显式失败，不再静默假通过；`ProgressSnapshot` 相应补 `serde::Deserialize`（纯增量，C ABI 线上 JSON 输出不变，无新增依赖）。顺带修正 `desktop/scripts/build_windows.ps1` 注释错字（兑底→兜底），不改行为。
- **P2 flutter test 冒烟（`LOOP-20261122-05`）**：新增 `desktop/app/test/rust_bridge_smoke_test.dart`（8 例）——`flutter test` 在宿主机 VM 直跑 dart:ffi，覆盖桥接层自然业务面：裸 JSON 双函数（`ss_version` version=1.0.0 + host_id、`ss_progress` state 为字符串且非 syncing、`ss_watch_status` watching=false）、ok_json 包装（`ss_watch_stop` 幂等）、C5-3 无匹配白名单（`tryFindMount` → null / `findMount` → 异常）、错误通道（`mountInfo` 不存在目录 → `SelfShareException` 不崩）、不可达 `ss_probe` 返回 false、异常 toString 透传。`ci.yml` gui job 在 Analyze 后增补「Bridge layer smoke tests」步骤（`flutter test`）——该 job 前置的 `cargo build --release` 已把 DLL 落在桥接开发态回退路径，测试加载真实内核而非桩；不为 `ss_find_mount` 硬接业务调用点（路线图口径）。

- **P3 工程债收敛（`LOOP-20261122-07`）**：① `docs/contracts/abi-ipc.md` 行号近似引用全部改为符号/小节锚点（`ffi.rs::ok_json` 等；`selfshare_core.h` 清单锚点保留，由 `check_abi_names.py` 机械锁定），并修正两处已过时描述（`integration.rs` 现为反序列化断言而非子串断言；`security-contract.md` 引用指向真实小节）；② `build-test-deploy.yml` 移除与权威门禁重复的 `test-server`（ci-v2 `server-test`）与 `test-python`（ci.yml `python` + ci-v2 `compat`）两 job，收敛为「构建 + 冒烟 + 发布 + 部署」链路（Docker 冒烟保留为发布前置门），`CONTRIBUTING.md` / `AGENTS.md` 流水线描述同步；③ CHANGELOG 历史锚点统一：v1.x 段 `# v1.3.0 发布说明` 等改为 `# [v1.3.0]` 方括号约定，8 个版本锚点的 release.yml awk 提取全部非空。
- **P2 隔离环境冒烟·可达子项（`LOOP-20261122-07`）**：并发基准对 v2.0.4 release 二进制实跑（`bench_upload.py`：8 MiB / 16 并发 0.096 s = 83.49 MB/s，32/32 上传 + 32/32 回读一致）；Windows 原生实机执行 release 二进制 `--version`=2.0.4；NSIS 真实安装 + GUI 窗口由 v2.0.3 / v2.0.4 两轮截图闭环。环境受限余量（darwin / linux-arm64 实机、真一次性 VM）须硬件，如实记录不虚报。

- **Flutter material.dart 弃用——迁移尝试与生态结论（`LOOP-20261123-01`）**：Flutter stable 3.50.0 起 `package:flutter/material.dart` 标记 deprecated（info 级，改用 `package:material_ui/material_ui.dart`）。迁移提交 `28a4281` 以 ci.yml gui job 实测裁决：**material_ui 在 SDK 中存在但不是 material.dart 的 API 兼容门面**（导入可解析，但 `Color` / `InputDecorationTheme` / `OutlineInputBorder` / `BorderRadius` / `BorderSide` 等全部未定义，Analyze 失败）——机械迁移不成立，已回退（`0b9c90f`，恢复已发布内容）。结论：维持 material.dart + `--no-fatal-infos`（info 不拦截），真实迁移须等生态成熟并重写 UI 代码面，属条件触发项。
- **O-4 分析复核（`LOOP-20261123-01`，不动裁决）**：三端引用全景排查（Go `registry.go::sealKey` env 优先 / Python `_key()` 不读 env / Rust·Dart 零引用）+「支持/移除」两方案影响面与建议（维持 ADR-002；若需演进选「支持」兼容性优先），已追加至 `docs/decisions/OPEN-DECISIONS.md` O-4 分析记录。
- **§0.3.1 下一阶段提案（`LOOP-20261123-01`，待用户裁决）**：P2P 可观测性（R11 余量）、文档站/wiki 口径刷新、`bench_ab` 常态化、真实部署 `scan_vault_db` 采集指引、发版流程余量收敛（PAT 切 tag 自动触发 release.yml 与手动 dispatch 双跑）、semver 口径立此存照（功能进 minor，下一功能版 = v2.1.0）。见 PROJECT_STATUS §0.3.1。

测试口径：Python 33 例（sync 22 / p2p 6 / pairing 5）+ 可选 DLL 冒烟 9 例、Rust 28 例（lib 内联 14 + 集成 14；历史 18 例）、Go 24 例（历史 20 例）、Tauri `engine_state` 9 例、Flutter 桥接冒烟 8 例（flutter test，CI）。

---

# [v2.1.3] — 2026-11-23

发布日期：2026-11-23
发布范围：Rust 客户端数据安全补丁——**scan_dir 严格化（防误删传播）+ 手动同步/后台巡检互斥**（上轮多 agent 审计立项的两项同步语义修复，`LOOP-20261123-07`）。Go 服务端与 v1 便携包按既定 release 流程重打（服务端代码与 v2.1.2 相同，仅版本号随版推进）。semver：补丁位只收修复。
协议兼容：HTTP `ServiceVersion` 保持 `1.0`，磁盘数据格式与 C4 合并语义不变。

## 内核与客户端（Rust）

- **scan_dir 严格化（数据安全）**：`util.rs` 重构出 `scan_dir_strict`——任何 read_dir/metadata 失败显式报错。同步规划（plan/sync）切换到严格版：SMB/网络盘瞬时不可读的子树此前被静默跳过 → 文件从本地清单消失 → 引擎判「本地已删」→ **DeleteRemote 误删远端并传播到其它主机**；现在此类扫描失败会中止本次同步并报错，绝不误判删除。容错版保留给 peer 文件列表（非数据安全场景）。新增回归测试 `scan_dir_strict_reports_unreadable_subdir`（chmod-000 子目录必须报错）。
- **watcher 快照严格化**：变更检测的快照扫描失败时按「本轮无变化」跳过（on_message 记录），同步后的快照失败保留旧快照（下轮重检）——绝不把扫描失败当成删除信号。
- **手动同步 / 后台巡检互斥**：`WatchHandle` 增加 syncing 标志（run_once 包络），`sync_once` 在 watcher 同步进行中拒绝手动触发——修复手动同步与后台巡检对同一 mount 并发双跑导致的 state.json 丢更新与重复冲突副本。新增契约测试 `sync_once_not_blocked_by_mutex_after_watch_stopped`（监控停止后互斥不复位误伤）。
- **syncing 泄漏修复**：`sync_once` 的 syncing 集合改用 Drop 守卫（`SyncingGuard`）——错误/panic/future 取消的任何退出路径都保证移除，修复状态卡「同步中」直至重启的泄漏。

## 验证

| 项目 | 结果 |
| --- | --- |
| GitHub Actions `ci.yml`（rust 双平台：cargo test --release 全量含 scan_dir_strict/0600/percent_decode 回归；v2-client 四步 + `engine_state` 10 例） | 全绿 |
| GitHub Actions `ci-v2.yml` v2-client（`npm run build` + `cargo check --all-targets` + `engine_state`） | 全绿 |
| Tauri Windows 安装包（NSIS，版本 2.1.3） | 流水线构建 + Windows 本机静默安装启动验证（截图证据） |
| `release.yml` 资产校验（2 zip + 5 二进制 + 1 NSIS，非空 + 集合互斥） | 流水线内建 |

## 升级说明

客户端安装包直接覆盖升级；**建议所有使用网络盘（SMB/NFS）的用户升级**（本版修复瞬时不可读导致的误删传播）；服务端无行为变更（v2.1.2 服务端可继续使用），数据目录通用。



发布日期：2026-11-23
发布范围：稳健性补丁——多 agent 第二轮审计（Go 服务端深查 / Rust core+客户端深查）抓到的 3 项缺陷修复（`LOOP-20261123-06`）；Go 服务端与 v1 便携包按既定 release 流程重打。semver 口径：补丁位只收修复。
协议兼容：HTTP `ServiceVersion` 保持 `1.0`，磁盘数据格式与 P2P 认证（C6 §3）不变；无 IPC 形状变化。

## 服务端（Go）

- **blobbulk 部分失败不再泄露服务器路径**：`handlers.go` bulk 上传的 `failed[].error` 此前携带 `PutBlobBytes` 的原始错误（`*os.PathError` 含服务器绝对磁盘路径），认证客户端可见——与 `writeError` 500 分支刻意规避的泄露形态同类。现在细节写 stderr（`log.Printf`），客户端只拿分类消息「blob write failed」。
- **配对码 / peer 注册表并发丢更新修复**：`PairCodeStore` / `PeerRegistry` 此前**每请求新建实例**，实例内部互斥锁跨请求无效——`paircodes.json` 的 Redeem 读-改-写在并发下丢更新，**一次性配对码可被并发兑换两次**；`peers.json` 的 Register 同理。修复：`Server` 持每 vault 共享实例（`sync.Map` 懒创建，`LoadOrStore`），三个调用点改用共享实例，同 vault 操作在其自带锁上串行。Python v1 存在同类每请求模式（parity 备忘，本轮不改）。

## 内核（Rust）

- **`percent_decode` 字符边界 panic 修复**：查询串解码此前用 `&s[i+1..i+3]` 的 str 切片——`%` 紧邻多字节 UTF-8（如 `%a中`）时切到字符中间触发 panic，且位于**未认证**的 `/p2p/ping`、`/p2p/blob` 解析路径上（LAN 内可任意打崩单连接线程）。修复为逐字节十六进制解析（`hex_digit`），语义不变；新增回归测试 `percent_decode_handles_multibyte_after_percent`（Rust 27 例，lib 13 + 集成 14）。

## 审计口径说明

本轮为多 agent 第二轮深查：Go 服务端（0 红线违反、5 低风险：本轮修 2，其余 3 项为两端共有 parity/契约内行为，记录在 ANALYSIS §19）；Rust core+客户端（4 缺陷：本轮修 1 + 0600 已随 v2.1.1，scan_dir 吞错与 syncing 互斥属同步语义变更，立项为下一轮提案——见 ANALYSIS §19）；历史口径 9 漂移已由 `e9617b5` 修正（CHANGELOG [v2.1.0]/[v2.0.4] 标题恢复等）。

## 验证

| 项目 | 结果 |
| --- | --- |
| GitHub Actions `ci.yml`（rust 双平台含 percent_decode 回归；v2-client 四步） | 全绿（修复提交上实证） |
| GitHub Actions `ci-v2.yml`（server-test：`go test -race ./...` + `go vet`——共享 store 并发变更的 race 门禁；compat 28 例） | 全绿 |
| Tauri Windows 安装包（NSIS，版本 2.1.2） | 流水线构建 + Windows 本机静默安装启动验证（截图证据） |
| `release.yml` 资产校验（2 zip + 5 二进制 + 1 NSIS，非空 + 集合互斥） | 流水线内建 |

## 升级说明

服务端**建议升级**（配对码并发兑换与路径泄露修复在服务端生效）；客户端安装包直接覆盖升级；数据目录通用。



发布日期：2026-11-23
发布范围：Rust 内核安全补丁——**`config.json` 落盘权限修复**（多 agent 安全扫描抓到的红线违反，`LOOP-20261123-03`）；Go 服务端与 v1 便携包按既定 release 流程重打（服务端代码与 v2.1.0 相同，仅版本号随版推进）。本版为 semver 口径下的首个补丁版（补丁位只收修复）。
协议兼容：HTTP `ServiceVersion` 保持 `1.0`，磁盘数据格式不变；不触 P2P 认证（C6 §3）。

## 内核（Rust）

- **`config.json` 落盘 0600（AGENTS §5.4-4 红线修复）**：`desktop/core/src/util.rs::atomic_write` 此前用 `fs::File::create` 写临时文件（Unix 权限 = 0666 & ~umask，典型 0644），rename 后所有经它落盘的含令牌文件（Rust 内核 `config.json`（含 vault token）、Tauri 客户端 `registry.json`（含 MountConfig token））在 Unix 上全局可读——违反红线「config.json 落盘 0600」，且与 v1 Python（显式 chmod 0600）、v2 Go（`CreateTemp` 默认 0600）不对齐。修复：Unix 分支改用 `OpenOptions::mode(0o600)` 创建临时文件（rename 保留权限），Windows 走 ACL 无此语义、行为不变。新增回归测试 `util.rs::atomic_write_sets_owner_only_mode_on_unix`（断言落盘 mode == 0600，仅 unix 编译）。
- 来源：多 agent 安全扫描（`LOOP-20261123-03`，agent 报告 = 1 条红线违反 + 3 项附带风险 + 17 项合规确认 + 7 处哑令牌定性为低风险测试夹具）。

## 验证

| 项目 | 结果 |
| --- | --- |
| GitHub Actions `ci.yml`（rust 双平台：cargo test --release 全量含 0600 回归测试；v2-client：vite 构建 + 静态扫描 + `cargo check --all-targets` + `engine_state` 9 例） | 全绿（安全修复提交上实证） |
| GitHub Actions `ci-v2.yml` v2-client（`npm run build` + `cargo check --all-targets` + `engine_state`） | 全绿 |
| Tauri Windows 安装包（NSIS，版本 2.1.1） | 流水线构建 + Windows 本机静默安装启动验证（截图证据） |
| `release.yml` 资产校验（2 zip + 5 二进制 + 1 NSIS，非空 + 集合互斥） | 流水线内建 |

## 升级说明

客户端安装包直接覆盖升级（Windows 客户端走 ACL，权限行为不变；Unix/macOS 侧修复全局可读问题——建议尽快升级）；服务端无行为变更（v2.1.0 服务端可继续使用，二进制仅版本号差异），数据目录通用。

---

# [v2.1.0] — 2026-11-23

发布日期：2026-11-23
发布范围：Tauri 客户端功能版——**P2P 可观测性（R11 余量，§0.3.1 提案 A 经用户裁决立项）**；Go 服务端与 v1 便携包按既定 release 流程重打（服务端代码与 v2.0.4 相同，仅版本号随版推进）。**本版起 semver 口径生效：功能进 minor**。
协议兼容：HTTP `ServiceVersion` 保持 `1.0`，磁盘数据格式不变；新增一条只读 Tauri IPC `p2p_status`，不触 C5 C ABI 形状，P2P 认证（C6 §3）不变。

## 客户端（Rust + Tauri）

- **P2P 可观测性**：新增只读 IPC `p2p_status`（`P2pStatus{mount_name, enabled, watching, node, peers}`）——内核 `watcher.rs` 在 `PeerServer::start` 成功后把本机节点（peer_id + 监听地址）写入 `WatchHandle` 共享槽（`peer_node()`），引擎聚合设置开关 / 监控状态 / 本机节点 / 中心发现列表；设备页在本机节点行展示「运行中（监听地址）/ 未启动（原因）/ 未运行」。中心不可达时发现列表以空表达，不折叠成 Err（与内核回退容错口径一致）。默认关闭语义不变（O-2）；数据面（拉取/服务）不变。
- 新增契约测试 `tests/engine_state.rs::p2p_status_reports_complete_shape_without_node_when_disabled`（开关关闭 + 无监控 + 中心不可达的最简环境下快照形状完整且不虚报节点；mount 不存在仍 Err）。

## 验证

| 项目 | 结果 |
| --- | --- |
| GitHub Actions `ci.yml`（v2-client：vite 构建 + 静态扫描 + `cargo check --all-targets` + `engine_state` 含新契约测试；Rust 双平台矩阵） | 全绿（P2P 可观测性提交上实证） |
| GitHub Actions `ci-v2.yml` v2-client（`npm run build` + `cargo check --all-targets` + `engine_state`） | 全绿 |
| Tauri Windows 安装包（NSIS，版本 2.1.0） | 流水线构建 + Windows 本机静默安装启动验证（截图证据） |
| `release.yml` 资产校验（2 zip + 5 二进制 + 1 NSIS，非空 + 集合互斥） | 流水线内建 |

## 升级说明

客户端安装包直接覆盖升级；服务端无行为变更（v2.0.4 服务端可继续使用，二进制仅版本号差异），数据目录通用。P2P 仍默认关闭（设置页开启，限局域网）。

---

# [v2.0.4] — 2026-11-22

发布日期：2026-11-22
发布范围：Tauri 客户端功能版——**R5 / P2P 数据面接通**（`enable_p2p` 开关驱动的手动同步 peer 优先拉取 + 中心回退）；随版携带已入库的 **flutter 桥接冒烟门禁**；Go 服务端与 v1 便携包按既定 release 流程重打（服务端代码与 v2.0.3 相同，仅版本号随版推进）。
协议兼容：HTTP `ServiceVersion` 保持 `1.0`，磁盘数据格式不变；P2P 认证按 C6 §3（vault token HMAC 双向验证，token 不出现在 P2P 请求）不变，服务端发现列表接口无改动。

## 客户端（Rust + Tauri）

- **R5 P2P 数据面**：`sync_once` → `run_sync` 此前硬编码 `peer_id=None`（手动同步只走中心），现按设置开关（默认关闭，O-2 口径）在 `enable_p2p` 时设置 peer_id——拉取走 peer 优先、节点不可达**静默回退中心**（C6 §3）；blob 落盘前的摘要/大小校验、C4 合并语义、C5 ABI 形状均不变。后台监控路径的 P2P（R11 接线）不变：watcher 起本机节点并注册，监控周期同步 peer 优先。`peer_id` 仅作 exclude 句柄（`make_peer_id` 实例唯一），监控中自拉为回环命中、摘要校验保证正确性。
- 新增契约测试 `tests/engine_state.rs::sync_once_with_p2p_enabled_keeps_failure_shape`：开关开启 + 不可达中心（127.0.0.1:1，无 P2P 夹具）下 `sync_once` 仍返回 `Ok(SyncStatus{state:"error"})`——启用 P2P 不改变 IPC 失败形状；数据面路由由内核层既有测试覆盖（`tests/test_p2p.py` + Rust 集成）。
- 随版携带 `LOOP-20261122-05`：Flutter 桥接冒烟 8 例接入 `ci.yml` gui job（`flutter test`，宿主机 VM 直跑 dart:ffi 加载真实 DLL）。

## 验证

| 项目 | 结果 |
| --- | --- |
| GitHub Actions `ci.yml`（v2-client：vite 构建 + 静态扫描 + `cargo check --all-targets` + `engine_state` 含新契约测试；Rust 双平台矩阵） | 全绿（P2P 提交上实证） |
| GitHub Actions `ci-v2.yml` v2-client（`npm run build` + `cargo check --all-targets` + `engine_state`） | 全绿 |
| Tauri Windows 安装包（NSIS，版本 2.0.4） | 流水线构建 + Windows 本机静默安装启动验证（截图证据） |
| `release.yml` 资产校验（2 zip + 5 二进制 + 1 NSIS，非空 + 集合互斥） | 流水线内建 |

## 升级说明

客户端安装包直接覆盖升级；服务端无行为变更（v2.0.3 服务端可继续使用，二进制仅版本号差异），数据目录通用。P2P 仍默认关闭：需在设置页手动开启（限局域网，README §P2P）。

---

# [v2.0.3] — 2026-11-22

发布日期：2026-11-22
发布范围：Tauri 客户端功能版——**O-2 / O-3 轻量 UI**（设置页首次进入一次性提示；>512 MiB 大文件同步提示与预期时间估算）；随版携带已入库的 **P2 断言加固**（`ss_progress` 反序列化断言）与 **存量库只读扫描工具**；Go 服务端与 v1 便携包按既定 release 流程重打（服务端代码与 v2.0.2 相同，仅版本号随版推进）。
协议兼容：HTTP `ServiceVersion` 保持 `1.0`，磁盘数据格式不变；本次为纯客户端增量（新增一条 Tauri IPC 命令 `list_large_files`，只读本地文件系统，不触 C5 C ABI 形状），不涉及协议与存储变更。

## 客户端（Rust + Tauri）

- **O-2 设置页首次进入一次性提示**（裁决保持 P2P 默认关闭）：`Settings.svelte` 首次进入展示一次性提示（localStorage 标记 `ss_settings_first_visit_hint_shown`，仅显示一次，可手动关闭；localStorage 不可用时静默跳过），内容覆盖 P2P 默认关闭口径、单文件 2 GiB 上限、巡检间隔生效方式。
- **O-3 >512 MiB 大文件提示**：新增 Tauri 命令 `list_large_files`（commands.rs，只读遍历挂载本地目录，>512 MiB 阈值常量 `LARGE_FILE_THRESHOLD`；取到挂载路径即释放引擎锁）；`Dashboard.svelte` 每挂载首次加载时扫描一次（不随 5 秒轮询重复执行）+「查大文件」手动重查，命中时按文件列出大小并给出**预期时间估算**（按实测基准保守 ~10 MB/s，标注为估算；>512 MiB 改动即整体重传）。
- **P2 断言加固随版**：`integration.rs::ffi_pair_failure_resets_progress` 对 `ss_progress` 快照的断言改为 serde_json 反序列化进 `ProgressSnapshot`（形状改动显式失败，不再静默假通过）；`ProgressSnapshot` 补 `serde::Deserialize`（纯增量，C ABI JSON 不变）。
- 新增 O-2/O-3 接线静态扫描门禁：`desktop/scripts/check_v2_ui_hints.py`（11 项标记）+ `tests/test_check_v2_ui_hints.py`（5 例自测含篡改负例），接入 ci.yml v2-client 步骤与 python job self-tests 步骤。

## 验证

| 项目 | 结果 |
| --- | --- |
| GitHub Actions `ci.yml`（v2-client：vite 构建 + 静态扫描 + `cargo check --all-targets` + `engine_state`；python 矩阵 + self-tests） | 全绿（O-2/O-3 提交上实证） |
| GitHub Actions `ci-v2.yml` v2-client（`npm run build` + `cargo check --all-targets` + `engine_state`） | 全绿 |
| Tauri Windows 安装包（NSIS，版本 2.0.3） | 流水线构建 + Windows 本机静默安装启动验证（截图证据） |
| `release.yml` 资产校验（2 zip + 5 二进制 + 1 NSIS，非空 + 集合互斥） | 流水线内建 |

## 升级说明

客户端安装包直接覆盖升级；服务端无行为变更（v2.0.2 服务端可继续使用，二进制仅版本号差异），数据目录通用。

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

# [v1.3.0]

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

# [v1.2.0]

发布日期：2026-11-03（tag `baddac95`，指向提交 `27c3a25`）

- P2P 数据面扩展到 Python 与 Rust 两侧，GUI 接入 P2P 开关并完成 Windows 构建验证（提交 `b698089`、`1a5c1d3`、`27c3a25`；tag 附注：`P2P on both Python and Rust, GUI P2P toggle, verified Windows build`）。
- 该版本发布时未在本文件记录条目；以上依据 tag 附注与提交历史补写，用于补齐版本锚点，避免 `release.yml` 提取 notes 时回退整份 CHANGELOG。

---

# [v1.1.0]

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
