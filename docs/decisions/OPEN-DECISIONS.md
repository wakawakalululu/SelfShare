# 未决事项

按 `AGENTS.md` §7 约定存放；每条含"待谁拍板 / 不拍板的后果"。已决定的事项移入 `ADR-XXX.md`。

---

## O-1 · 服务端是否也拒绝盘符路径段

- 背景：`selfshare/util.py::abs_path` 已在客户端拦掉 `C:` 一类逃逸（`ADR-001`），服务端
  `store.norm_rel` 仍原样存。当前不构成越权（服务端只按 `rel` 存键，不拼本地路径），
  但共享 vault 场景下不同客户端对同一 `rel` 的解释可能不同。
- 选项：
  1. 服务端同样拒绝，需先扫存量库（`vault.db` 的 files 表）确认无此类路径；
  2. 保持现状，仅在文档声明"`rel` 必须相对、不含盘符"。
- 影响：选项 1 更严但可能拒绝历史数据；选项 2 零风险但对新客户端无约束。
- 建议：先做只读扫描（不阻塞发布），有数据再决定。
- 待拍板：协议架构师 + 发布运维。

## O-2 · v2 客户端是否恢复 P2P 数据面

- 背景：`PROJECT_STATUS.md` R5 记录 v2 客户端曾写死关闭 P2P，后改为设置开关驱动。
- 现状：默认关闭，需用户在设置里开启；README 已说明 P2P 限局域网。
- 待确认：默认值是否应改为"跟随服务端能力自动开启"，避免用户以为没这功能。
- 建议：保持默认关闭（安全），但在设置页首次进入时给一次性提示。

## O-3 · 单文件 2 GiB 上限与"改一次整体重传"

- 背景：`README.md` §限制 明示；分块增量传输未实现。
- 影响：大文件（视频、镜像）体验差，但改成分块会动 C4 同步语义契约。
- 建议：不改现有语义，作为 v3 议题；短期在客户端对 >512 MiB 文件给出进度提示与预期时间。

## O-4 · `SELFSHARE_SEAL_KEY` 只有 Go 端读取，是支持还是移除

**已裁决（2026-11-08）：保持现状 + 文档警示，见 `ADR-002-seal-key-env.md`。**

## O-5 · C ABI 返回 JSON 是否就地统一为 `ok_json`（**v2 变更**）

- 背景：`requirement-card.md` §8 把「3 个裸 JSON、`ss_probe` 双层 `ok`、NUL 错误分支缺 `ok`」
  移交 D 轨道。静态盘点确认 `ss_version` / `ss_progress` / `ss_watch_status` 为裸 JSON
  （`ffi.rs:99/:431/:537`），形状已被 Dart 3 个方法（`rust_bridge.dart:148/:228/:249`）、
  Python 3 个用例（`test_core_dll.py:68-72/:88-94/:101`）、Rust 集成测试
  （`integration.rs:386-398`）锁定，属**已发布行为**。
- 变更性质：**不可兼容**。就地包装会使 Dart 顶层字段取值变 `null`、Python 冒烟断言失败、
  `integration.rs` 子串断言**静默假通过**；`SELFSHARE_CORE_DLL` 冒烟针对 CI / Release 产物
  （`AGENTS.md:66/:112`），旧 GUI / 旧测试配新 DLL 混跑必挂。触及 `AGENTS.md:98/:104` 红线。
- 影响说明：详见 `docs/contracts/abi-ipc.md` C5-2 / C5-3 / C5-5。下游 3 处实现 + 2 组测试
  + 文档 5 处须同步；门禁为 L1 `core-dll-smoke` 与 L2 Rust 集成，**L4 不适用**；
  C6 安全契约不受影响；`ServiceVersion` 保持 `1.0`。
- 选项：1) **冻结现状**，以 `abi-ipc.md` 把两种形状升格为契约，未来用「新增 ABI +
  旧 ABI 并存」演进；2) 就地统一，须标 v2 大版本、重跑 L1 / L2 / L6 并作废便携包内
  DLL 混跑兼容承诺。
