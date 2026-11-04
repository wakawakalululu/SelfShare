# SelfShare v2 架构（收敛版）

> 本文描述**当前实际实现**。早期设计草图里出现过的 `chi` 路由、`SELFSHARE_*` 环境变量、`--data-dir`、
> Tauri 客户端自带 SyncEngine、以及 `v2/client/src-tauri/src/sync` 内实现 HTTP 客户端等说法均已废弃，
> 以本文与 `v2/README.md` 的「验证状态」为准。

## 1. 总体结构

```
┌──────────────────────────┐        HTTP API         ┌──────────────────────────────┐
│ Go 服务端 v2/server       │ ◄──────────────────────► │ Rust + Tauri 客户端 v2/client │
│  • 标准库 net/http        │                          │  • 系统托盘 / 窗口 / IPC      │
│  • modernc.org/sqlite     │                          │  • Svelte 前端（5 个页面）    │
│  • 内容寻址 blob 存储      │                          │  • 同步逻辑委托共享内核        │
│  • 配对码 / P2P 节点发现   │                          └──────────────┬───────────────┘
│  • 单二进制 / Docker       │                                         │ 复用
└──────────────────────────┘                          ┌──────────────▼───────────────┐
                                                       │ selfshare-core（desktop/core）│
                                                       │ 三方合并 / 冲突副本 / 原子写  │
                                                       │ 删除传播 / 监视线程 / P2P 数据面│
                                                       └──────────────────────────────┘
```

**关键取舍**：不重写同步算法。Go 只实现服务端协议与存储，Tauri 只做 GUI 与状态编排，
两者都通过已验证的 `selfshare-core` / Python 兼容协议对接，因此 v1 与 v2 可以混跑、数据目录可直接复用。

## 2. Go 服务端（`v2/server`）

| 层 | 文件 | 职责 |
| --- | --- | --- |
| 入口 | `cmd/selfshare-server/main.go` | 命令行参数、零配置建库、启动配对码打印、TLS、优雅关闭、`--version` |
| HTTP | `internal/api/api.go` | 路由分发、Bearer 令牌鉴权、错误码映射 |
| HTTP | `internal/api/handlers.go` | manifest / commit / history / stat / blob / blobbulk / pair / peers |
| 存储 | `internal/store/vault.go` | SQLite 元数据、三方合并、版本历史、blob 流式写入（sha256 校验 + 原子替换） |
| 存储 | `internal/store/registry.go` | `server.json`：库注册、令牌加盐哈希、可逆密封令牌（配对时下发） |
| 存储 | `internal/store/pairing.go` | `paircodes.json`：一次性、有时效、可吊销的配对码 |
| 存储 | `internal/store/peers.go` | `peers.json`：P2P 节点注册/心跳/发现（TTL 300s） |

### 性能设计

- **blob 请求不碰 SQLite**：`PUT/GET/HEAD /api/v/<vault>/blob/...`、`blobbulk`、`peers` 走
  `store.OpenBlobStore`（只创建 `blobs/` 目录的轻量句柄），避免为每个高频请求打开数据库、
  执行 PRAGMA 与 schema 检查。仅 manifest / commit / history / stat 使用完整 `OpenVault`。
- **按需打开 DB**：完整 Vault 仍是「请求级打开、用完即关」，与 Python 一致，这样 Windows 上
  删除同步库或整目录拷贝时不会因长期持有 `vault.db` 而失败。
- **流式写入**：`WriteBlobStream` 边收边算 sha256，写入临时文件 → `Sync` → `Close` → `Rename`，
  不把 2 GiB 文件整体读进内存；摘要不符直接丢弃。
- 实测（本机 Windows，32 × 256 KiB、16 并发）：首次观测优化前 12.23 s / 0.65 MB/s、优化后
  0.372 s / 21.5 MB/s（约 33 倍），32/32 回读一致；同轮受控 A/B 未复现该倍数，基准对负载敏感，
  不作为量化 SLA（见 `v2/RELEASE_SUMMARY.md` §2.2）。复跑命令见 `v2/scripts/bench_upload.py`。

### 部署形态

- 单二进制：`CGO_ENABLED=0 go build`，可交叉编译 linux/windows/darwin（amd64、arm64）。
- Docker：`golang:1.24-alpine` 构建 → `alpine:3.20` 运行，非 root 用户、卷 `/data`、
  内置 `HEALTHCHECK /api/ping`；`docker-compose.yml` 提供端口映射与健康检查。
