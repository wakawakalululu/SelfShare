# SelfShare

自建的跨主机文件夹同步。放一个文件夹，另一台机器输入一串码，两边内容自动一致；冲突不丢数据。

[![CI](https://github.com/wakawakalululu/SelfShare/actions/workflows/ci.yml/badge.svg)](https://github.com/wakawakalululu/SelfShare/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/wakawakalululu/SelfShare)](https://github.com/wakawakalululu/SelfShare/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

## 三步用起来

### 第 1 步：一台机器当服务端

```bash
python selfshare.py server
```

**不用建库，不用配置。** 首次启动会自动创建同步库，并直接打印：

```text
  ┌──────────────────────────────────────────────┐
  │  在另一台设备上连接（配对码 30 分钟内有效）  │
  └──────────────────────────────────────────────┘
     地址  : http://192.168.1.10:8484
     配对码: SS-5T8Y-E3FA-THV3
```

### 第 2 步：另一台机器连接

打开桌面端 `selfshare_desktop.exe` → 点「连接同步文件夹」→ 选文件夹 → 粘贴上面两行 → 点「连接」。

或者用命令行：

```bash
python selfshare.py pair D:\同步盘 --url http://192.168.1.10:8484 --code SS-5T8Y-E3FA-THV3
```

### 第 3 步：完成

桌面端会自动常驻托盘并持续同步。命令行用户加一条开机自启：

```powershell
powershell -ExecutionPolicy Bypass -File deploy\windows\install-autostart.ps1 `
  -GuiExe "C:\Program Files\SelfShare\selfshare_desktop.exe"
```

就这样。之后在两台机器的文件夹里增删改文件，几秒内就会同步到对端。

---

## 就是这样

不需要云账号，不需要域名，不需要开放公网。一台常开的机器（旧笔记本、NAS、树莓派都行）做服务端，其余设备配对即可。

## 它会做什么

| 场景 | 行为 |
| --- | --- |
| 两端改同一个文件 | 保留两份，`名字 (冲突副本-从 主机 时间).txt`，谁也不覆盖谁 |
| 一端删除，另一端没动 | 同步删除 |
| 一端删除，另一端改过 | 保留改动，不因删除丢编辑 |
| 想找回旧版本 | `selfshare history` 查看，`selfshare restore` 恢复 |
| 多台机器都连同一个库 | 全部看到同一份目录树 |
| 想省服务器带宽 | 加 `--p2p`，文件在机器之间直传 |

## 继续配置（可选）

```bash
selfshare watch  D:\同步盘 --p2p   # 常驻 + P2P 直连
selfshare status D:\同步盘         # 看状态
selfshare doctor D:\同步盘         # 出问题时自检
```

更多文档：

- [安装与部署](https://wakawakalululu.github.io/SelfShare/install.html)（systemd / 计划任务）
- [P2P 同步](https://wakawakalululu.github.io/SelfShare/p2p.html)
- [冲突与版本](https://wakawakalululu.github.io/SelfShare/conflicts.html)
- [桌面客户端](https://wakawakalululu.github.io/SelfShare/gui.html)
- [架构](https://wakawakalululu.github.io/SelfShare/architecture.html)

## 下载

[最新 Release](https://github.com/wakawakalululu/SelfShare/releases) 里有 Windows 便携包（解压即用）和服务端压缩包。

## 限制

- 单文件上限 2 GiB；改一次整体重传
- 不保留 Windows ACL、符号链接、空目录
- P2P 目前限局域网（公网穿透未实现）
- 服务端为单机 SQLite，适合个人/小团队

## 开发

Python 15 + P2P 3 测试，Rust 6 单元 + 9 集成测试，`flutter analyze` 零问题。详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可

[MIT](LICENSE)