- 建议：**选 1**（2026-11-08 D 轨道 G0/G1 已按此落盘契约）。本轮只做契约与文档澄清，
  `ss_find_mount` 补绑定另立单元；任何形状改动停在 G0 等拍板。
- 待拍板：协议架构师 + 客户端工程师（Dart）+ 发布运维。不拍板的后果：一旦有人
  「顺手统一」，旧产物冒烟套件与已发布 GUI 将同时失效且难以归因。
- 验证状态：本条为**静态影响面分析，未实跑任何测试 / 构建**；契约落盘后由
  `AGENTS.md` §6 的既有 job 守护形状回归。

## O-6 · 三端 `norm_rel` trim 与 Windows 盘符 containment 是否统一（**v2 变更记录**）

- 背景（2026-11-09 `selfshare-dev-team` D 轨道只读核实）：Python `selfshare/util.py:44`
  与 Go `v2/server/internal/store/util.go:16` 在反斜杠替换后对整串做首尾 trim，
  Rust `desktop/core/src/util.rs:15` 不 trim；同一含首尾空白文件名可在 manifest /
  base 出现 `" a.txt"` 与 `"a.txt"` 两键，经 `sync.py:322` / `engine.rs:160-164`
  键并集触发 Pull/Push 交替。Windows 盘符：Python `util.py:73` 显式拒绝，Rust
  `util.rs:38` 靠 containment 兜底（测试为容错断言），Go `util.go:43-46` 无
  `filepath.VolumeName` 且 `vault_test.go:359-360` 已固化「`C:` 为普通段」；
  POSIX 三端均视其为普通相对路径。Go `AbsPath` 生产**零调用**，服务端只按 rel 存键。
- 影响说明：改动任一端的 rel 归一或盘符处理都会改变 `files.rel` / `versions.rel`
  键空间（C3、`vault.go:20/31`）；统一不 trim 会改已发布 Python/Go 服务端行为并
  违反「新库能被老客户端读」；统一 trim 需重编译 Rust DLL，已发布便携包内 DLL
  仍是旧语义（混跑以服务端 trim 为准）；三端统一接受盘符会撤销 ADR-001 加固。
  `ServiceVersion` 保持 `"1.0"`，blob 布局 / C4 八情形 / C5 ABI·IPC 形状均不受影响。
- 选项：1) **trim 收敛**：只给 Rust 补 trim，对齐已发布 Python/Go 服务端（历史库键
  不变，可平滑）；2) **盘符冻结**：按 OS 分支把现状升格为契约，未来统一另立 v2 变更；
  3) 统一不 trim / 三端统一接受盘符（**不可兼容，否决**）。
- 建议与裁决（2026-11-09 D 轨道 G0/G1）：**选 1 + 2**。本轮落盘
  `docs/contracts/storage-layout.md`（C3）与本契约 §4 C6-2；实施限于 Rust
  `norm_rel` / base 键与三端测试断言，**不改 Python / Go 生产代码**；D2 盘符语义
  冻结，禁止顺手改 `NormRel` 或服务端存键面。限制披露（首尾空白文件名不受支持、
  已发布 DLL 旧语义）写入 C3 §4。
- 待拍板：协议架构师 + 同步内核工程师 + 客户端工程师（Dart/DLL）+ 发布运维
  —— 仅针对「未来是否立项 D2 统一」；本轮 trim 收敛已按契约先行实施。
  不拍板的后果：有人「顺手统一盘符或 trim 方向」将静默改写 `vault.db` 键空间，
  老客户端与已发布便携包 DLL 混跑分叉且难以归因。
- 验证状态：影响面为**静态只读盘点，未实跑任何测试 / 构建**；本轮实现改动后由
  L1 / L4（`SELFSHARE_SERVER_BIN` 兼容套件）与 push 后 `ci.yml rust` /
  `ci-v2.yml server-test` 实证，结果见 `LOOP-20261109-05` 验证卡。
