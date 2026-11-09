# SelfShare

自建的跨主机文件夹同步。在一台机器上放一个文件夹，另一台机器挂载同一个同步库，两边看到同一份目录树，改动自动互传，历史版本可回溯，冲突不丢数据。

纯 Python 标准库实现，**零第三方依赖**。Windows / Linux / macOS 通用，另有 Rust 内核与 Flutter 桌面 GUI。

[![CI](https://github.com/wakawakalululu/SelfShare/actions/workflows/ci.yml/badge.svg)](https://github.com/wakawakalululu/SelfShare/actions/workflows/ci.yml)
[![Release v2.0.0](https://img.shields.io/badge/Release-v2.0.0-blue)](https://github.com/wakawakalululu/SelfShare/releases/tag/v2.0.0)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://github.com/wakawakalululu/SelfShare/blob/master/LICENSE)

## 为什么

坚果云这类服务需要云账号和公网存储。如果只想在自己的两台机器之间同步，SelfShare 用一台机器当服务端就够了：

- **双向同步**：任何一端改动都会传到其他端
- **冲突保留双方**：生成 `xxx (冲突副本-从 HOST 时间).txt`，不覆盖任何一方的数据
- **全量版本历史**：每个文件的每次修订都可列出、可恢复
- **内容去重**：同一份内容只存一次（SHA-256）
- **P2P 直连**：中心服务器只做认证与发现，文件在主机之间直传
- **可映射成盘符**：Windows 上用 `subst` 挂成 `S:`

## 三种部署形态

| 形态 | 适用场景 | 命令 |
| --- | --- | --- |
| 服务端 + CLI | 个人/小团队，最简 | `selfshare.py server` / `sync` |
| 服务端 + GUI | 需要托盘、进度、历史界面 | `selfshare_desktop.exe` |
| 中心认证 + P2P | 内网多机，减少服务器带宽 | `sync --p2p` |

## 快速开始（v1.3.0 配对流程）

### 服务端

```bash
python selfshare.py server --root D:\SelfShareData --port 8484
```

首次启动自动创建 `default` 库并打印地址与 30 分钟内有效的配对码。

### 客户端

```bash
python selfshare.py pair D:\同步盘 --url http://192.168.1.10:8484 --code SS-XXXX-XXXX-XXXX
python selfshare.py watch D:\同步盘 --p2p
```

`pair` 自动完成换令牌、写配置与首次同步；桌面端在「连接同步文件夹」里填同样的地址与配对码即可。
旧流程 `vault create` + `mount --token` 仍保留用于高级场景，但不再是推荐入口。

> 想用 Go 单二进制或 Docker 部署服务端（v2），参见仓库根 `README.md` 的 v2 章节与 `v2/README.md`。

## 文档

- [安装与部署]({{ '/install.html' | relative_url }})：服务端 systemd、Windows 计划任务
- [P2P 同步]({{ '/p2p.html' | relative_url }})：认证模型、节点发现、故障回退
- [桌面 GUI]({{ '/gui.html' | relative_url }})：构建、托盘、开机自启
- [冲突与版本]({{ '/conflicts.html' | relative_url }})：三方合并规则、恢复历史
- [架构]({{ '/architecture.html' | relative_url }})：存储、协议、C ABI

## 下载

- [稳定版 v2.0.0](https://github.com/wakawakalululu/SelfShare/releases/tag/v2.0.0)：Windows 便携包、服务端压缩包
- latest 当前为演练发布 `v1.1.0`（8 资产），按用户决定保留；稳定版请指定 `v2.0.0`（7 资产）
- 源码：`git clone https://github.com/wakawakalululu/SelfShare.git`

## 限制

- 单文件上限 2 GiB；改动为整文件传输
- 不保留 Windows ACL、符号链接、空目录
- P2P 目前面向局域网直连；公网 NAT 穿透未实现
- 服务端为单机 SQLite + 文件系统，适合个人/小团队规模

## 许可

[MIT](https://github.com/wakawakalululu/SelfShare/blob/master/LICENSE)
