# 流放漓 — 部署与运维

> 详细操作手册。AI 助手读 `CLAUDE.md` 中的概要即可；执行部署/排障时查阅本文。

## 文档索引

| 文档 | 内容 |
|------|------|
| **本文** | NAS + 腾讯云部署、更新、日志、防火墙 |
| [nas-deploy-guide.md](../../nas-deploy-guide.md) | NAS Docker 通用步骤 |
| [NAS-Docker-服务清单.md](../NAS-Docker-服务清单.md) | NAS 上全部容器（勿重复部署） |

## 环境分工

| 环境 | 地址 | 角色 |
|------|------|------|
| **NAS** | `192.168.110.26:2212` | **开发 / 测试 / 数据采集 / 知识库写入（唯一源）** |
| **腾讯云** | `159.75.231.110` | **公网生产** — 只读消费 KB；大版本时从 NAS 同步 |

### 发布流程（NAS → 腾讯云）

```
日常开发 / 功能验证          大版本 / 对外发布
        ↓                            ↓
   NAS 部署 & 测试              腾讯云 deploy
   python deploy_nas.py         python scripts/deploy_tencent.py
```

| 阶段 | 在哪做 | 做什么 |
|------|--------|--------|
| **开发** | NAS | 改代码、跑脚本、灌知识库、调 RAG/交易/Chat |
| **联调测试** | NAS | 内网访问验证；确认通过后再考虑上云 |
| **大版本发布** | 腾讯云 | 合并到发布分支 → `deploy_tencent.py`（**默认不同步库**） |
| **知识库大更新** | NAS 先灌 → 腾讯云 | 发布时设 `SYNC_NAS_DATA=1`，从 NAS `pg_dump` 恢复 |

### 知识库与数据采集（NAS 写入 → 腾讯云只读）

**所有 KB 增长在 NAS 完成；腾讯云一般不跑爬虫/灌库脚本。**

```
poe2db / wiki / PoB / backfill / embedding
              ↓  （NAS 上跑 scripts/、collectors/）
         NAS PostgreSQL（源库）
              ↓  （大版本 + SYNC_NAS_DATA=1）
         腾讯云 PostgreSQL（只读消费，对外 RAG）
```

| 操作 | NAS | 腾讯云 |
|------|-----|--------|
| 爬虫（poe2db、poe2wiki、caimogu 等） | ✅ | ❌ 不跑 |
| 入库 / embedding / backfill_links / KG | ✅ | ❌ 不跑 |
| RAG 问答验证新数据 | ✅ 先测 | 发布后再验 |
| 同步到生产 | — | `SYNC_NAS_DATA=1` 随大版本推送 |

**原则**

- 原始数据与脚本产物在 NAS：`/volume1/docker/PoE2LI/data/`（容器内 `/app/data`）。
- 腾讯云 2C2G、无内网代理，不适合长时间爬取；Compliance 上官方 API 也应在 NAS 统一走缓存层再入库。
- 腾讯云上的 `knowledge_chunks` 等表**只服务线上查询**，不在上面做 ingest 迭代。
- KB 有增量：NAS 灌完并验证检索质量 → 下一次大版本发布带 `SYNC_NAS_DATA=1`；不要为少量 chunk 单独上云灌库。

**NAS 常见灌库命令**（在 `poe2li-backend` 容器或 NAS 路径下执行，详见各 `backend/scripts/`）：

```bash
# 示例：wiki 爬取、link 回填、向量补全 — 均在 NAS 跑
/usr/local/bin/docker exec poe2li-backend python3 /app/scripts/crawl_poe2wiki.py
/usr/local/bin/docker exec poe2li-backend python3 /app/scripts/backfill_links.py
```

**原则**（代码与功能）

- 新功能、Bug 修复、Prompt 调优：**只在 NAS 迭代**，不要直接改生产。
- 腾讯云更新时机：功能在 NAS 测稳、准备对外时（大版本 / 里程碑）。
- 日常 `deploy_tencent.py` **不要**带 `SYNC_NAS_DATA=1`（避免覆盖生产用户数据）；仅 KB/Schema 有大变更时同步。
- 代码走 git：NAS 与腾讯云同一仓库；发布前 `git push`，两边 `git pull` 或部署脚本拉分支。

**快速命令**

