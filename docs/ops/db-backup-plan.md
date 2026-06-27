# PoE2LI 数据库备份方案

> 时间：项目时间第 2 天 08:32  
> 负责：行舟（ops_engineer）  
> 状态：待朝露 review

---

## 1. 目标
- 防止 PostgreSQL 数据（含 pgvector 向量库）因磁盘故障、误删除、容器损坏而丢失
- 建立可验证的恢复流程
- 对 NAS 和腾讯云均适用

## 2. 当前现状
- 数据库：PostgreSQL 15 + pgvector，Docker Compose 编排
- 持久化：`pgdata` Docker volume（NAS 宿主机路径 `/volume1/docker/PoE2LI/data` 仅挂载 backend 数据）
- 当前仅有一次性同步能力：`deploy_tencent.py` 中 `SYNC_NAS_DATA=1` 可做 `pg_dump` → `pg_restore`
- 无定时备份、无自动清理、无恢复演练

## 3. 备份策略

### 3.1 全量备份（主策略）
- **频率**：每日 02:00（NAS 本地时间）
- **工具**：`pg_dump -Fc`（自定义格式，支持压缩与并行恢复）
- **保留周期**：
  - 最近 7 天：每日备份
  - 最近 4 周：每周一备份
  - 最近 6 个月：每月 1 日备份
- **存储位置**：
  - 主备份：NAS 宿主机目录 `/volume1/docker/PoE2LI/data/backups/`（Docker bind mount 到容器内 `/app/data/backups`）
  - 异地备份：每周一自动复制一份到腾讯云 `/opt/PoE2LI/data/backups/`（通过 `deploy_tencent.py` 扩展或 rsync）

### 3.2 增量/WAL 归档方案可行性评估
- **可行性**：技术上可行，但复杂度较高
- **建议**：Phase 1 先落地全量备份 + 保留策略，满足当前需求
- **Phase 2 可选升级**：启用 `archive_mode = on` + `archive_command` 将 WAL 归档到对象存储，实现 PITR（Point-in-Time Recovery）
- **评估结论**：当前数据量（~22K chunks + trade stats + 游戏数据）全量备份约 100-300MB，全量备份足够，暂不需要 WAL 归档

### 3.3 备份存储位置对比

| 方案 | 优点 | 缺点 | 适用性 |
|------|------|------|--------|
| 本地磁盘（NAS） | 简单、快速、免费 | 单点故障 | ✅ 主备份 |
| NAS → 腾讯云 rsync | 异地容灾 | 需要网络打通 | ✅ 周备份 |
| S3 / 云对象存储 | 高可靠、版本控制 | 需要额外配置、成本 | ⏸ Phase 2 |

**当前推荐**：本地磁盘为主 + 每周复制到腾讯云

## 4. 备份脚本

### 4.1 脚本位置
`scripts/ops/backup_db.sh`

### 4.2 功能特性
- 兼容 NAS / 腾讯云 Docker Compose 环境
- 自动检测 `docker` 路径（NAS 特殊处理 `/usr/local/bin/docker`）
- 使用 `pg_dump -Fc` 自定义格式（支持压缩、并行恢复）
- 备份后自动清理过期文件（保留周期可配置）
- 包含完整性检查（文件大小校验）
- 输出备份清单

### 4.3 定时任务配置

**NAS crontab（推荐）**：
```bash
# 每日 02:00 执行备份
0 2 * * * /volume1/docker/PoE2LI/scripts/ops/backup_db.sh >> /volume1/docker/PoE2LI/data/backup.log 2>&1

# 每周一 03:00 执行异地复制到腾讯云
0 3 * * 1 /volume1/docker/PoE2LI/scripts/ops/backup_db.sh && rsync -avz /volume1/docker/PoE2LI/data/backups/ root@159.75.231.110:/opt/PoE2LI/data/backups/
```

**腾讯云 crontab（如适用）**：
```bash
# 每日 02:00 执行备份（prod 环境）
0 2 * * * /opt/PoE2LI/scripts/ops/backup_db.sh >> /opt/PoE2LI/data/backup.log 2>&1
```

## 5. 恢复演练步骤

### 5.1 快速恢复验证（推荐每月一次）
```bash
# 1. 创建测试数据库
docker compose -f docker-compose.yml exec -T postgres \
  createdb -U poe2li poe2li_restore_test

# 2. 恢复备份
docker compose -f docker-compose.yml exec -T postgres \
  pg_restore -U poe2li -d poe2li_restore_test --clean --if-exists /path/to/backup.dump

# 3. 校验数据
docker compose -f docker-compose.yml exec -T postgres \
  psql -U poe2li -d poe2li_restore_test -c "SELECT count(*) FROM knowledge_chunks;"

# 4. 清理测试库
docker compose -f docker-compose.yml exec -T postgres \
  dropdb -U poe2li poe2li_restore_test
```

### 5.2 完整恢复流程
```bash
# 1. 停止 backend / celery
docker compose -f docker-compose.yml stop backend celery_worker celery_beat

# 2. 备份当前数据库（安全起见）
./scripts/ops/backup_db.sh

# 3. 恢复指定备份
docker compose -f docker-compose.yml exec -T postgres \
  pg_restore -U poe2li -d poe2li --clean --if-exists /path/to/backup.dump

# 4. 重启服务
docker compose -f docker-compose.yml up -d backend celery_worker celery_beat

# 5. 健康检查
curl -sf http://127.0.0.1:8000/health
```

### 5.3 演练记录模板
```
演练日期：____
备份文件：____
恢复耗时：____
数据校验：知识库 chunk 数 ____ / 预期 ____
结论：成功 / 失败
备注：____
```

## 6. 备份验证机制

### 6.1 自动验证（脚本内置）
- 备份文件大小校验（< 1KB 报警）
- pg_dump 退出码检查
- 备份文件列表输出

### 6.2 定期恢复演练
- **频率**：每月一次
- **范围**：随机抽取最近 7 天内备份，恢复到测试库
- **校验项**：
  - `knowledge_chunks` 行数
  - `trade_stats` 行数
  - `builds` 表关键字段可读性
  - pgvector 索引有效性：`SELECT count(*) FROM knowledge_chunks WHERE embedding IS NOT NULL;`

### 6.3 告警规则（建议）
- 备份文件 0 字节或缺失 → 立即告警
- 连续 3 天备份失败 → 升级告警
- 恢复演练失败 → 立即升级

## 7. 实施依赖

| 成员 | 配合事项 | 时间 |
|------|---------|------|
| 朝露 | 确认备份目录权限与定时任务策略 | Week 1 |
| 守夜 | 提供数据量估算（pg_dump 文件大小预期） | Week 1 |
| 织墨 | 确认 `deploy_tencent.py` 是否需要扩展 rsync 功能 | Week 1 |

## 8. 风险与缓解

| 风险 | 缓解 |
|------|------|
| NAS 磁盘满 | 保留策略 + 自动清理 + 监控磁盘使用率 |
| 备份文件损坏 | 定期恢复演练 + 多版本保留 |
| 备份时数据库写入 | `pg_dump` 在线备份，无需停机；大库可考虑 `pg_dump --jobs=4` |
| 腾讯云网络不通 | rsync 失败不影响本地备份；记录失败日志并告警 |

## 9. Week 1 交付物
1. `scripts/ops/backup_db.sh` ✅ 已实现
2. `docs/ops/db-backup-plan.md` ✅ 本文档
3. NAS crontab 配置（待朝露确认后执行）
4. 第一次手动备份 + 恢复验证（待守夜提供数据量参考）
