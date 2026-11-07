# 验证记录 · 2026-11-07 · v1 路径校验加固

按 `AGENTS.md` §6 的 L1–L7 分层记录。所有命令均在 `D:\code\waka\SelfShare` 实跑，
输出为当次终端原始结果摘要。未跑项在文末单列，不推测其结论。

## 0. 变更范围

| 文件 | 改动 |
|---|---|
| `selfshare/util.py` | `abs_path` 增加绝对路径 / 盘符段拒绝 + 拼接后包含性复核（`ADR-001`） |
| `tests/test_sync.py` | 新增 `SyncTestCase.test_abs_path_cannot_escape_vault` |
| `README.md`、`AGENTS.md` | 测试口径 29 → 30（sync 19 → 20） |
| `CHANGELOG.md` | 新增 `[Unreleased]` 章节（安全 + 工程） |
| `docs/decisions/ADR-001-path-containment.md`、`OPEN-DECISIONS.md` | 决策与未决项 |

## 1. L1 · Python 单测（29 → 30 例）

```
$ python tests/test_sync.py -v
Ran 20 tests in 33.822s
OK
```

```
$ python tests/test_p2p.py -v
Ran 5 tests in 11.729s
OK
```

```
$ python tests/test_pairing.py -v
Ran 5 tests in 8.673s
OK
```

合计 30 例通过；`python -m compileall -q selfshare tests` 退出码 0。

## 2. L2 · Rust 内核

```
$ cd desktop/core && cargo test --release
running 7 tests  ... ok. 7 passed
running 11 tests ... ok. 11 passed
```

18 例通过（7 单测 + 11 集成）。

## 3. L3 · Go 服务端

```
$ export PATH="/c/Users/cloud_user/go/bin:$PATH"
$ cd v2/server && go vet ./...        # 0 issue
$ go test -count=1 ./...
ok  selfshare/server/internal/api    3.122s
ok  selfshare/server/internal/store  6.126s
$ go test -count=1 -v ./... | grep -c '^--- PASS'
20
```

Go 1.22.5（`go.mod` 声明 1.24，由 `GOTOOLCHAIN=auto` 处理）；20 例通过。
本轮未跑 `go test -race`（本机无 gcc/cgo），由 CI `v2-server` 作业覆盖。

重新构建并确认版本：

```
$ go build -o bin/selfshare-server-new.exe ./cmd/selfshare-server
$ ./bin/selfshare-server-new.exe --version
selfshare-server 2.0.0
```

## 4. L4 · 跨实现兼容（G3 硬门槛）

用**新构建的 Go 二进制**驱动同一套 Python 用例：

```
$ SELFSHARE_SERVER_BIN=v2/server/bin/selfshare-server-new.exe python tests/test_sync.py
Ran 20 tests in 23.480s
OK

$ SELFSHARE_SERVER_BIN=v2/server/bin/selfshare-server-new.exe python tests/test_p2p.py
Ran 5 tests in 11.883s
OK

$ SELFSHARE_SERVER_BIN=v2/server/bin/selfshare-server-new.exe python tests/test_pairing.py
Ran 5 tests in 6.878s
OK
```

30 例在 Go 服务端下同样通过，含新增的路径逃逸用例 → 修复未破坏协议兼容。

## 5. L5 · 前端与 Tauri

```
$ cd v2/client && npm run build
✓ 42 modules transformed.
dist/index.html                  0.40 kB
dist/assets/index-C96pXIWb.css   8.91 kB
dist/assets/index-4MC8PyFK.js   36.48 kB
✓ built in 2.86s

$ cd src-tauri && cargo check --all-targets
Finished `dev` profile ... in 33.31s

$ cargo test --test engine_state
running 2 tests
test pause_resume_and_tray_state ... ok
test settings_roundtrip ... ok
```

## 6. 缺陷复现与修复对照

修复前（`abs_path` 仅做 `norm_rel` + `os.path.join`）：

| 输入 | 结果 | 判定 |
|---|---|---|
| `C:/Windows/Temp/pwn.txt` | `C:\Windows\Temp\pwn.txt` | 逃逸 |
| `C:relative/inside.txt` | `C:\relative\inside.txt` | 逃逸 |
| `D:/x/y.txt` | `<vault>\x\y.txt` | 同盘被当子路径（行为不一致） |

修复后：

| 输入 | 结果 |
|---|---|
| `C:/Windows/x.txt` | `ValueError: path must stay relative to the vault` |
| `C:rel/x.txt` | 同上 |
| `D:/y.txt` | 同上 |
| `a/b.txt`、`sub/dir/名字.md`、`带空格 的名字.txt`、`a\b\c.txt` | 正常解析到 vault 内 |

端到端：伪造含盘符 `rel` 的清单，canary 文件未被创建（`canary exists: False`）。

## 7. 未验证项（不得视为通过）

| 层 | 项目 | 原因 |
|---|---|---|
| L3 | `go test -race` | 本机无 gcc/cgo；由 `.github/workflows/ci.yml` 的 `v2-server` 覆盖 |
| L7 | Docker 镜像构建与 `/api/ping` 冒烟 | 本机无 Docker 引擎；由 CI 覆盖 |
| L7 | GitHub Actions / Release 流水线 | 需 push 后触发；本轮未推送 |
| L7 | macOS / Linux 实机冒烟 | 本机仅 Windows |
| L6 | Flutter `analyze` + Windows 构建 | 本次未改 `desktop/app/`，未跑 |

## 8. 结论

G0–G4 门禁：G1 契约（`ADR-001` 已落盘）、G2 实现（最小变更，单点收口）、G3 验证（L1/L2/L3/L4/L5 实跑）
均通过。四红线零命中：未改协议与磁盘布局、未丢数据语义、无凭证入库、无构建产物入库。

遗留：`bin/selfshare-server-new.exe` 为本地验证产物，被 `.gitignore` 忽略，不提交。
