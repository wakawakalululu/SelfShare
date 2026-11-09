# C1 增量需求卡 · 待发布批次（安全加固 + v2 流水线 + 专家团落地）

- 基线：`master` @ `974c257`（协议版本 `ServiceVersion = "1.0"`，不变）
- 轨道：**B 迭代维护**（主）+ **D 兼容与协议专项**（路径校验基线对齐）+ **E 发布与文档专项**（Release/CI/口径）+ **F 轻量局部**（专家团配置）
- 最小阵容：产品经理 / 协议架构师 / 同步内核 / 测试 / 发布运维 / 安全审计（客户端工程师本轮不上场：`desktop/app/`、`v2/client/src/` 零改动）
- 契约判定：**C2 / C3 / C4 / C5 不变**；**C6 收紧**（Python 客户端新增路径拒绝面）；C1 由本卡建立

---

## 1. 目标（可验收）

| # | 目标 | 验收命令 |
| --- | --- | --- |
| G-1 | v1 Python 客户端拒绝绝对路径 / 盘符段，与 Rust、Go 基线对齐，杜绝 vault 外读写 | `python tests/test_sync.py -v`（含 `test_abs_path_cannot_escape_vault`） |
| G-2 | v2 的 Go 服务端与 Tauri 客户端进入根流水线门禁 | `ci.yml` / `ci-v2.yml` 对应 job 全绿 |
| G-3 | 打 `vX.Y.Z` 标签可产出并发布 v2 客户端安装包与五平台服务端二进制 | `release.yml` 实跑，资产数 = 8 |
| G-4 | 仓库内 AI 协作规范与专家团可被后续任务直接启用 | `AGENTS.md`、`软件开发专家团/SKILL.md` 可读且互相引用 |

## 2. 明确不做

- 不改 `/api/*` 路由、错误码、`ServiceVersion`、磁盘布局（`server.json` / `vault.db` / `blobs/aa/<sha256>` / `paircodes.json` / `peers.json`）。
- 不动三方合并 8 情形语义与冲突副本命名。
- 不改 `desktop/app/`（Flutter）与 `v2/client/src/`（Svelte）业务代码。
- 不实现公网穿透、分块增量传输；2 GiB 单文件上限维持。
- 不修改 Go 端校验实现（差异登记见 `docs/decisions/OPEN-DECISIONS.md`，另立任务）。

## 3. 用户可见变化

- CLI/客户端：`abs_path` 对 `C:/x`、`C:rel`、`D:/y` 抛 `ValueError`，错误信息含相对路径要求；正常相对路径行为不变。
- 发布页：新增 `SelfShare_<ver>_x64-setup.exe` 安装包；服务端二进制仍是 5 平台。
- 文档：`README.md` / `CONTRIBUTING.md` / `v2/README.md` 的测试数与资产数口径已统一（8 个资产，历史 `v2.0.0` 为 7 个）；G-3 已由 `release.yml` 演练 run `42424638532` 验收（8 资产真实发布并全部下载校验）。

## 4. 受影响实现与文件

| 层 | 文件 | 变更性质 |
| --- | --- | --- |
| Python v1 | `selfshare/util.py`、`tests/test_sync.py` | 收紧校验 + 新增用例 |
| Rust core | — | 无改动（作为对齐基线被引用） |
| Go v2 | `v2/server/Dockerfile` | 仅构建方式（多架构交叉编译），无业务代码 |
| CI/CD | `.github/workflows/{ci,ci-v2,release,build-test-deploy}.yml`、`v2/scripts/check.sh` | 门禁与发布编排 |
| 文档 | `README.md`、`CONTRIBUTING.md`、`CHANGELOG.md`、`v2/README.md`、`docs/_config.yml` | 口径与站点排除 |
| 协作规范 | `AGENTS.md`、`agent.md`、`软件开发专家团/**`、`docs/decisions/**` | 新增 |

## 5. 契约豁免说明

C2–C5 豁免理由：本批次无路由、错误码、磁盘布局、合并语义、C ABI/IPC 变更；`git diff --stat` 中无 `.go`（除 Dockerfile）、无 `.rs`、无 `selfshare/store.py` / `selfshare/sync.py` / `v2/server/internal/**`。
C6 不豁免：新增的拒绝面必须固化进安全契约，否则三端口径会再次分叉。

## 6. 已知产品边界是否变化

否。P2P 仅局域网、单文件 2 GiB、无分块增量、单机 SQLite、不保留 ACL/符号链接/空目录，全部维持，README 限制说明保持可见。

## 7. 交付单元（详见内部计划 `软件开发专家团/memory/2026-11-08-plan.md`）

| 单元 | 内容 | 建议提交信息 |
| --- | --- | --- |
| W1 | 路径校验加固 + 用例 | `fix(v1): reject absolute and drive-letter paths before join` |
| W2 | v2 流水线门禁 + 本地检查脚本 | `ci(v2): gate go server and tauri client in root workflows` |
| W3 | 发布资产与多架构镜像 | `build(release): publish v2 installer and multi-arch image` |
| W4 | 规范、专家团与口径对齐 | `docs(repo): land AGENTS.md, expert team and baseline numbers` |

## 8. 后续批次 W6 契约归属（2026-11-08 检修）

