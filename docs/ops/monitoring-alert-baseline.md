# Monitoring & Alert Baseline — PoE2LI

## 目标
- 容器异常自动告警
- 后端/数据库/Redis 健康异常可感知
- 部署失败可回滚

## 关键告警（建议落地到 Prometheus / Grafana / 腾讯云监控）

### 1. 容器存活
- 规则：`up{container_name=~"poe2li-.*"} == 0`
- 持续：1m
- 级别：P0

### 2. 后端 HTTP 健康检查
- 规则：`probe_success{job="poe2li-backend"} == 0`
- 持续：2m
- 级别：P0

### 3. 数据库连接
- 规则：`pg_up == 0`
- 持续：1m
- 级别：P0

### 4. Redis 连接
- 规则：`redis_up == 0`
- 持续：1m
- 级别：P0

### 5. 前端页面可用
- 规则：HTTP / 或 /chat 连续 3 次非 2xx
- 持续：3m
- 级别：P1

### 6. 磁盘空间（NAS/腾讯云宿主机）
- 规则：`disk_usage_percent > 85`
- 持续：5m
- 级别：P1

## 当前可用工具
- `scripts/nas/monitor.py` — NAS 侧健康检查脚本
- `scripts/tencent/health_check.py` — 腾讯云健康检查脚本
- `deploy_nas.py` / `deploy_tencent.py` — 部署入口，失败会 `sys.exit(1)`

## 下一步
- 接入 Prometheus exporter / Grafana dashboard
- 配置 Webhook 到飞书/钉钉/企业微信
