# ADR-001 · v1 客户端路径校验与 Rust/Go 对齐

- 状态：已采纳（2026-11-07）
- 决策人：协议架构师（D 轨道）
- 关联：C6 安全与配对契约、`PROJECT_STATUS.md` §3（安全类）、CHANGELOG `[Unreleased]`

## 背景

服务端把客户端 manifest 里的 `path` 原样交给 `store.norm_rel` 归一化后存库，客户端落盘时再用
`selfshare.util.abs_path` 把 `rel` 拼到本地同步目录上。

`norm_rel` 的职责只有两条：统一斜杠、拒绝 `..` 段；其余文本原样保留（这是有意的——服务端不该
改写用户文件名）。问题在于 `os.path.join(root, *rel.split("/"))` 的行为：

```
os.path.join("/vault", "C:", "Windows", "x.txt")
# Windows => "C:Windows\\x.txt"  —— root 被丢弃
```

`C:` 是**盘符相对路径**，不是绝对路径，因此不会被任何"以 / 开头"的判断拦截，但它足以让拼接结果
落到 vault 之外。实测（修复前，Windows）：

| 输入 `rel` | 拼接结果 | 是否在 vault 内 |
|---|---|---|
| `a/b.txt` | `<vault>\a\b.txt` | 是 |
| `C:/Windows/Temp/x.txt` | `C:\Windows\Temp\x.txt` | **否** |
| `C:relative/x.txt` | `C:\relative\x.txt` | **否** |
| `D:/x/y.txt` | `<vault>\x\y.txt`（同盘时被当作 root 下子路径） | 是（行为不一致） |

影响：同步清单由服务端下发；服务端被攻破、被中间人替换，或客户端自身构造出错时，v1 客户端会
按攻击者指定的位置**读**（上传本地文件）或**写**（覆盖本地文件）。Rust 内核
（`desktop/core/src/util.rs::abs_path`）与 Go 服务端（`store.AbsPath`）都已在拼接后做包含性校验，
只有 Python 侧缺失，属实现间安全基线不一致。

## 决策

在 `selfshare.util.abs_path` 中，`norm_rel` 之后、拼接之前增加两道校验：

1. `os.path.isabs(rel)` → 拒绝；
2. `os.path.splitdrive(rel)[0]` 非空 → 拒绝（覆盖 `C:`、`C:rel`、`\\?\` 等形式）。

拼接后再用 `os.path.abspath` + `os.path.commonpath` 做一次包含性复核，防御未来 `norm_rel` 语义变化。

刻意**不采用** `os.path.realpath` 做包含性判断：那会把 vault 内的符号链接目录判为逃逸，改变既有
行为（`norm_rel` 从未承诺解析符号链接），也会让每次落盘多一次 `lstat` 往返。符号链接的安全边界
仍由既有的 `SymlinkSafetyTestCase`（不跟随链接上传内容）负责，不在本 ADR 扩权。

## 备选方案

| 方案 | 代价 | 结论 |
|---|---|---|
| 在 `norm_rel` 里直接拒绝盘符段 | 服务端也会跟着变严，可能拒绝历史上合法存过的文件名 | 否决：会改变服务端行为，破坏兼容 |
| 用 `realpath` 全量校验 | 改变符号链接语义，性能下降 | 否决：超出本缺陷范围 |
| 只在客户端 `_fetch_blob` 处校验 | 读写路径共 10 处，容易漏 | 否决：单点收口更稳 |
| **在 `abs_path` 收口（本方案）** | 一处改动，所有调用点自动生效 | **采纳** |

## 影响

- 行为变化：含盘符段的 `rel` 从"可能写到 vault 外"变为抛 `ValueError`，由既有错误处理记为同步错误，
  不中断整轮同步。合法文件名不受影响（含中文、空格、`\` 分隔、`..` 之外的任意文本）。
- 协议：`ServiceVersion` 不变，磁盘布局不变，服务端与 Rust/Go 侧无需改动。
- 测试：新增 `SyncTestCase.test_abs_path_cannot_escape_vault`（3 个逃逸用例 + 2 个正常用例）。
- 回归：Python 30 例（sync 20 / p2p 5 / pairing 5）在"Python 服务端"与"真实 Go 二进制"两种模式下全绿。

## 未决

- 服务端是否也应拒绝盘符段（当前只在客户端拦）？若后续要做多租户共享 vault，建议在
  `store.norm_rel` 增加同样的拒绝，但需先评估存量数据里是否存在此类路径。此项记入 `OPEN-DECISIONS.md`。
