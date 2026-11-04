# SelfShare v2

SelfShare v2 是对原 SelfShare 项目的重新架构，将服务端从 Python 迁移到 **Go**（高性能），客户端从 Flutter 迁移到 **Rust + Tauri**（参考 [syncthingtray](https://github.com/Martchus/syncthingtray)）。

## 架构概览

```
┌─────────────────────────┐     ┌──────────────────────────────┐
│   Go Server (高性能)      │     │   Tauri Client (Rust + Web)   │
│                         │     │                              │
│  • 标准库 net/http 路由    │     │  • 系统托盘集成               │
│  • SQLite 元数据         │     │  • 复用 selfshare-core 内核   │
│  • 内容寻址 Blob 存储    │     │  • Svelte 前端 UI             │
│  • 配对码认证            │     │  • 文件监控                   │
│  • P2P 节点发现          │     │  • 版本历史/恢复              │
│                         │     │                              │
│  部署:                   │     │  部署:                        │
│  • 单二进制文件           │     │  • Windows .exe 安装包        │
│  • Docker 容器           │     │  • Linux .AppImage/.deb       │
│  • systemd 服务          │     │  • macOS .app/.dmg            │
└─────────────────────────┘     └──────────────────────────────┘
           │                                  │
           └──────── HTTP API ────────────────┘
```

## 快速开始

### 服务端

#### 方式一：直接运行二进制

```bash
# Linux/macOS
./selfshare-server --root /var/lib/selfshare

# Windows
selfshare-server.exe --root C:\SelfShare\data

# 首次启动会自动创建 default 同步库并打印一张 30 分钟有效的配对码。
# 其它参数：--host 0.0.0.0  --port 8484  --cert/--key（TLS）  --quiet
```

#### 方式二：Docker 部署

```bash
cd server

# 构建镜像
docker build -t selfshare-server:v2 .

# 运行容器
docker run -d \
  --name selfshare \
  -p 8484:8484 \
  -v selfshare-data:/data \
  selfshare-server:v2

# 或使用 docker-compose
docker-compose up -d
```

#### 方式三：systemd 服务 (Linux)

```bash
# 单元文件在 server/deploy/selfshare.service，用 --root/--host/--port 传参
sudo cp server/deploy/selfshare.service /etc/systemd/system/selfshare.service
sudo systemctl enable --now selfshare
```

### 客户端

Tauri 客户端只做 GUI（托盘、窗口、IPC、Svelte 前端），真正的同步逻辑复用共享内核
`selfshare-core`（仓库根目录 `desktop/core/`，与旧 Flutter 客户端同一份 Rust 代码，已带 18 项测试）。
`src-tauri/Cargo.toml` 通过 `path = "../../../desktop/core"` 引用它。

```bash
cd client

# 安装依赖（需 Node.js 在 PATH 上；package-lock.json 保证可复现）
npm ci

# 开发模式 / 仅构建前端
npm run tauri dev
npm run build

# 构建安装包
npm run tauri build
```

## 目录结构

```
v2/
├── server/                     # Go 服务端（标准库 net/http，模块名 selfshare/server）
│   ├── cmd/selfshare-server/   # 入口（--root/--host/--port/--cert/--key/--quiet/--version）
│   ├── internal/
│   │   ├── api/                # HTTP 路由 + 处理器 + 兼容测试 (api_test.go)
│   │   └── store/              # SQLite 元数据 / Blob / registry / 配对码 / peers + 单元测试
│   ├── deploy/selfshare.service# systemd 单元
│   ├── Dockerfile              # golang:1.24-alpine → alpine，内置 HEALTHCHECK /api/ping
│   ├── docker-compose.yml
│   ├── Makefile
│   └── go.mod / go.sum
│
├── client/                     # Tauri 客户端（仅 GUI，逻辑委托内核）
│   ├── src-tauri/
│   │   ├── src/                # lib.rs / commands.rs / tray.rs / sync/
│   │   ├── tests/engine_state.rs
│   │   └── Cargo.toml          # selfshare-core = path ../../../desktop/core, features = tls
│   └── src/                    # Svelte 前端（Dashboard/Folders/Devices/History/Settings）
│
├── scripts/
│   ├── build.sh                # 一键构建服务端 / 客户端
│   └── bench_upload.py         # 并发上传基准 + 摘要回读校验
├── README.md
└── ARCHITECTURE.md

（同步内核本体在仓库根 desktop/core/；v2 的 CI 在仓库根 .github/workflows/ci-v2.yml，
 GitHub Actions 不识别 v2/.github/workflows/ 下的工作流。）
```

## API 兼容性

Go 服务端完全兼容原 Python 服务端的 HTTP API：

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/ping` | 存活检查（`engine: go`） |
| GET / POST | `/api/pair` | 服务信息 / 配对码换令牌 |
| GET | `/api/v/<vault>/manifest?since=<rev>` | 增量清单 |
| POST | `/api/v/<vault>/commit` | 批量提交（乐观并发） |
| GET | `/api/v/<vault>/history` | 版本历史 |
| GET | `/api/v/<vault>/stat` | 库统计 |
| PUT | `/api/v/<vault>/blob/<sha256>` | 流式上传 + 摘要校验 |
| GET / HEAD | `/api/v/<vault>/blob/<sha256>` | 下载（支持单段 Range） |
| POST | `/api/v/<vault>/blobbulk` | 批量上传（单个失败隔离） |
| GET | `/api/v/<vault>/peers` | P2P 节点发现 |
| POST | `/api/v/<vault>/peer/{register,heartbeat,unregister}` | 节点生命周期 |

## 服务端配置

服务端**只认命令行参数**（不读 `SELFSHARE_*` 环境变量）：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--root` | `selfshare-data` | 数据根目录（`server.json`/`vaults/<id>/...`） |
| `--host` | `0.0.0.0` | 监听地址 |
| `--port` | `8484` | 监听端口（`0` 表示随机） |
| `--cert` / `--key` | 空 | 提供则启用 HTTPS |
| `--quiet` | `false` | 不打印访问日志与启动配对码 |
| `--version` | — | 打印发行版本（当前 `2.0.0`）并退出，便于部署校验 |

## 验证状态（2026-11-04 本机实测）

| 项目 | 命令 / 方式 | 结果 |
| --- | --- | --- |
| Go 测试 | `go test ./...` | **20 个测试全绿**：12 个 API/存储兼容测试 + 8 个新增单测（配对码、peers、registry） |
| 静态检查 | `go vet ./...` | 0 issue |
| 协议兼容 | `SELFSHARE_SERVER_BIN=<Go 二进制> python tests/test_sync.py` / `test_p2p.py` | **19 + 5 全绿**（对真实 Go 进程跑 v1 全套用例：冲突、删除、历史、P2P HMAC） |
| Rust 内核 | `cd desktop/core && cargo test` | 7 单元 + 11 集成 = **18 全绿** |
| Tauri 客户端 | `cargo build --offline` / `cargo test --test engine_state` | 编译通过；设置持久化与暂停/恢复 2 个测试通过 |
| 前端 | `npm ci` / `npm run build` | 42 模块构建通过，生成真实 `dist/` |
| 二进制部署（Windows） | `selfshare-server.exe --version` + Python 兼容套件 | 通过 |
| 二进制部署（Linux） | WSL Ubuntu 运行 linux/amd64 二进制 + `/api/ping` | 通过（`--version 2.0.0`、自动建库、数据目录布局正确） |
| HTTPS | 自签证书 + `--cert/--key` + `/api/ping` | 通过；客户端已启用 `selfshare-core/tls` |
| 并发性能 | `python v2/scripts/bench_upload.py --server <二进制> --files 32 --size-kb 256 --workers 16` | 32/32 回读摘要一致；首次观测 0.372 s / 21.5 MB/s，复核口径见 `RELEASE_SUMMARY.md` §2.2 |
| Docker | 根 CI 的 `docker` job | 本机无 Docker 引擎，**未实测**；镜像构建与 `/api/ping` 冒烟由 CI 覆盖 |
| 竞态检测 | 根 CI 的 `server-test` job（`go test -race`，ubuntu） | 本机 Windows 缺 gcc/cgo 未实测；CI 覆盖 |

性能说明：blob 请求改为不打开 SQLite 后，首次观测由 12.23 s / 0.65 MB/s 提升到 0.372 s / 21.5 MB/s（约 33 倍）；同轮受控 A/B 未复现该倍数，基准须在空闲环境单独运行。细节见 `ARCHITECTURE.md` §2 与 `RELEASE_SUMMARY.md` §2.2。

## 构建

```bash
# 服务端：当前平台 / 全部平台
cd server && make build          # 输出 bin/selfshare-server
cd server && make test vet       # 单测 + 静态检查
cd server && make build-all      # linux amd64/arm64、windows amd64、darwin amd64/arm64

# 客户端（需 Node.js 与 Rust；package-lock.json / Cargo.lock 已入库）
cd client && npm ci && npm run build
cd client/src-tauri && cargo test --test engine_state
cd client && npm run tauri build  # Windows 安装包

# 一键构建 / 并发基准
./scripts/build.sh server-all
python scripts/bench_upload.py --server server/bin/selfshare-server
```

## 与 v1 的关系

- **API 完全兼容**：v2 Go 服务端可以与 v1 客户端（Python CLI / Rust core / Flutter GUI）互操作
- **数据格式一致**：SQLite schema 和 Blob 存储布局相同，可直接迁移数据目录
- **渐进迁移**：用户可以逐步从 v1 切换到 v2，无需一次性迁移
- **桌面端重构**：Rust + Tauri 客户端复用 `selfshare-core`，托盘状态/暂停/恢复参考 syncthingtray

## 许可证

MIT
