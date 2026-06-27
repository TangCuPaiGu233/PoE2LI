# Checkpoint — 数据库备份方案

> 时间：项目时间第 3 天 15:38  
> 执行人：行舟（ops_engineer）  
> 协调人：朝露  
> 状态：Approved ✅（五轴全绿）— 准备 merge

## 沙箱文件清单
- `docs/ops/db-backup-plan.md` — 备份方案文档
- `scripts/ops/backup_db.sh` — 可执行备份脚本
- `docs/ops/checkpoint-db-backup-plan.md` — 本 checkpoint

## 方案摘要
- 全量备份：每日 02:00，pg_dump -Fc，保留 7 天
- 存储：NAS 本地为主，每周复制到腾讯云
- 恢复演练：每月一次，包含数据校验步骤
- 脚本兼容 NAS / 腾讯云 Docker Compose 环境

## 评审结论
- 功能 ✅ 每日全量 pg_dump -Fc + 分层保留 7d/4w/6m + NAS 本地 + 腾讯云异地
- 完整 ✅ 恢复演练步骤详细到命令级别、验证机制（大小/行数/向量索引）、告警规则
- 简洁 ✅ 分段清晰，表格直观，恢复脚本即文档
- 一致 ✅ 符合 docs/ops/ 和 scripts/ops/ 规范
- 安全 ✅ pg_dump 在线备份无需停机，异地容灾降单点风险

## 下一步
1. 等待朝露 review 后 merge main
2. NAS crontab 配置需要实际验证
3. CI/CD Stage 3（Docker build）待织墨 Step 0 合入 main 后实现
