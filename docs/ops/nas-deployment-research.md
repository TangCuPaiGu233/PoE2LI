# NAS 部署方案调研报告

> 项目时间：第 35 天  
> 执行人：哨兵（运维）  
> 状态：调研完成，待实际部署验证

## 1. 目标机器概览

| 项目 | 值 |
|------|------|
| 设备型号 | Synology NAS（群晖） |
| IP | 192.168.110.26 |
| SSH 端口 | 2212 |
| SSH 用户 | skc |
| Docker 路径 | /usr/local/bin/docker |
| 项目根目录 | /volume1/docker/PoE2LI |
| 存储池 | /volume1 |

## 2. 资源限制

- **PATH 限制**：skc 用户的 PATH 不包含 `/usr/local/bin`，Docker 命令必须使用完整路径，或在脚本中显式 `export PATH="/usr/local/bin:$PATH"`。
- **Crontab 限制**：NAS 的 crontab 不可用，定时任务需用轮询守护进程替代。
- **重启恢复**：容器需配置 `restart: unless-stopped`，否则 NAS 重启后不会自动恢复。
- **磁盘清理**：磁盘不足时使用 `/usr/local/bin/docker image prune -a` 清理旧镜像。

## 3. 存储挂载

- NAS 使用 `/volume1` 作为主存储池。
- 项目持久化数据建议挂在 `/volume1/docker/PoE2LI/data`（已映射到容器内 `/app/data`）。
- PostgreSQL/Redis 数据卷由 Docker 管理，宿主机路径在 NAS Docker 卷目录下。

## 4. 网络拓扑

```
内网 (192.168.110.0/24)
├── NAS (192.168.110.26:2212 SSH, :3000 frontend, :8000 backend)
│   └── 代理出口: 192.168.110.26:7890
└── 腾讯云 (159.75.231.110:22)
```

- NAS 对外暴露前端 3000、后端 8000。
- 后端容器通过 NAS 宿主机代理 (192.168.110.26:7890) 访问外网 LLM API。
- 腾讯云为独立生产环境，无公网代理依赖。

## 5. 已知风险

| 风险 | 等级 | 缓解措施 |
|------|------|----------|
| SSH 密码硬编码在脚本中 | 高 | 优先迁移到 SSH key；需确认 NAS 是否支持 key auth |
| 单点 NAS | 高 | 腾讯云作为灾备/生产分流 |
| 磁盘 IO 瓶颈 | 中 | 监控磁盘使用，设置告警阈值 85% |
| 宿主机代理单点 | 中 | NO_PROXY 已配置关键域名直连 |

## 6. 结论

NAS 环境适合作为 dev/staging 和团队内网访问入口。生产环境建议走腾讯云独立部署，避免单点故障。当前 docker-compose.yml 需加固为 production-ready 后，再执行首次部署验证。

## 7. SSH Key 调研说明

- 目标：确认 Synology DSM 是否支持 `ssh-copy-id` 或等效的 key 导入方式。
- 当前状态：尚未实测。
- 若支持：应替换密码登录为 key auth，并移除脚本中的硬编码密码。
- 若不支持：需在报告中明确限制，并寻找替代方案（如 VPN/跳板机）。

## 8. TODO

- [ ] Sprint 3：反向代理/TLS 方案（traefik/nginx + Let's Encrypt）
- [ ] 实测 NAS SSH key auth 可行性