```powershell
# NAS — 日常开发部署
python deploy_nas.py

# 腾讯云 — 大版本（仅代码）
$env:TENCENT_SSH_PASS = "…"
python scripts/deploy_tencent.py

# 腾讯云 — 大版本 + 同步知识库
$env:SYNC_NAS_DATA = "1"
python scripts/deploy_tencent.py
```

---

## NAS（内网）

| 项目 | 值 |
|------|-----|
| SSH | `ssh -p 2212 skc@192.168.110.26` |
| 密码 | `SKChaidao@123` |
| 路径 | `/volume1/docker/PoE2LI` |
| Docker | `/usr/local/bin/docker`（不在默认 PATH） |
| 分支 | 通常 `main` 或 `cursor/cn-trade-realm` |
| 本地一键部署 | `python deploy_nas.py` |
| 分支部署脚本 | `python scripts/deploy_cn_trade_nas.py` |

### 常用命令

```bash
cd /volume1/docker/PoE2LI
git fetch origin && git reset --hard origin/main
/usr/local/bin/docker compose build --no-cache backend
/usr/local/bin/docker compose up -d --force-recreate backend
/usr/local/bin/docker compose ps
/usr/local/bin/docker logs poe2li-backend --tail 50
/usr/local/bin/docker restart poe2li-backend
```

### 从本机查 NAS 日志（paramiko）

```python
import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.110.26", 2212, "skc", "SKChaidao@123", timeout=10)

for cmd in [
    "/usr/local/bin/docker logs poe2li-backend --tail 30 2>&1",
    "/usr/local/bin/docker logs poe2li-backend 2>&1 | grep -E 'CHAT|POST /api/chat' | tail -15",
    '/usr/local/bin/docker ps --format "{{.Names}} {{.Status}}"',
]:
    _, out, _ = client.exec_command(cmd, timeout=15)
    out.channel.recv_exit_status()
    print(out.read().decode("utf-8", errors="replace"))

client.close()
```

**注意**：不要在 `exec_command()` 里嵌套 `"""` 多行 Python；复杂脚本先写到 NAS 文件再执行。SSH 终端中文可能乱码，DB 内为 UTF-8。

### NAS 代理

`docker-compose.yml` 中 backend/celery 使用 `HTTP(S)_PROXY=http://192.168.110.26:7890`（mihomo）。腾讯云部署须去掉代理行。

---

## 腾讯云（公网生产）

首次部署：**2026-06-14** · 广州 Lighthouse · OpenCloudOS 9.4 · 宝塔面板

| 项目 | 值 |
|------|-----|
| **站点** | http://liufangli.xyz/chat（IP 直连：`:3000`） |
| SSH | `ssh root@159.75.231.110`（22） |
| 密码 | `SKChaidao123`（控制台可重置） |
| 路径 | `/opt/PoE2LI` |
| 分支 | `cursor/cn-trade-realm` |
| 实例 | 2C2G · 40GB · `lhins-1t2s28x7` |
| 宝塔 | http://159.75.231.110:8888/tencentcloud |
| Compose | `docker compose -f docker-compose.yml -f docker-compose.tencent.yml` |
| 部署脚本 | `scripts/deploy_tencent.py` |
| Override 文件 | `docker-compose.tencent.yml` |

### 与 NAS 的差异

- **无 HTTP 代理** — `.env` 不含 `HTTP_PROXY` / `HTTPS_PROXY`
- **Postgres/Redis 不对外** — override 去掉 5433/6379 映射
- **默认不启 Celery** — 2GB 内存；仅 `postgres redis backend frontend`。AI 问答/交易正常；PoB 异步攻略可能不可用
- **API** — 浏览器走 `:3000` 同源 `/api/*`（Next 反代）。`:8000` 外网可能 502，一般无需开放
- **知识库** — 首次用 `SYNC_NAS_DATA=1` 从 NAS `pg_dump`（~132MB）恢复

### OpenCloudOS 安装 Docker

`get.docker.com` 不支持 OpenCloudOS，用 dnf：

```bash
dnf install -y docker docker-compose-plugin
systemctl enable docker && systemctl start docker
```

### 本机一键部署

```powershell
cd d:\PC_AI\Project\PoE2LI
$env:TENCENT_SSH_PASS = "SKChaidao123"
$env:SYNC_NAS_DATA = "1"   # 可选：从 NAS 同步 PG（需 NAS 在内网可达）
python scripts/deploy_tencent.py
```

