# NAS Docker 服务清单

> **重要：所有 AI 助手请注意**
> 本文档记录了 NAS (192.168.110.26) 上所有已部署的 Docker 容器。
> **请勿为已有服务创建重复容器。** 如需新增服务，请先更新本文档。

## NAS 连接信息

- 地址: `192.168.110.26`
- SSH 端口: `2212`
- 用户: `skc`
- Docker 路径: `/usr/local/bin/docker`（不在默认 PATH 中）
- 项目目录: `/volume1/docker/`

---

## 服务总览

| 服务 | 目录 | 容器数 | 状态 | 端口映射 | 用途 |
|------|------|--------|------|----------|------|
| **PoE2LI** | `/volume1/docker/PoE2LI` | 5 | 运行中 | 3000, 5433, 6379, 8000 | 流放漓主项目 |
| **mihomo** | `/volume1/docker/mihomo` | 1 | 运行中 | (内部代理) | 网络代理 (Clash Meta) |
| **openclaw** | `/volume1/docker/openclaw` | 1 | 运行中 | 18789-18790 | 自托管 AI Agent 平台 |
| **svn-server** | — | 1 | 运行中 | 3690 | SVN 版本控制 |
| **clash** | `/volume1/docker/clash` | 0 | 已停用 | — | 旧版代理（已被 mihomo 替代） |

---

## 1. PoE2LI — 流放漓智能工具站

**管理者**: QoderWork AI  
**部署方式**: `docker compose up -d --build`  
**Git 仓库**: `https://github.com/TangCuPaiGu233/PoE2LI.git`

### 容器列表

| 容器名 | 镜像 | 端口 | 说明 |
|--------|------|------|------|
| `poe2li-backend` | poe2li-backend | 8000 | FastAPI 后端 API |
| `poe2li-celery-worker` | poe2li-celery_worker | — | Celery 异步任务 Worker |
| `poe2li-frontend` | poe2li-frontend | 3000 | Next.js 前端 |
| `poe2li-postgres` | pgvector/pgvector:pg15 | **5433**:5432 | PostgreSQL + pgvector |
| `poe2li-redis` | redis:7-alpine | 6379 | Redis (缓存 + 消息队列) |

### 数据卷

| 卷名 | 用途 |
|------|------|
| `poe2li_pgdata` | PostgreSQL 数据持久化 |
| `poe2li_redisdata` | Redis 数据持久化 |
| `./data` (bind mount) | SQLite 备份 / 文件数据 |

### 关键注意事项

- PostgreSQL **外部端口为 5433**（5432 被 NAS 系统 PostgreSQL 占用）
- Embedding 使用 SiliconFlow BGE-M3 API（非本地模型，NAS 硬件不支持 GPU）
- 需要配置 `NO_PROXY=api.siliconflow.cn,localhost,127.0.0.1` 绕过代理
- `.env` 文件需包含: `ANTHROPIC_AUTH_TOKEN`, `SILICONFLOW_API_KEY`

---

## 2. mihomo — 网络代理

**管理者**: 手动配置  
**用途**: Clash Meta 内核代理，为 NAS 提供科学上网能力

| 容器名 | 镜像 | 说明 |
|--------|------|------|
| `mihomo` | metacubex/mihomo:latest | Clash Meta 代理核心 |

配置文件: `/volume1/docker/mihomo/config.yaml`

---

## 3. openclaw — AI Agent 平台

**管理者**: 其他 AI (Claude Code)  
**用途**: 自托管开源 AI Agent 平台 (Paperclip 替代)

| 容器名 | 镜像 | 端口 | 说明 |
|--------|------|------|------|
| `openclaw-openclaw-gateway-1` | openclaw:local | 18789-18790 | Gateway 网关 |

---

## 4. svn-server — SVN 版本控制

**管理者**: 手动配置  
**用途**: Subversion 服务器

| 容器名 | 镜像 | 端口 | 说明 |
|--------|------|------|------|
| `svn-server` | garethflowers/svn-server | 3690 | SVN 协议端口 |

---

## 5. clash（已停用）

**状态**: 容器已停止，目录保留  
**说明**: 旧版 Clash 代理，已被 mihomo 替代。目录 `/volume1/docker/clash` 可在确认后清理。

---

## 端口占用汇总

| 端口 | 服务 | 协议 |
|------|------|------|
| 3000 | PoE2LI Frontend | HTTP |
| 3690 | SVN Server | SVN |
| 5433 | PoE2LI PostgreSQL | PostgreSQL |
| 6379 | PoE2LI Redis | Redis |
| 7890 | mihomo (HTTP 代理) | HTTP Proxy |
| 8000 | PoE2LI Backend API | HTTP |
| 18789-18790 | OpenClaw Gateway | HTTP |

**新增服务时，请避开以上端口。**

---

*最后更新: 2026-06-07 by QoderWork*
