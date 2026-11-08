# C5 · C ABI / IPC 契约（既有行为冻结）

> 状态：2026-11-08 由 `selfshare-dev-team` **D 轨道 G0/G1 契约先行**落盘。
> 依据：`AGENTS.md` §5.8 / §7、`desktop/core/include/selfshare_core.h:14-33`、
> `desktop/core/src/ffi.rs`、`desktop/app/lib/rust_bridge.dart`、
> `tests/test_core_dll.py`、`docs/contracts/requirement-card.md` §8。
>
> **本文件是静态影响面盘点的产物，未实跑任何测试或构建**；它把已发布行为升格为
> 契约条款，**不改变任何实现、不新增 ABI、不改 `ServiceVersion = "1.0"`**。
> 任何形状演进先走 `docs/decisions/OPEN-DECISIONS.md` 的 v2 变更记录（见 O-5）。

## C5-1 面与所有权

C ABI 导出 **19 个**，清单以 `selfshare_core.h:15-33` 为准。除 `ss_free`（`void`）外，
所有返回值是 UTF-8 JSON `char*`，**所有权归调用方**，必须经 `ss_free` 释放
（`selfshare_core.h:14`）。头文件只写「都是 UTF-8 JSON」，不描述形状，故以本文件为准。

## C5-2 两种合法形状（既有行为即契约，冻结，不得就地统一）

- **A 类 `ok_json`**：`{"ok":true,"data":<JSON>}`（`ffi.rs:79-82`），共 **15 个**：
  `ss_init`、`ss_mount`、`ss_pair`、`ss_probe`、`ss_unmount`、`ss_mount_info`、
  `ss_find_mount`、`ss_sync`、`ss_plan`、`ss_watch_start`、`ss_watch_stop`、
  `ss_history`、`ss_restore`、`ss_remote_stat`、`ss_shutdown`。
- **B 类 裸 JSON**：**`ss_version`**（`ffi.rs:99`）、**`ss_progress`**（`:431`）、
  **`ss_watch_status`**（`:537`）——顶层字段即数据，不经 `ok_json` 包装。
  `ss_progress` 字段集以 `ProgressSnapshot`（`ffi.rs:25-35`）为准。
- **错误形状**：`{"ok":false,"error":<string>}`（`ffi.rs:73-77`）。所有**显式**错误
  分支恒带 `ok:false`；退化分支见 C5-3。

## C5-3 冻结的例外（禁止「顺手修掉」）

以下均为**已发布行为**，本契约将其升格为条款；需要演进只能走 C5-5：

| 例外 | 证据 | 下游现状 |
| --- | --- | --- |
| `ss_probe` 双层 `ok`：`{"ok":true,"data":{"ok":bool}}` | `ffi.rs:282` | `rust_bridge.dart:191-192`、`test_core_dll.py:103-106` 均取 `data['ok']` |
| `ss_pair` 首次同步失败返回 `ok:true` + `warning` | `ffi.rs:262-267` | 语义与形状错位，暂不调整 |
| `ss_find_mount` 无匹配返回 `ok:false` | `ffi.rs:330` | 业务否定被编码为错误 |
| `to_c` NUL 兜底 `{"error":"internal: nul byte"}` 不带 `ok` | `ffi.rs:60-62` | 契约文本缺陷；`serde_json` 会转义 `\u0000`，实际只可能挂在 B 类函数上 |
| `ss_progress` 锁毒化返回 `{}` | `ffi.rs:432` | 无 `ok`、无 `error` 的退化形状 |

## C5-4 下游读取规则与同步面

- Dart `_unwrap`（`rust_bridge.dart:141-146`）**仅**在 `ok == false` 时抛
  `SelfShareException`，不校验 `ok == true`；B 类三个方法必须**绕过** `_unwrap`
  直取顶层字段（`:148` `version()`、`:228` `progress()`、`:249` `watchStatus()`）。
  `ss_init`（`:60`）与 `ss_shutdown`（`:294`）也绕过，属既有端点不一致。
- Python `_unwrap`（`test_core_dll.py:75-78`）更严格：`assert ok is True` 后取 `data`；
  6 个用例（`:63-106`）中有 3 个显式锁定裸 JSON、1 个锁定双层 `ok`，**是形状回归基线**。
- Rust `integration.rs:333-401` 用 `CStr` + 子串断言（不反序列化）；其中 `:386-398`
  直接匹配 `ss_progress` 裸文本，若包装进 `data` 会变成**静默假通过**。
- 形状变更须**四处同步**：`selfshare_core.h` / `rust_bridge.dart` /
  `test_core_dll.py` / `integration.rs`，并跑 **L1 `core-dll-smoke`**（`AGENTS.md:112`）
  与 **L2 Rust 集成**（`:113`）。**L4 是 Python↔Go HTTP 兼容套件**
  （`security-contract.md:54-59`），不作为 C ABI 验收依据。
- `v2/` 全目录不直连 C ABI，形状面变更对 Tauri / Go 服务端零直接影响；
  也不触碰 C6 安全契约（无令牌 / 密钥 / 路径 / 摘要变化）。

## C5-5 不可兼容判定

把 B 类改为 A 类包装、或消除 `ss_probe` 内层 `ok`，属于**不可兼容的 v2 协议变更**：
Dart 顶层字段取值全部变 `null`（`watchStatus()` 恒 `false`）、Python 冒烟断言失败、
`integration.rs` 子串断言静默假通过；`SELFSHARE_CORE_DLL` 冒烟针对 CI / Release 产物
（`AGENTS.md:66/:112`），旧 GUI / 旧测试配新 DLL 混跑必挂。

**禁止就地改写既有返回值**。演进只允许「新增 ABI + 旧 ABI 并存」，且必须先在
`docs/decisions/OPEN-DECISIONS.md` 记一条 v2 变更 + 影响说明（当前为 **O-5**）。
`ServiceVersion = "1.0"` 不因本面变更而改。

## C5-6 新增 ABI 的同步面

依 `AGENTS.md:104`，新增 ABI 须同步 **5 处**：
`selfshare_core.h:15-33`、`rust_bridge.dart:35-58`、`test_core_dll.py:22-28`、
`desktop/README.md:91-95`、`docs/gui.md:70-74`。
`ss_find_mount` 已有头文件与 `ffi.rs` 实现、但缺 Dart 绑定，属**补绑定**而非新增 ABI，
按 `requirement-card.md` §8 单独排期。

## 验收门禁

| 层 | 命令 / job | 说明 |
| --- | --- | --- |
| L1 | `SELFSHARE_CORE_DLL=<dll> python tests/test_core_dll.py -v`（6 例） | `ci.yml core-dll-smoke` 已覆盖（run `42474993786` 实证 success） |
| L2 | `cargo test --lib` / `cargo test --test integration` | `ci.yml rust` job；`ffi_pair_failure_resets_progress` 已在 `42474993786` 通过 |
| L5 | `cargo test --test engine_state`（6 例） | `ci.yml v2-client`；`42474993786` 实证 6 passed |

本文件为契约文本，不引入新的运行门禁；上述 job 状态引用自 2026-11-08 的真实 run。
