# C4 · 三方合并与 commit 冲突判定契约

> 契约编号对应 `AGENTS.md` §5 与专家团 C1–C6 六件套。改动本契约任何一条都必须
> Python / Go / Rust 三端对齐并跑通跨实现兼容套件（D 轨道硬门槛）。
> 状态：2026-11-09 由 `LOOP-20261109-07` 落盘（D 轨道 G0/G1 已先行判定）。

## 1. 三方合并八情形（冻结，文本与实现同源）

权威表：`selfshare/sync.py:7-19`（Python 服务端/客户端规划）与
`desktop/core/src/engine.rs:5-15`（Rust 内核规划）。核心条款：

| 本地 | 远端 | 基线 | 动作 |
| --- | --- | --- | --- |
| 删 | 改 | 有 | `pull`，保留远端编辑（C4「删除撞编辑保留编辑」） |
| 改 | 删 | 有 | `push(force)`，保留本地编辑 |
| 改 | 改且内容不同 | 有 | `conflict`，保留双方（冲突副本） |
| 删 | 未变 | 有 | `delete_remote` 提交 `del` |
| 未变 | 删 | 有 | `delete_local` |

**不得**改写八情形表的文本；本文件只补充服务端 commit 层的冲突判定细则。

## 2. C4-1 · commit 的乐观并发判据（2026-11-09 修正）

对 `put` 与 `del` **统一**使用 `base == current` 判据，其中 `current` 是服务端
`files` 表中该 rel 的当前 hash（`deleted=1` 或行不存在时视为 `None`）：

1. `current is None` 的 `del` → 已删除，静默跳过（无副作用）。
2. `base != current` 的 `del` → 记 `Conflicts{reason:"remote_changed", path, remote_hash, remote_rev}`
   并**跳过**；不得 bump `head_rev`、不得写 `files.deleted=1`、不得追加 `versions` 的 del 记录。
3. `base == current` 的 `del` → 正常删除（bump + tombstone + 追加 del 版本）。
4. `put` 沿用既有 `current != base` 判据与 `force` 复活分支，不改动。

三端锚点：Python `selfshare/store.py:162-183`、Go
`v2/server/internal/store/vault.go:276-300`、客户端 `selfshare/sync.py:444-451`
与 `desktop/core/src/engine.rs:357-368`。

### 为什么收紧

2026-11-09 前 `del` 的条件是 `base is not None and current != base`，
`base_hash` 缺失（畸形 / 旧版 / 第三方客户端）时**跳过乐观并发**，直接置
`deleted=1`：A 取 manifest 后、commit 前 B 上传新内容 c，A 的无 base `del`
会把 c 从同步路径抹掉（blob 仍在，仅 history 可恢复）→ 违反「不丢数据」红线与
C4「删除撞编辑保留编辑」。修正后该 op 与 `put` 同样被判 `remote_changed`。

### 兼容影响（已发布行为变更）

- **正常客户端不受影响**：`plan_with` 仅在 `base` 有该 rel 且 `remote == base` 时
  产生 `delete_remote`（`sync.py:350-354`），提交恒带非空 `base_hash`；因此
  `test_delete_propagates`、`test_delete_vs_edit_keeps_edit` 等既有断言保持通过。
- 只有"发无 base `del`"的调用方由「静默删除」变为「收到 `remote_changed` 冲突」；
  Python 客户端 `sync.py:541-546` 记 errors 并 `state.forget(rel)`，下一轮规划
  走 `pull`（远端新增）保留远端内容，**不会死循环**。
- `/api/commit` 请求与响应形状、`ServiceVersion = "1.0"`、blob 布局、C2/C3/C5/C6
  条款全部不变；变更记录见 `docs/decisions/OPEN-DECISIONS.md` **O-7**。

## 3. 放行条件（G3）

- Python / Go 两端注入用例实跑：`del` 无 base 且远端有内容 → conflicts / applied 空 /
  文件内容仍为第三方新编辑 / `head_rev` 不递增 / `versions` 不追加 del。
- 正常删除回归不断（`test_delete_propagates` / `test_delete_vs_edit_keeps_edit`）。
- D 轨道硬门槛：`SELFSHARE_SERVER_BIN=<**新编译** Go 二进制绝对路径>`
  `python tests/test_sync.py -v` 与 `test_p2p.py -v` 全绿；旧 Go 二进制不能代表本改动。
- 本机无 cargo/go 时，Go 编译与 `go test -race` 须由 push 后 `ci-v2.yml server-test` 实证。
