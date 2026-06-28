# NAS 部署检查清单

> 用途：在真正执行 `deploy_nas.py` 前，逐项确认可一步到位。

## 1. 前置条件

- [ ] NAS 可达：`ssh -p 2212 skc@192.168.110.26` 可登录
- [ ] Docker 可用：NAS 上 `/usr/local/bin/docker compose version` 正常输出
- [ ] 磁盘空间：`/usr/local/bin/docker system df` 显示可用空间充足
- [ ] Git 可用：NAS 上 `git --version` 正常；如需走代理确认 `git config --global http.proxy` 已配置
- [ ] 网络：NAS 能访问 GitHub（clone/fetch）、外网 LLM API（通过代理或 NO_PROXY）

## 2. 依赖确认

- [ ] 本机执行环境安装 `paramiko`（deploy_nas.py 依赖）
- [ ] 目标主机（NAS）有 `curl`、`grep`、`test` 等基础工具（deploy_nas.py 远程验证用）
- [ ] 若使用腾讯云脚本，确认 `paramiko` 已安装且网络可达

## 3. 环境变量 / Secrets

- [ ] `QWEN_API_KEY` 有效且未过期
- [ ] `SILICONFLOW_API_KEY` 有效且未过期
- [ ] `LANGFUSE_*` 如需启用，已配置
- [ ] `TRADE_CN_POESESSID` 如需 CN 交易，已配置
- [ ] GitHub Secrets 中 `NAS_PASS` 与当前密码一致；若改密码需同步更新

## 4. 代码前置检查

- [ ] 目标分支 `main` 已包含前端 chat image 功能（`frontend/src/lib/chatImage.ts`、`frontend/src/app/chat/page.tsx`）
- [ ] 后端 `/health` 端点可正常响应
- [ ] 前端 `/` 或 `/chat` 页面可访问
- [ ] Dockerfile 本地构建验证通过

## 5. 部署执行

### 5.1 首次部署
- [ ] 在 NAS 上创建项目目录：`mkdir -p /volume1/docker/PoE2LI`
- [ ] 确认网络/卷/网络不存在时会自动创建
- [ ] 执行 `python deploy_nas.py`
- [ ] 观察输出：git sync/clone → chat image 验证 → docker compose up --build --force-recreate
- [ ] 若某步失败，查看 STDERR 定位（常见：Git 权限、Docker 构建超时、环境变量缺失）

### 5.2 增量部署
- [ ] 在 NAS 上确认已有项目目录和 `.git`
- [ ] 执行 `python deploy_nas.py`（会执行 `git fetch && git reset --hard origin/main`）
- [ ] 观察输出：git reset → chat image 验证 → docker compose up --build --force-recreate
- [ ] 若只想快速重启不重新构建，可改为 `docker compose up -d --force-recreate`（但 CI 建议保持 --build）

## 6. 部署后验证

### 6.1 容器状态
- [ ] `docker compose ps`：所有容器 `running` 且 `healthy`

### 6.2 服务健康检查命令
- [ ] 后端 API：`curl -f http://localhost:8000/health` 返回 200
- [ ] 前端页面：`curl -f http://localhost:3000/` 返回 200
- [ ] PostgreSQL：`pg_isready -U poe2li -d poe2li` 返回 `accepting connections`
- [ ] Redis：`redis-cli ping` 返回 `PONG`
- [ ] Langfuse：`curl -f http://localhost:3000/api/public/health` 返回 200
- [ ] ClickHouse：`clickhouse-client -u langfuse --password langfuse_secret -q 'SELECT 1'` 返回 1
- [ ] Celery Worker：`celery -A app.tasks.celery_app inspect ping` 返回 pong
- [ ] Celery Beat：`pgrep -f 'celery beat'` 有输出

### 6.3 日志检查
- [ ] 日志无报错：`docker compose logs --tail=50` 关键服务无 ERROR

## 7. 回滚

- [ ] 上一版本镜像 tag 保留（建议 `:latest` + `:sha-<commit>`）
- [ ] 若新版本异常，执行 `docker compose up -d --force-recreate <service>:<old-tag>` 或 `git reset --hard origin/<previous-ref>` 后重部署

## 8. 常见失败点

| 现象 | 可能原因 | 处理 |
|------|---------|------|
| git fetch 失败 | 代理/DNS/权限 | 检查代理、改用 HTTPS、确认 repo 公开或 token 有效 |
| docker build 超时 | pip 源慢 | 确认 Dockerfile 使用清华镜像源 |
| 健康检查失败 | 启动慢/端口冲突 | 增加 start_period 或检查端口占用 |
| 前端缺失 chat image | 分支未合并 | 确认 origin/main 包含对应 commit |
