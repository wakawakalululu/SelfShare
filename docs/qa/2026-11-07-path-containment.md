# 验证记录索引 · 2026-11-07 · v1 路径校验加固

本文件为**简短索引**，不含本机路径、用户名或命令原始输出。按 `AGENTS.md` §7，
过程性验证记录（含命令输出、本机路径）不得放入 `docs/`；权威正文见：

- `.codebuddy/skills/软件开发专家团/memory/2026-11-07-path-containment.md`

`docs/qa/` 由 `docs/_config.yml` 的 `exclude: [qa]` 在站点层剪枝，不随 Pages 公开；
`docs/contracts/` 与 `docs/decisions/` 为公开内容，不受此剪枝影响。
发布级验证结论（可公开）并入 `v2/RELEASE_SUMMARY.md`；相关决策见
`docs/decisions/ADR-001-path-containment.md` 与 `docs/decisions/OPEN-DECISIONS.md`。

## 主题

v1 `selfshare.util.abs_path` 盘符 / 绝对路径逃逸加固（`ADR-001`）及 L1–L7 分层验证记录。
具体命令、原始输出、未验证项与结论，一律以 memory 目录的权威副本为准。
