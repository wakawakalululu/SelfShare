# v1.3.0 发布说明

发布日期：2026-11-03

## 重点：从「配置」变成「配对」

之前连接一台新设备需要：建库 → 抄令牌 → 填地址 → 填库名，四步手工操作。现在只需**一串配对码**。

### 服务端零配置起步

```bash
python selfshare.py server
```

首次启动自动创建同步库 `default`，并直接打印：

```text
     地址  : http://192.168.1.10:8484
     配对码: SS-5T8Y-E3FA-THV3
```

### 客户端一条命令

```bash
selfshare pair D:\同步盘 --url http://192.168.1.10:8484 --code SS-5T8Y-E3FA-THV3
```

自动完成：换令牌 → 写配置 → 首次同步。

### 桌面端两个输入框

「连接同步文件夹」对话框从 4 个字段缩减为 **文件夹 + 配对码**，地址栏带「测试连接」按钮即时校验。

## 配对码的安全设计

- **一次性**：兑换成功后立即作废，重复使用返回失败
- **有时效**：默认 30 分钟，最长 24 小时
- **不含令牌**：码本身只是搬运载体，兑换时才下发真实令牌
- **服务端可吊销**：`vault pair-code` 可随时查看未使用的码

令牌现在用服务端本地密钥加密存储（`token_sealed`），以便配对时还原。这是有意的取舍：能防 `grep server.json` 直接读到令牌，但不防服务端被完全攻陷——配对码的一次性与短时效已经压缩了攻击窗口。

## 文档

README 从 210 行精简到 100 行，三步快速开始放在最顶部。

## 新增

- `selfshare pairing` 模块与 5 个端到端测试
- `POST /api/pair`（唯一无需令牌的写接口）
- FFI：`ss_pair`、`ss_probe`
- CI 增加 pairing 测试步骤

## 验证

| 项目 | 结果 |
| --- | --- |
| Python 同步 | 15/15 |
| Python P2P | 3/3 |
| Python 配对 | 5/5 |
| Rust 单元 + 集成 | 6 + 9 |
| flutter analyze | 0 issue |
| Windows GUI 构建与冒烟 | 通过 |
| GitHub Actions | 7/7 全绿 |

# v1.1.0 发布说明

发布日期：2026-11-02

## 本次发布内容

### 1. 跨主机同步（服务端模式）

- 内容寻址存储：按 SHA-256 去重，同一内容只存一份
- 双向同步：三方合并（本地 / base 快照 / 远端），只传变化
- **冲突保留双方**：生成 `name (冲突副本-从 HOST 时间).ext`，任何一方的编辑都不会被覆盖
- 删除语义：不丢数据——远端删除 + 本地改动时保留本地并重新上传
- 全量版本历史，可按文件列出、可恢复任意历史版本
- 令牌加盐哈希存储，比较用常量时间；路径含 `..` 一律拒绝

### 2. P2P 同步（认证在中心，数据在节点）

- 节点向中心服务端注册监听地址与持有的 blob 哈希
- 拉取时优先查在线 peer，用 `HMAC(token, vault:peer:digest:nonce)` 双向认证后直连
- peer 不可达或没有该 blob 时自动回退到中心服务器
- 元数据（manifest / commit / history）始终走中心，保证全局一致
- 节点 TTL 300 秒，心跳 30 秒，下线自动剔除

用法：

```bash
python selfshare.py watch D:\同步盘 --p2p
```

### 3. Rust 同步内核

- 与 Python 服务端协议完全兼容，可与 Python 客户端混合部署
- 稳定 C ABI：17 个 `ss_*` 导出，配套 `selfshare_core.h`
- 提供独立 CLI（`selfshare-cli`）用于无 GUI 验证
- 本地状态用原子 JSON 快照，避免 SQLite 的 C 依赖

### 4. Flutter 桌面 GUI

- 多同步文件夹管理、即时同步与预演
- 实时进度、服务端容量/版本/修订统计
- 自动 watch、系统托盘常驻、关闭隐藏
- 版本历史浏览与一键恢复
- Windows 登录自启开关（计划任务）
- 同步操作在独立 isolate 执行，不阻塞 UI

### 5. 部署

- Windows 计划任务：GUI 托盘模式 + 纯 CLI watch 模式，两份 XML 模板和安装脚本
- 服务端 systemd：专用用户、自动重启、`ProtectSystem=strict` 等加固
- Linux 用户级 `selfshare-watch@.service`

## 验证结果

| 项目 | 结果 |
| --- | --- |
| Python 同步测试 | 15/15 通过 |
| Python P2P 测试 | 3/3 通过 |
| Rust 单元测试 | 6/6 通过 |
| Rust 集成测试（对接真实 Python 服务端） | 6/6 通过 |
| `flutter analyze` | No issues found |
| `flutter build windows --release` | 成功 |
| GUI 冒烟（窗口创建、稳定运行） | 通过，180 MB / 55 线程 |
| Rust P2P 集成测试 | 3/3 通过（HMAC 一致、节点服务、坏 MAC 拒绝） |
| 端到端 P2P 实测 | 通过，客户端输出 `<- peer:127.0.0.1:49376` |

## 已知边界

- P2P 面向局域网直连；公网 NAT 穿透（打洞/中继）尚未实现
- Rust Core 默认 HTTP；公网部署建议在 Nginx/Caddy 终止 TLS
- 单文件上限 2 GiB；改动为整文件传输
- 不保留 Windows ACL、符号链接、空目录
- GUI 当前一次管理一个活动 watch；多目录可分别用 CLI 计划任务

## 升级说明

v1.0.0 是内部首个可用版本（仅 Python 服务端 + CLI）。本版本未改动服务端存储格式和 HTTP 协议，旧数据目录可直接沿用。
