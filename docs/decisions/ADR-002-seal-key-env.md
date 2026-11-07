# ADR-002 · `SELFSHARE_SEAL_KEY` 保持 Go 端单侧读取，跨实现混跑禁止设置

- 状态：已接受（2026-11-08，项目所有者拍板，原 `OPEN-DECISIONS.md` O-4）
- 关联：C6 安全与配对契约；`docs/decisions/OPEN-DECISIONS.md`；`v2/README.md` 服务端配置

## 背景

Go 服务端 `internal/store/registry.go::sealKey` 读取 `SELFSHARE_SEAL_KEY` 作为
`token_sealed` 的解封密钥（缺省落盘一把随机密钥）；Python v1 端从不读环境变量，
密封行为两端不对称。部署文档（`v2/README.md`、`v2/server/Dockerfile`、
`v2/server/docker-compose.yml`）曾写「不读 `SELFSHARE_*`」，2026-11-08 已改为
「唯一例外 `SELFSHARE_SEAL_KEY`」并加混跑警示，与实现一致。

## 决策

维持现状（原 O-4 选项 3）：

1. 不移除 Go 端读取，也不在 Python 端补齐同一语义；
2. 部署文档保持「唯一例外 + 跨实现混跑勿设置」警示；
3. 未设置该变量时，两端各自落盘随机密钥，配对走单机模式，行为不受影响。

## 理由

- 选项 1 / 2 都要动配对密封路径，属 C6 安全契约变更，须走 D 轨道并过 L4 兼容套件，
  收益（容器内固定密钥）当前没有真实需求支撑；
- 显式设置会让两端解封密钥不同、配对兑换跨实现失败，文档警示已消除误用面。

## 后果与复核条件

- 任何部署**不要**设置 `SELFSHARE_SEAL_KEY`；若未来确实需要容器内固定密钥，
  重新评估原 O-4 选项 2（两端同语义），届时走 D 轨道 + L4 兼容套件后再改。
