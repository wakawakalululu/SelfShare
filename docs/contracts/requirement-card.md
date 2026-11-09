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
