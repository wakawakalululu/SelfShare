# Runbook：真实部署环境 vault.db 只读扫描采集（O-1 / O-6 立项依据）

> 目的：从**真实部署环境**采集 `vault.db` 的 rel 键健康数据（whitespace / drive_letter / null
> 三类异常），为 OPEN-DECISIONS O-1（服务端是否拒盘符段）与 O-6（盘符语义统一）的裁决提供
> 实证。工具与判类口径见 `desktop/scripts/scan_vault_db.py`（`LOOP-20261122-02` 落地）。

## 1. 采集步骤（在部署机上执行）

```bash
# ① 定位 vault.db（默认与 server.json 同目录；Docker 部署在挂载的数据目录内）
# ② 只读扫描（mode=ro；被运行中的服务端持有的线上库加 --immutable）
python3 desktop/scripts/scan_vault_db.py --immutable --json /path/to/vault.db > scan-result-$(hostname)-$(date +%F).json
# 退出码：0=clean / 1=发现异常 / 2=schema 不符（旧版本库结构，请附上完整输出反馈）
```

## 2. `--json` 汇总格式（机器可读，便于跨部署汇总）

```json
{
  "tables": {
    "files":    {"rows": 0, "whitespace": 0, "drive_letter": 0, "null": 0},
    "versions": {"rows": 0, "whitespace": 0, "drive_letter": 0, "null": 0}
  },
  "conclusion": {"clean": true, "counts": {"whitespace": 0, "drive_letter": 0, "null": 0}}
}
```

汇总时**只收集上述计数字段**（不收集 rel 原文——见 §3 脱敏）。

## 3. 脱敏要求（提交/共享前必做）

- 只保留 JSON 的**计数与结论**字段，不要附带任何 `rel` 原文、主机名、令牌、路径中的
  用户名或业务目录名；
- 如需报告异常样例，请把 `rel` 中的业务片段替换为 `<redacted>`，只保留异常**形态**
  （如 `"  C:/<redacted>"` 前导空白 + 盘符段）；
- 不要把 `vault.db` 本体、`server.json`、令牌或配对码附在工单里（红线：AGENTS §5.4）。

## 4. 采集模板（提交到 O-1/O-6 决策记录时使用）

```
部署形态：Docker / systemd / 裸进程（选一）
服务端版本：vX.Y.Z
库规模：files <N> 行 / versions <N> 行
结论：<clean | whitespace=N | drive_letter=N | null=N>
附注：<如有异常样例，脱敏后形态描述>
```

## 5. 与决策的联动

- 数据累计到一定规模后回填 `docs/decisions/OPEN-DECISIONS.md` O-1 / O-6 的「现状」小节；
- 全部 clean → 维持冻结不动；发现盘符段/空白异常 → 触发 O-1/O-6 裁决流程（走 D 轨道 +
  三端同步 + L3/L4 实证，见 `PROJECT_STATUS.md` §0.3 说明）。