- systemd：`server/deploy/selfshare.service`（专用用户、`ProtectSystem` 等加固）。
- HTTPS：`--cert` / `--key` 启用 `ServeTLS`；客户端已启用 `selfshare-core/tls`。

## 3. Rust + Tauri 客户端（`v2/client`）

| 层 | 文件 | 职责 |
| --- | --- | --- |
| 装配 | `src-tauri/src/lib.rs` | 插件、AppState、19 个 IPC 命令、托盘状态更新任务 |
| IPC | `src-tauri/src/commands.rs` | 请求/响应 DTO，转调 `SyncEngine` |
| 托盘 | `src-tauri/src/tray.rs` | 打开窗口、立即同步全部、暂停/恢复、退出；tooltip 每 5 秒反映同步状态（参考 syncthingtray） |
| 编排 | `src-tauri/src/sync/engine.rs` | 多挂载注册表、设置持久化、全局暂停/恢复、一键同步、在线节点查询 |
| 引导 | `src-tauri/src/sync/client.rs` | 仅 `/api/ping` 与 `/api/pair` 两个无鉴权端点 |
| 前端 | `src/*.svelte` | 仪表盘 / 同步文件夹 / 设备 / 版本历史 / 设置 |

同步数据面全部由 `desktop/core`（`selfshare-core`）提供：`Syncer`、`watcher::spawn`、
`LocalState`、`Client::peers` 等。客户端通过 `path = "../../../desktop/core"` 依赖它，
并启用 `tls` feature 以直连 HTTPS 服务端。

**设置持久化**：`config_dir/settings.json` 保存默认服务器地址、巡检间隔（5–3600 秒）与
P2P 开关；`watcher::spawn(..., enable_p2p, ...)` 由此读取，不再写死「纯中心模式」。
设置页只暴露真正生效的字段，避免展示无法落地的开关。

## 4. API 兼容（与 Python 服务端逐路由一致）

| 方法 | 路径 | 功能 |
| --- | --- | --- |
| GET | `/api/ping` | 存活检查（含 `engine: go`） |
| GET / POST | `/api/pair` | 服务信息 / 配对码换令牌 |
| GET | `/api/v/<vault>/manifest?since=<rev>` | 增量清单 |
| POST | `/api/v/<vault>/commit` | 批量提交（乐观并发、冲突保留双方） |
| GET | `/api/v/<vault>/history` | 版本历史 |
| GET | `/api/v/<vault>/stat` | 库统计 |
| PUT / GET / HEAD | `/api/v/<vault>/blob/<sha256>` | 上传 / 下载（单段 Range）/ 元信息 |
| POST | `/api/v/<vault>/blobbulk` | 批量上传，单个失败不影响其它 |
| GET | `/api/v/<vault>/peers` | P2P 节点发现 |
| POST | `/api/v/<vault>/peer/{register,heartbeat,unregister}` | 节点生命周期 |

`ServiceVersion` 保持 `"1.0"`，老客户端据此做协议判断；发行版本由 `--version` 输出（当前 `2.0.0`）。

## 5. 数据格式与迁移

- `server.json` / `vaults/<id>/vault.db` / `vaults/<id>/blobs/aa/<sha256>` /
  `paircodes.json` / `peers.json` 与 Python 实现逐字节兼容，可直接把 v1 数据目录交给 Go 服务端。
- 迁移路径：先只换服务端（客户端不动）→ 再换桌面端 → 按需开启 P2P / HTTPS；
  两端可随时回退，无需一次性切换。
- 早期基于 `chi` 的重写（存在配对码空指针、peers stub 等缺陷）已从 `v2/superseded/` 删除；
  仓库内唯一的服务端构建入口是 `v2/server`，不再存在第二个 Go 模块。

## 6. 持续验证

根 `.github/workflows/ci-v2.yml` 覆盖：Go `go test -race` / `go vet`、5 平台二进制构建、
Python 兼容套件对接 Go 二进制、Docker 镜像与 `/api/ping` 冒烟、Tauri 前端与客户端构建。
本机验证结果见 `v2/README.md`「验证状态」与仓库根 `PROJECT_STATUS.md`。