| 环境变量 | 默认 |
|----------|------|
| `TENCENT_HOST` | `159.75.231.110` |
| `TENCENT_USER` | `root` |
| `TENCENT_PORT` | `22` |
| `TENCENT_ROOT` | `/opt/PoE2LI` |
| `TENCENT_BRANCH` | `cursor/cn-trade-realm` |
| `SYNC_NAS_DATA` | 不设；设 `1` 则恢复 NAS 数据库 |

流程：SSH → 装 Docker → git pull → 从 NAS 拉 `.env`（去代理）→ build → up → 可选 pg_restore → health check。

### 域名（liufangli.xyz）

| 项目 | 值 |
|------|-----|
| 根域 | `liufangli.xyz` |
| www | `www.liufangli.xyz` |
| DNS | 腾讯云「域名解析」A 记录 → `159.75.231.110`（**只负责解析，不配置网站**） |
| 站点 | http://liufangli.xyz/chat（80 → nginx 反代 → Docker `:3000`） |
| HTTPS | 未配置；须用宝塔申请 Let's Encrypt |

**常见误区**：控制台里域名显示「正常」只表示 DNS 生效。应用跑在 **3000 端口**，浏览器访问域名默认走 **80 端口**，必须在宝塔/nginx 加**反向代理**，否则会看到宝塔默认页。

Nginx 配置路径：`/www/server/panel/vhost/nginx/liufangli.xyz.conf`

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name liufangli.xyz www.liufangli.xyz;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 300s;
    }
}
```

写入后：`nginx -t && /etc/init.d/nginx reload`

**宝塔 GUI 等价操作**：网站 → 添加站点（域名填两个）→ 设置 → 反向代理 → 目标 `http://127.0.0.1:3000` → SSL → Let's Encrypt（可选）。

### 防火墙

1. **腾讯云控制台** → 实例 → **防火墙** → 放行 **TCP 3000**（0.0.0.0/0）
2. **宝塔系统防火墙** — 当前为**关闭**；若开启须再加 **3000**。已有：22、80、443、8888、FTP 段

### 腾讯云常用命令

```bash
cd /opt/PoE2LI
docker compose -f docker-compose.yml -f docker-compose.tencent.yml ps
docker compose -f docker-compose.yml -f docker-compose.tencent.yml logs -f backend --tail=50
docker compose -f docker-compose.yml -f docker-compose.tencent.yml up -d --build backend frontend
docker compose -f docker-compose.yml -f docker-compose.tencent.yml restart backend

# 更大内存实例才启 Celery：
docker compose -f docker-compose.yml -f docker-compose.tencent.yml --profile celery up -d celery_worker
```

### Chat 审计日志

```python
import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("159.75.231.110", 22, "root", "SKChaidao123", timeout=15)
_, out, _ = client.exec_command(
    "docker logs poe2li-backend 2>&1 | grep -E 'CHAT|rag_search|tool_call' | tail -30",
    timeout=30,
)
print(out.read().decode("utf-8", errors="replace"))
client.close()
```

### 更新生产（不灌库）

```powershell
$env:TENCENT_SSH_PASS = "SKChaidao123"
python scripts/deploy_tencent.py
```

NAS 知识库有更新时再设 `SYNC_NAS_DATA=1`。

---

## 通用注意

- 仅 `/app/data` 为 volume；改代码需 `docker compose build` 或 `docker cp`
- 前端 rebuild 建议 `docker compose build --no-cache frontend`（Turbopack 缓存问题见 `frontend/AGENTS.md`）
- `.env` 密钥：`MIMO_API_KEY`（LLM）、`SILICONFLOW_API_KEY`（Embedding + DeepSeek 备用）、`TRADE_CN_POESESSID` 等，勿提交 git

### LLM 切换（MiMo ↔ DeepSeek）

| 变量 | MiMo（当前） | DeepSeek（备用） |
|------|--------------|------------------|
| `LLM_BASE_URL` | `https://api.xiaomimimo.com/v1` | `https://api.siliconflow.cn/v1` |
| `LLM_MODEL` | `mimo-v2.5` | `deepseek-ai/DeepSeek-V4-Flash` |
| `LLM_API_KEY` | `${MIMO_API_KEY}` | `${SILICONFLOW_API_KEY}` |

在 `docker-compose.yml` 注释/取消注释对应块即可；Embedding 始终走 SiliconFlow BGE-M3。改 `.env` 后 `docker compose up -d --force-recreate backend`。
