# SelfShare

跨主机文件夹同步。冲突保留双方，中心服务器负责认证，文件可走 P2P 直连。

## 从这里开始

| 我想… | 看这里 |
| --- | --- |
| 五分钟跑起来 | [[快速开始]] |
| 在 Linux 服务器上部署 | [[安装与部署]] |
| 让内网多机直连省带宽 | [[P2P 同步]] |
| 理解冲突怎么处理 | [[冲突与版本]] |
| 用桌面 GUI | [[桌面客户端]] |
| 看内部实现 | [[架构说明]] |
| 遇到问题 | [[常见问题]] |

## 它解决什么

坚果云这类服务需要云账号和公网存储。如果只想在自己的两台机器之间同步，用一台机器当服务端就够：

- 双向同步，任何一端改动都会传到其他端
- 冲突保留双方，生成 `xxx (冲突副本-从 HOST 时间).txt`
- 每个文件的每次修订都可回溯、可恢复
- 相同内容只存一份（SHA-256 去重）
- 可映射成盘符（Windows `subst`）
- P2P 模式让文件在主机间直传，服务器只做认证与发现

## 技术栈

- 服务端与 CLI：Python 3.9+，仅标准库
- 桌面内核：Rust（提供 17 个稳定 C ABI）
- 桌面界面：Flutter

## 仓库

- 源码：https://github.com/wakawakalululu/SelfShare
- 下载：https://github.com/wakawakalululu/SelfShare/releases
- 文档站：https://wakawakalululu.github.io/SelfShare/
- 问题反馈：https://github.com/wakawakalululu/SelfShare/issues