| 待办 | 契约面 | 归属 |
| --- | --- | --- |
| C ABI 返回 JSON 形状统一（3 个裸 JSON、`ss_probe` 双层 `ok`、NUL 错误分支缺 `ok`） | **C5 ABI 契约** | **D 轨道已判定（2026-11-08）：冻结现状，禁止就地统一**。见 `docs/contracts/abi-ipc.md` C5-2/C5-3/C5-5 与 `OPEN-DECISIONS.md` O-5；演进只能「新增 ABI + 旧 ABI 并存」 |
| Dart bridge 补 `ss_find_mount` 绑定（头文件与 `ffi.rs` 已有，bridge 仅 18 个 lookup） | C5 ABI 下游 | 可平滑，另立单元待排期（`abi-ipc.md` C5-6） |
| `ss_pair` 首次同步失败不复位 `PROGRESS` | `ffi.rs` 返回内容 | **已闭合**：`b8b0895` 仅复位内部 `PROGRESS`，返回形状不变；本团 G0 放行 |
| Tauri `save_settings` 改用 `util::atomic_write`；`persist()` 错误传播 | 不改 IPC 签名 / 布局，属 §5.3 合规修复 | **已闭合**：`c37501d`；`ci.yml` `v2-client` 实证 `engine_state` 6 passed（run `42474993786`） |
| Rust/Go 集成测试补齐（containment、`head_rev` 单调、删除撞编辑两向） | 纯测试 | **已闭合**：`6b611c9` 补 containment / `head_rev` / `versions`；删除撞编辑两向独立断言由 Rust 集成 + Go store 双层实跑闭合（run `42556170295` / `42556170181`） |
| HTTPS 自签 + `/api/pair` 冒烟补 CI；`release.yml` dispatch 加 tag 存在性断言 | CI / 发布编排 | **已闭合**：`5f38c06`；HTTPS 冒烟由 `42474993754` 实证，tag 断言由 `42475819429` 负向演练实证 |
| NSIS 真实安装 + GUI 窗口冒烟 | 需隔离环境 | 暂缓，不得改本机环境 |

**本团 G0 判定**：触及 C ABI / 返回形状 / Dart bridge 的改动一律停在本团 G0，移交 D 轨道；本团只保留 CI / 产物 / 验证 / 分析四段。**收盘（2026-11-08）**：D 轨道 G0/G1 已完成契约先行（C5 落盘 + O-5 登记），本团非契约项已全部由 CI 实证；删除撞编辑两向断言已由 Rust 集成 + Go store 双层实跑闭合（run `42556170295` / `42556170181`）；下一轮仅剩 `ss_find_mount` 补绑定、NSIS 隔离环境冒烟。

## 9. D 轨道契约先行闭环（2026-11-09，`LOOP-20261109-05`）

用户启用 `selfshare-dev-team` 后，此前多轮移交的 D 轨道路径语义项按「影响面 → 契约对齐 → 三端测试 → 兼容套件」推进：

| 项 | 裁决 | 落盘 |
| --- | --- | --- |
| D1 三端 `norm_rel` trim 不一致（Rust 不 trim） | **实施收敛**：只给 Rust 补 trim，对齐已发布 Python/Go 服务端 | `docs/contracts/storage-layout.md` C3-1、`docs/decisions/OPEN-DECISIONS.md` O-6 |
| D2 Windows 盘符 containment 差异 | **冻结现状**（Go `AbsPath` 生产零调用、Python 已加固、POSIX 三端一致），按 OS 分支升格为契约 | `docs/contracts/security-contract.md` C6-2、O-6 |
| D6 删除 TOCTOU / D7 IPC 吞错误 / O-5 C ABI 形状 | 维持排除（分别属 C4 八情形 / C5 IPC / 已冻结的不可兼容变更） | O-5、O-6 |

限制披露（首尾空白文件名不受支持、已发布便携包 DLL 仍是旧语义）见 C3 §4。验证以 `LOOP-20261109-05` 的 G3 卡为准。

## 10. 2026-11-09 全授权决策收口（`LOOP-20261109-06`）

| 项 | 裁决 | 不做 |
| --- | --- | --- |
| O-1 | 已裁决：保持现状 + 文档声明（服务端只按 `rel` 存键，C6-2 / C3 §3） | 不在 `NormRel` 层收紧、不拒绝历史库路径 |
| O-2 | 已裁决：P2P 保持默认关闭；默认关闭 / 设置开关 / README 局域网限制已符合，仅裁决口径；「首次进入一次性提示」未实现，另立轻量 UI 单元 | 不改「跟随服务端能力自动开启」、本轮不改前端代码 |
| O-3 | 已裁决：不改 C4 语义，短期给 >512 MiB 进度提示（下一轮排期） | 不实现分块增量；2 GiB 上限与整体重传仍是已知限制 |
| O-5 | 维持冻结：就地统一 C ABI 形状属不可兼容 v2 变更（C5-5） | 不改 19 个 ABI 形状 / `ServiceVersion` / 便携包内 DLL；授权不覆盖破协议红线 |
| O-6 / D2 | 维持冻结：本轮只做存量库只读扫描与契约记录（本机 `*.db` 数量 0，扫描须在部署环境执行） | 不统一盘符语义、不改三端 `norm_rel` 实现、不收紧 Go `NormRel` |
| D6 / D7 | **启动 D 轨道契约专项 G0/G1**（详见 `loop-LOOP-20261109-07/00-task.md`）：D6 经评估为 **P0 逻辑丢数据**（`del` 缺 `base_hash` 跳过乐观并发）、D7 为 P1 UI 假成功 | 本轮不改实现；实现排下一轮首位，须两端同步 + L4 硬门槛 |
| GUI 调用点 | 客户端工程师评估：`ss_find_mount` 无自然 GUI 业务调用点，硬接线属臆造需求 | 不新增业务入口；仅「桥接层 `flutter test` 冒烟」排下一轮 |

本节只登记裁决与边界，不新增 ADR 文件、不改代码、不改 C2–C6 契约条款正文；`PROJECT_STATUS.md` 无对应未闭环 R*/P* 项（R1–R12 已闭环、R13 为持续披露边界），故不改状态文件。
