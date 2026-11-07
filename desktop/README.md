# SelfShare Desktop（Rust Core + Flutter GUI）

桌面客户端采用「Rust 同步内核 + Flutter GUI」分层：

```
Flutter UI / 系统托盘 / 文件夹选择 / 开机自启
                  │ dart:ffi（19 个稳定 C ABI）
                  ▼
Rust Core：扫描、SHA-256、三方合并、冲突副本、watch、HTTP
                  │ 复用既有协议
                  ▼
Python SelfShare Server：blob + SQLite 元数据/版本历史
```

Rust 客户端与 Python CLI 客户端可以连接同一个 vault；已实测 Rust 上传 → Python 拉取、Python 上传 → Rust 拉取均可互通。

## 目录

- `core/`：Rust 同步内核、C ABI、Rust CLI、18 个测试（7 单元 + 11 集成）
- `app/`：Flutter 桌面 GUI、系统托盘、挂载管理、进度、历史恢复
- `scripts/build_windows.ps1`：先构建 Rust DLL，再生成/构建 Flutter Windows 工程
- `../deploy/windows/`：Windows 计划任务 XML 和安装脚本
- `../deploy/systemd/`：服务端 systemd 与 Linux 用户 watch unit

## 构建

### 仅构建并验证 Rust Core

```powershell
cd desktop\core
cargo test
cargo build --release
```

产物：

- `target\release\selfshare_core.dll`：Flutter FFI 动态库
- `target\release\selfshare-cli.exe`：无 GUI 验证工具

### 构建完整 Windows GUI

要求 Flutter 3.19+、Rust stable：

```powershell
powershell -ExecutionPolicy Bypass -File desktop\scripts\build_windows.ps1
```

脚本会执行：

1. `cargo build --release`
2. `flutter create --platforms windows .`（补齐标准 Windows Runner）
3. `flutter pub get`
4. `flutter analyze`
5. `flutter build windows --release`
6. 把 `selfshare_core.dll` 复制到应用目录

实测构建环境：Flutter 3.47.9 stable + VS 2022 BuildTools (MSVC 14.44) + Windows SDK 10.0.22621。

已验证产物：

```text
build\windowsd
unner\Release  selfshare_desktop.exe      1.7 MB
  selfshare_core.dll         2.7 MB
  flutter_windows.dll
  datapp.so                5.7 MB （AOT 快照，含全部 ss_* FFI 调用）
  data\icudtl.dat
```

冒烟结果：进程稳定运行，窗口句柄有效，标题 `SelfShare`，内存约 180 MB、57 线程。

> 若 `flutter build` 报 "No CMAKE_CXX_COMPILER"，说明当前会话缺少 MSVC/SDK 环境变量；
> `build_windows.ps1` 会自动探测 `VC\Tools\MSVC` 与 `Windows Kits\Include` 并注入
> `INCLUDE`/`LIB`/`PATH`，无需手工开 vcvars 窗口。

## GUI 功能

- 添加多个同步文件夹（服务端、vault、token）
- 立即同步 / 预演同步
- 自动 watch、进度轮询、托盘常驻
- 拉取/上传/删除/冲突统计
- 服务端文件数、容量、版本数、修订号
- 版本历史与恢复
- Windows 登录自启开关（计划任务）
- 关闭窗口隐藏到托盘，退出时停止 Rust 后台线程

## Rust C ABI

头文件：`core/include/selfshare_core.h`。所有返回值都是 UTF-8 JSON，必须由 `ss_free` 释放。导出包括：

- 生命周期：`ss_init`、`ss_shutdown`、`ss_version`
- 挂载：`ss_mount`、`ss_unmount`、`ss_mount_info`
- 同步：`ss_sync`、`ss_plan`、`ss_progress`
- watch：`ss_watch_start`、`ss_watch_stop`、`ss_watch_status`
- 历史：`ss_history`、`ss_restore`、`ss_remote_stat`

构建时自动检查 Rust 导出、C 头文件和 Dart lookup 三方名称是否一致。

## 多端策略

- Windows / Linux / macOS：同一 Rust Core；Flutter 仅负责平台 UI。
- Windows：计划任务启动 GUI 到托盘；Rust watch 在线程中运行。
- Linux 桌面：可用 Flutter GUI，也可用 `selfshare-watch@.service` 后台运行。
- 服务器：继续使用 Python 服务端 + systemd，不需要 Flutter。
- 手机端后续可让 Flutter 直接复用同一套 Rust C ABI（Android JNI/iOS dylib），但移动端的后台文件访问受系统沙盒限制，需要单独实现 SAF / File Provider。

