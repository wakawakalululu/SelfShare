# SelfShare

自建的跨主机文件夹同步。参考坚果云的「同步文件夹」体验：在一台机器上放一个文件夹，另一台机器挂载同一个同步库，两边看到同一份目录树，改动自动互传，历史版本可回溯，冲突不丢数据。

纯 Python 标准库实现，**零第三方依赖**，服务端和客户端是同一个程序。Windows / Linux / macOS 通用，另有 Rust 内核与 Flutter 桌面 GUI。

[![CI](https://github.com/wakawakalululu/SelfShare/actions/workflows/ci.yml/badge.svg)](https://github.com/wakawakalululu/SelfShare/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/wakawakalululu/SelfShare)](https://github.com/wakawakalululu/SelfShare/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-GitHub%20Pages-2ea44f)](https://wakawakalululu.github.io/SelfShare/)

## 它解决什么问题

坚果云这类服务需要一个云账号和公网存储。如果你只想在自己的两台机器（家里台式 + 公司笔记本、或本机 + 内网服务器）之间同步，SelfShare 用一台机器当服务端就够了：

- **一台机器跑服务端**，其余机器挂载本地文件夹
- **双向同步**：任何一端改动都会传到其他端
- **冲突保留双方**：像坚果云一样生成 `xxx (冲突副本-从 HOST 时间).txt`，不覆盖任何一方的数据
- **全量版本历史**：服务端保留每个文件的每次修订，可列出、可恢复
- **内容去重**：同一份内容只存一次（按 SHA-256），重命名/复制不额外占空间
- **可映射成盘符**：Windows 上用 `subst` 把同步目录挂成 `S:` 这样的盘符
- **P2P 直连传输**：中心服务器负责认证与发现，blob 数据优先走节点直连，节点不可达自动回退服务器

## P2P 同步

默认模式下所有 blob 都走中心服务器。内网多主机时打开 `--p2p`，让文件在节点之间直连传输：

```bash
# 每台主机都用 --p2p 启动 watch；中心服务器只做认证、发现和兜底存储
python selfshare.py watch D:\同步盘 --p2p
```

工作原理：

- 节点向中心服务器注册自己的监听地址和已持有的 blob 哈希
- 拉取时先查在线 peer，用 `HMAC(vault_token, peer_id:digest:nonce)` 双向验证后直连下载
- peer 不可达或都没有该 blob 时自动回退到中心服务器
- 元数据（manifest / commit / history）始终走中心服务器，保证全局一致
- 节点下线后中心端按 TTL（300s）自动剔除

Rust 内核（GUI 与 `selfshare-cli`）同样支持 P2P，与 Python 节点互通：

```powershell
selfshare-cli sync  D:\同步盘 --p2p
selfshare-cli watch D:\同步盘 --p2p
```

两端 HMAC 实现逐字节一致（已用相同输入比对校验），因此 Python 节点与 Rust 节点可互为 peer。

实测：Rust 客户端拉取时输出 `p2p.txt <- peer:127.0.0.1:49376`，数据未经中心服务器转发。节点不可达时自动回退，输出 `<- server`。

> 当前面向局域网直连场景；公网 NAT 穿透（打洞/中继）列入后续工作。

## 快速开始

不需要安装，克隆后直接用 `python selfshare.py`（也支持 `pip install -e .` 后用 `selfshare` 命令）。

### 1. 在「服务端」机器上

```bash
# 建一个同步库（会打印一次性令牌，记下来）
python selfshare.py vault create work --root D:\SelfShareData

# 启动服务（监听 8484；内网使用建议加防火墙规则）
python selfshare.py server --root D:\SelfShareData --port 8484
```

### 2. 在每台「客户端」机器上

```bash
# 把这个目录挂载到刚才的同步库
python selfshare.py mount D:\同步盘 --url http://192.168.1.10:8484 --vault work --token <令牌>

# 拉取远端内容
python selfshare.py sync D:\同步盘
```

两台机器都对同一个库执行 `mount`，就完成了跨主机挂载。之后：

```bash
python selfshare.py watch D:\同步盘     # 持续自动同步
python selfshare.py status D:\同步盘    # 看状态
```

### 3.（可选）挂成盘符

```bash
python selfshare.py drive S D:\同步盘
```

之后在资源管理器里通过 `S:` 访问，和坚果云盘符一个用法。

## 常用命令

| 命令 | 作用 |
| --- | --- |
| `vault create/list/info/rotate/remove` | 管理服务端同步库与令牌 |
| `server` | 启动同步服务（`--cert/--key` 可启用 HTTPS） |
| `mount` / `umount` | 挂载 / 卸载本地文件夹（卸载不删文件） |
| `sync` | 执行一次双向同步，`--dry-run` 只预演不落盘 |
| `watch` | 持续监视并自动同步 |
| `status` | 挂载点、上次同步、本地与远端修订 |
| `history` | 查看服务端版本历史，`--path` 过滤单个文件 |
| `restore` | 从历史版本恢复，可恢复到另一个文件名 |
| `doctor` | 自检配置、连通性、目录可写性 |
| `list` | 列出本机所有挂载点 |
| `init` | 在目录内生成 `.selfshareignore` 样例 |
| `drive` | Windows 下映射成盘符 |

## 冲突是怎么处理的

同步引擎维护一份「上次同步时双方一致的状态」（base），每次同步比较三方：本地、base、远端。

| 本地 vs base | 远端 vs base | 行为 |
| --- | --- | --- |
| 未变 | 未变 | 什么都不做 |
| 有改动 | 未变 | 上传 |
| 未变 | 有改动 | 下载 |
| 都改了，内容相同 | | 收敛，无操作 |
| 都改了，内容不同 | | **保留双方**：本地版本改名成冲突副本，远端版本占原名，副本再上传 |
| 本地删除 | 远端未变 | 服务端删除，其他主机跟随删除 |
| 本地删除 | 远端有改动 | 保留远端（不以删除覆盖别人的编辑） |
| 未变 | 远端删除 | 本地删除 |
| 有改动 | 远端删除 | 保留本地并重新上传（复活，不丢编辑） |

冲突副本命名：`纪要 (冲突副本-从 HOST ID 20261101-194802).txt`，同一秒多次冲突会追加序号。两端最终会收敛到同一份文件集合。

## 工作原理

```
客户端 A                    服务端                       客户端 B
 磁盘文件                     blobs/ (SHA-256 去重)
   ↕ 扫描/写入                vault.db (元数据+版本)
 state.db  ←── HTTP ──→  sync 服务  ←── HTTP ──→  state.db
 (base 快照)                                       (base 快照)
```

- **传输**：客户端把文件按内容哈希上传到 `/api/v/<vault>/blob/<sha256>`，服务端校验哈希后落盘；元数据通过 `/commit` 批量提交，一次同步只有一次写事务。
- **服务端存储**：`vaults/<id>/blobs/ab/abcdef…`，同一内容只存一份；`vault.db` 记录每个路径的当前版本与完整修订历史。
- **客户端状态**：挂载目录内的 `.selfshare/`（Windows 下设为隐藏）保存 base 快照与配置，其中含令牌，权限收紧为 0600。
- **本地扫描优化**：先用 `(size, mtime)` 快速比对，只有可能变过的文件才算 SHA-256；空闲时不哈希任何文件。
- **并发**：`/commit` 用 base_hash 做乐观并发控制，服务端发现的竞态以 `conflicts` 返回，客户端下次同步重新规划。
- **安全**：路径含 `..` 一律拒绝；令牌用加盐 SHA-256 存储，比较用 `hmac.compare_digest`；`vault rotate` 可吊销旧令牌。

## 忽略规则

挂载目录内放 `.selfshareignore`（语法类似 `.gitignore`）：每行一个模式，`*` 通配，结尾 `/` 只匹配目录，`!` 表示重新包含。`selfshare init <目录>` 会生成带常用条目的样例（`*.tmp`、`~$*`、`Thumbs.db` 等）。`.selfshare/` 与 `.git/` 始终不同步。

## 桌面 GUI 与开机自启

项目已新增 `desktop/`：使用 **Rust 同步内核 + Flutter GUI**，支持多挂载点、系统托盘、同步进度、历史恢复和 Windows 登录自启。Rust 客户端与本 Python CLI 使用同一服务端协议，可以混合部署。

详细构建和部署见 [`desktop/README.md`](desktop/README.md)。

### Windows GUI 计划任务（推荐）

```powershell
powershell -ExecutionPolicy Bypass -File deploy\windows\install-autostart.ps1 `
  -GuiExe "C:\Program Files\SelfShare\selfshare_desktop.exe" -Force
```

也可安装无 GUI 的后台 watch：

```powershell
powershell -ExecutionPolicy Bypass -File deploy\windows\install-autostart.ps1 `
  -SyncFolder "D:\同步盘" -PythonwExe "C:\Python312\pythonw.exe" `
  -SelfSharePy "C:\SelfShare\selfshare.py" -Force
```

计划任务 XML 位于 `deploy/windows/`，任务在**用户登录时**启动，避免 SYSTEM 会话无法访问用户目录和映射盘。

### 服务端 systemd

```bash
sudo bash deploy/systemd/install-server.sh /path/to/SelfShare
journalctl -u selfshare-server -f
```

配置文件：`/etc/selfshare/server.env`；数据目录：`/var/lib/selfshare`。服务单元位于 `deploy/systemd/selfshare-server.service`，带自动重启和 systemd 安全加固。Linux 用户级 watch 使用 `deploy/systemd/selfshare-watch@.service`。

## 限制与注意事项

- 只同步文件内容与修改时间，**不保留** Windows ACL、符号链接属性、空目录。
- 单文件上限 2 GiB（`server.py` 的 `MAX_BODY`）；传输为整文件上传，超大文件每次改动都会重传（内容去重只在服务端存储层生效）。
- `watch` 用轮询（默认 5 秒）而非系统通知，在 SMB/网络盘上行为一致；超大目录树建议调大 `--interval`。
- 服务端是单机 SQLite + 文件系统，适合个人/小团队（几千到几万文件）。要更高并发请换 PostgreSQL + 对象存储。
- 令牌明文存放在各挂载点的 `.selfshare/config.json`，请确保该目录不被同步或分享。
- Windows 的 `subst` 盘符**重启后失效**，需要开机脚本重新映射。

## 测试

```bash
python tests/test_sync.py        # 15 个用例：真实 HTTP 服务端 + 两个客户端目录
```

覆盖：双向同步、冲突保留双方、删除传播、删除 vs 编辑、忽略规则、2 MiB 二进制回环、内容去重、历史与恢复、令牌校验、增量清单、路径穿越防护、三主机收敛。

## 目录结构

```
selfshare/
  util.py      哈希、原子写入、路径规范化、忽略规则
  store.py     服务端存储：内容寻址 blob + SQLite 元数据与历史
  server.py    HTTP 同步服务（标准库）
  client.py    客户端 HTTP 传输
  sync.py      双向同步引擎：三方合并 + 冲突副本
  watch.py     轮询监视器
  config.py    挂载配置与全局挂载表
  cli.py       命令行
```
