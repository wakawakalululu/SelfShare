# C3 · 存储布局与 rel 键契约

> 契约编号对应 `AGENTS.md` §5 与专家团 C1–C6 六件套。改动本契约任何一条都必须
> Python / Go / Rust 三端对齐并跑通跨实现兼容套件（D 轨道硬门槛）。
> 状态：2026-11-09 由 `selfshare-dev-team` **D 轨道 G0/G1 契约先行**落盘
> （`LOOP-20261109-05`）。本文件以实读源码为准，未实跑的项在文末单列。

## 1. 存储面（冻结，仅列已实读锚点）

| 面 | 锚点 | 锁定内容 |
| --- | --- | --- |
| 库主键 | `selfshare/store.py:151,263`、`v2/server/internal/store/vault.go:20,31,241,454` | `files.rel` / `versions.rel` 是同一逻辑键；commit 与 history 都写/查该键 |
| manifest | `selfshare/store.py:237-255`、`vault.go:389-427` | `entries[].path` 回读 DB 中的 rel，不再二次变换 |
| base 快照 | `desktop/core/src/state.rs:148-161` | 本地基线键，与 manifest rel 对应 |
| blob | `selfshare/store.py:109-112`、`vault.go:150-155`、`api/handlers.go:147` | 摘要严格 `^[0-9a-f]{64}$`，落 `blobs/aa/<sha256>`，与 rel 无关 |
| 配对 / peer | `selfshare/pairing.py`、`selfshare/p2p.py:26`、`docs/contracts/security-contract.md` | `paircodes.json` / `peers.json`，本契约不重新定义其字段 |
| 版本 | `AGENTS.md:97-98` | `head_rev` 单调递增、`versions` 只追加 |

## 2. C3-1 · rel 键规范化（三端统一语义）

写入 `files.rel` / `versions.rel` / manifest / base 的值 = 该端 `norm_rel` / `NormRel` 的输出。三端统一：

1. 反斜杠 `\` → 正斜杠 `/`；
2. **整串首尾空白 trim**（在去 `./` 与去前导 `/` 之前）；
3. 反复去掉 `./` 前缀，再去掉前导 `/`；
4. 丢弃空段与 `.` 段；
5. 任何 `..` 段一律拒绝；
6. 空串由 `norm_rel` 返回 `""`，由 `abs_path` / `AbsPath` 判空拒绝。

三端锚点：Python `selfshare/util.py:38-51`、Go `v2/server/internal/store/util.go:15-32`、
Rust `desktop/core/src/util.rs:14-25`。Rust 的 `state.rs:148-161` 中 `set_base` /
`forget` / `base_of` 必须**同样经 `norm_rel` 归一**后再存取键，否则 trim 后
基线键与 `engine.rs` 查询键分叉，会误报 `remote_changed` 或重复上传。

**变更记录**：2026-11-09 前 Rust 未做步骤 2（trim），同一含首尾空白文件名会在
manifest/base 出现 `" a.txt"` 与 `"a.txt"` 两键，经 `sync.py:322` /
`engine.rs:160-164` 的键并集触发 Pull/Push 交替。本轮给 Rust 补 trim，对齐
**已发布** Python/Go 服务端；详细兼容影响见 `docs/decisions/OPEN-DECISIONS.md` O-6。

## 3. 盘符与 containment（按宿主 OS 分支，冻结）

- `norm_rel` 三端均把 `C:` 视作普通段，不在归一化层拒绝。
- **Windows**：Python `abs_path`（`util.py:73`）显式 `isabs` / `splitdrive` 拒绝并
  `commonpath` 复核（ADR-001）；Rust `abs_path`（`util.rs:38`）靠 `starts_with(root)`
  兜底；Go `AbsPath`（`util.go:43-46`）只做 `Clean` 前缀包含，且**生产零调用**
  （仅 `vault_test.go` 使用），服务端只按 `NormRel` 存键、不按 rel 拼本地路径。
- **POSIX**：三端都把 `C:/...` 当普通相对目录名，红线是结果不逃出 vault root。
- O-1（服务端是否也拒绝盘符）维持「保持现状 + 文档声明」；Go 不在 `NormRel`
  层收紧，否则会改变已发布存键面并影响历史库。

## 4. 限制披露（必须随契约一起读）

1. **含首尾空白的文件名不受支持**：三端 trim 后，服务端键与 Rust 本地键一致，
   但 Rust / Python 的 `abs_path` 会把带空格的文件名归一，导致本地读路径 Skip。
   这优于原先的无限 Pull/Push 抖动；用户不应创建首尾带空白的文件名。
2. **已发布产物仍是旧语义**：`v2.0.0` / 演练 `v1.1.0` 便携包内的 DLL 未补 trim，
   与新源码混跑时以服务端（Python/Go）的 trim 结果为准；不就地替换历史资产。
3. `ServiceVersion = "1.0"`（`api.go:30-31`）不因本契约改动而变化。

## 5. 双向兼容与边界（G1/G2 依据）

- 老库能被新代码读、新库能被老客户端读：历史 `vault.db` 的 rel 在写键前已由
  Python/Go trim，Rust 补 trim 只让本地键收敛，不改写任何已存键。
- 不得借本契约顺手改：C5 已冻结的 19 个 C ABI / 20 个 IPC 形状
  （`abi-ipc.md` C5-2/C5-5）、`/api/*` 路由与错误码、C4 三方合并八情形、
  blob 布局、配对/P2P 协议、`ServiceVersion`。
- 任何一端进一步收敛 trim 或盘符语义都属 v2 变更，须先按 O-1 做存量库只读扫描、
  三端实现与测试同步、L3/L4 兼容套件实跑，并在 `OPEN-DECISIONS.md` 登记。

## 放行条件（G3）

- Python / Go / Rust 三端 `norm_rel` 与 containment 用例实跑通过；
- D 轨道硬门槛：`SELFSHARE_SERVER_BIN=<Go 二进制绝对路径> python tests/test_sync.py -v`
  与 `test_p2p.py -v` 全绿；
- 本机无 cargo/go 时，Rust 编译与 Go 测试必须由 push 后 `ci.yml rust` /
  `ci-v2.yml server-test` 实证，未实证不得声称覆盖。

## 未验证项

本契约落盘前的影响面分析为**静态只读盘点，未实跑任何测试 / 构建**；
三端实现改动后的实证结果见 `LOOP-20261109-05` 的验证卡。