## 已知边界

- 当前 Rust Core 默认 HTTP；`--features tls` 会启用 rustls，但构建机需有 C 工具链（ring/cc）。生产公网部署建议在 Nginx/Caddy 后启用 HTTPS。
- 本地 base 快照使用原子 JSON，而不是 SQLite，避免 GUI 客户端引入 C 依赖；适合几万文件规模。
- GUI 当前一次管理一个活动 watch；切换挂载点时停止旧 watch、启动新 watch。计划任务 CLI 模式可为不同目录建多个任务。

## Windows 开机自启

### A. GUI 托盘模式（推荐）

GUI 内「设置 → 登录 Windows 时启动」会直接创建 `\SelfShare\GUI` 计划任务。

也可命令行安装（适合打包/运维）：

```powershell
powershell -ExecutionPolicy Bypass -File deploy\windows\install-autostart.ps1 `
  -GuiExe "C:\Program Files\SelfShare\selfshare_desktop.exe" -Force
```

任务特性：当前用户登录后延迟 10 秒、以普通权限运行、重复启动时忽略新实例、失败后每分钟重试（最多 3 次）、程序以 `--minimized` 隐藏到托盘。

验证：

```powershell
schtasks /Query /TN "\SelfShare\GUI" /V /FO LIST
schtasks /Run   /TN "\SelfShare\GUI"
```

卸载：

```powershell
schtasks /Delete /TN "\SelfShare\GUI" /F
```

### B. 纯 CLI watch 模式

适合还没构建 GUI、或希望每个目录独立守护：

```powershell
powershell -ExecutionPolicy Bypass -File deploy\windows\install-autostart.ps1 `
  -SyncFolder "D:\同步盘" `
  -PythonwExe "C:\Python312\pythonw.exe" `
  -SelfSharePy "C:\SelfShare\selfshare.py" -Force
```

它注册 `\SelfShare\Watch`，执行：

```text
pythonw.exe selfshare.py watch "D:\同步盘" --interval 5 --debounce 2 --full-interval 120
```

不用 `python.exe`，因此登录时不会弹黑色命令行窗口。

> 不建议用“系统启动时 + SYSTEM”运行客户端 watch：用户目录、映射盘和 DPAPI 凭据在 SYSTEM 会话中往往不可见。客户端应在用户登录时启动；服务端才使用 systemd/Windows Service 这种系统级启动。

## 服务端 systemd

文件：

- `deploy/systemd/selfshare-server.service`
- `deploy/systemd/server.env.example`
- `deploy/systemd/install-server.sh`

安装：

```bash
sudo bash deploy/systemd/install-server.sh /path/to/SelfShare
```

脚本会：

1. 创建不可登录的 `selfshare` 系统用户
2. 程序安装到 `/opt/selfshare`
3. 数据目录建立在 `/var/lib/selfshare`
4. 环境文件建立在 `/etc/selfshare/server.env`
5. 安装、启用并立即启动 `selfshare-server.service`

修改监听配置：

```bash
sudoedit /etc/selfshare/server.env
sudo systemctl restart selfshare-server
```

管理和日志：

```bash
systemctl status selfshare-server
journalctl -u selfshare-server -f
sudo systemctl restart selfshare-server
sudo systemctl disable --now selfshare-server
```

新建 vault：

```bash
sudo -u selfshare /usr/bin/python3 /opt/selfshare/selfshare.py \
  vault create work --root /var/lib/selfshare
```

服务单元启用了 `ProtectSystem=strict`、`ProtectHome=true`、`NoNewPrivileges=true`、`PrivateTmp=true`，并只允许写 `/var/lib/selfshare`。

## Linux 用户级 watch

```bash
mkdir -p ~/.config/systemd/user ~/.config/selfshare
cp deploy/systemd/selfshare-watch@.service ~/.config/systemd/user/
cp deploy/systemd/watch.env.example ~/.config/selfshare/work.env
$EDITOR ~/.config/selfshare/work.env
systemctl --user daemon-reload
systemctl --user enable --now selfshare-watch@work
journalctl --user -u selfshare-watch@work -f
```
