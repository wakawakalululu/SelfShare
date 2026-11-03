# 贡献指南

## 开发环境

- Python 3.9+（服务端与 CLI，无第三方依赖）
- Rust stable（桌面内核）
- Flutter 3.19+（桌面界面，可选）

## 本地验证

提交前请跑完整回归：

```bash
# Python
python -m compileall -q selfshare tests
python tests/test_sync.py
python tests/test_p2p.py

# Rust
cd desktop/core
cargo build --release
cargo test --release

# Flutter（如改动 GUI）
cd desktop/app
flutter analyze
flutter build windows --release
```

## 代码约定

- Python 只用标准库，不引入第三方包
- 所有文件写入走 `atomic_write`，避免中断产生半截文件
- 路径必须经 `norm_rel` 规范化，拒绝 `..`
- 冲突处理遵循「保留双方」原则，不得静默覆盖
- 新增 C ABI 时同步更新 `desktop/core/include/selfshare_core.h` 与 `desktop/app/lib/rust_bridge.dart`

## 提交信息

采用 `type(scope): summary` 形式：

```text
feat(p2p): peer registration and discovery
fix(sync): remote delete no longer overwrites local edit
docs(wiki): add FAQ
```

## 测试要求

改动同步逻辑必须补测试，且要覆盖：

- 正常路径
- 冲突路径（双方都改）
- 删除与编辑相撞
- 节点不可达时的回退

## 分支与发布

- 主分支 `master`
- 版本标签 `vX.Y.Z`
- 打标签后 `release.yml` 自动构建 Windows 便携包并创建 Release

## 报告问题

请附上：

```bash
selfshare --version
selfshare doctor <同步目录>
```

以及复现步骤、操作系统、是否启用 `--p2p`。**不要粘贴令牌。**
