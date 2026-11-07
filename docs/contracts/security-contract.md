# C6 · 安全与配对契约

> 契约编号对应 `AGENTS.md` §5 与专家团 C1–C6 六件套。改动本契约任何一条都必须
> Python 与 Go 两端同步并跑通跨实现兼容套件（D 轨道硬门槛）。

## 1. 传输与鉴权

| 项 | 契约 | 两侧锚点 |
| --- | --- | --- |
| 主鉴权 | 除 `/api/ping`、`/api/pair` 外一律 `Authorization: Bearer <token>` | `selfshare/client.py:41`、`v2/server/internal/api/api.go:206` |
| 兜底鉴权 | Go 端额外接受 `X-Vault-Token: <token>` 头 | `api.go:212` |
| 鉴权顺序 | 先判 vault 存在性，再校验令牌；不得用 401 泄露路由差异 | AGENTS.md §5.4 |
| 令牌面 | token 只出现在请求头；不得进入 URL、日志、错误信息、提交信息与示例 | AGENTS.md §5.4 |

## 2. 配对码（一次性搬运载体，非长期凭证）

- 形态 `SS-XXXX-XXXX-XXXX`；**兑换后立即作废**（一次性）。
- TTL 钳制区间 `[60s, MAX_TTL]`，缺省落盘 `vaults/<id>/paircodes.json`，过期由 `_prune` 清理
  （`selfshare/pairing.py::issue/_prune`；Go 侧同语义）。
- 兑换返回 vault 令牌；令牌本身不在配对码里，不落明文日志。
- 服务端启动自动生成的启动配对码同样受 TTL 约束（`selfshare/server.py` `ttl=1800`）。

## 3. P2P 直连认证

- 中心签发发现列表（`/api/v/<vault>/peers`），数据面节点直连；
  节点间用 vault token 的 HMAC 双向验证：`HMAC-SHA256(token, "peer_id:digest:nonce")`
  （`selfshare/p2p.py::make_p2p_hmac`），token 不明文出现在 P2P 请求中。
- 客户端必须区分 **401（认证失败）** 与 **不可达（URLError）**：401 不得被当成
  "节点掉线"静默回退中心（`selfshare/client.py::get_blob_p2p`，回归用例
  `tests/test_p2p.py::BlobAdvertisementTestCase.test_peer_auth_failure_reports_status_not_unreachable`）。
- peer 注册表 `peers.json` 含 `last_seen`，TTL 300s 过期即从发现列表剔除。

## 4. 路径与摘要校验

- 相对路径统一经 `norm_rel`，拒绝 `..`；三端（Python `selfshare/util.py`、
  Rust `desktop/core/src/util.rs`、Go `store.AbsPath`）语义对齐。
- Python 客户端 `abs_path` 额外拒绝绝对路径与盘符段（`C:/x`、`C:rel`），拼接后
  `commonpath` 复核（ADR-001）；服务端只按 `rel` 存键不拼本地路径（O-1 维持）。
- blob 摘要严格 `^[0-9a-f]{64}$`；blob 落盘 `blobs/aa/<sha256>`，先校验后落盘。

## 5. 原子写与落盘权限

- 所有元数据/配置写入走 `atomic_write*`（同目录临时文件 + fsync + replace），
  崩溃不留半截文件（AGENTS.md §5.3）。
- `config.json` 落盘 `0600`（支持的平台上强制，`selfshare/config.py`）。
- 密钥类文件（`*.pem` / `*.key` / `.env` / `server.env`）不入库、不入日志、不入示例。

## 6. 配对码密封密钥（`SELFSHARE_SEAL_KEY`）

- Go 端 `registry.go::sealKey` 是唯一读取该环境变量的位置；Python 端不读。
- **跨实现混跑（Python ↔ Go）的部署不要设置它**：两端解封密钥不一致会导致
  配对兑换失败。已裁决维持现状，详见 `docs/decisions/ADR-002-seal-key-env.md`。

## 放行条件（G1/G3 依据）

- 本契约受影响时：Python 与 Go 两侧实现同步修改，L4 跨实现兼容套件必须实跑通过。
- 任何改动不得引入令牌 / 密钥 / 配对码的外泄路径（日志、错误信息、示例、产物入库）。
- 回归基线：`tests/test_pairing.py`、`tests/test_p2p.py`、`tests/test_sync.py` +
  `SELFSHARE_SERVER_BIN` 兼容模式全绿。
