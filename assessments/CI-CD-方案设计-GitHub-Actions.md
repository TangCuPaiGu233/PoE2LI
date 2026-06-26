# PoE2LI CI/CD 方案设计（GitHub Actions）

> 类型：方案设计文档（非实施代码）  
> 目标：替代当前本地 paramiko 脚本发布模式，建立可重复、可审计的自动化流水线  
> 建议实施窗口：Week 1

---

## 1. 总体设计

### 1.1 选择 GitHub Actions 的理由
- 仓库已托管在 GitHub，无需额外 CI 平台接入
- 与 GitHub 权限模型原生集成（ secrets / environments / protection rules ）
- 对 Docker 支持成熟：`docker/login-action` + `docker/build-push-action` 可直接产出镜像
- 市场可托管到 GitHub Container Registry（GHCR），减少外部依赖

### 1.2 核心原则
- **不可变制品**：每次构建产出带 tag 的镜像，部署基于镜像，不基于源码目录
- **环境隔离**：dev / staging / prod 各自拥有 secrets / environment / 主机列表
- **最少权限**：GitHub token / deploy key 只授予必要范围
- **可回滚**：保留历史镜像 tag，回滚即切换 tag

---

## 2. 四段 Pipeline 设计

### 2.1 Lint — 提交即触发
**触发条件**：`push` + `pull_request` 到任意分支

**步骤**：
1. checkout 代码
2. setup Node.js（frontend）
3. 执行 `npm ci && npm run lint`（ESLint / Prettier / type check）
4. setup Python（backend）
5. 执行 `ruff check` / `black --check` / `mypy`（根据项目现有工具链调整）
6. 任一失败则阻断

**产出**：代码风格 / 类型问题在合入前被发现

---

### 2.2 Test — PR 触发
**触发条件**：`pull_request` 到 `main`

**步骤**：
1. checkout
2. 启动测试依赖：`docker compose -f docker-compose.yml -f docker-compose.test.yml up -d postgres redis`
3. backend：
   - `pip install -r requirements.txt -r requirements-test.txt`
   - `pytest --cov=app --cov-report=xml`
   - 上传 coverage 到 Codecov（可选）
4. frontend：
   - `npm ci && npm test -- --coverage`
5. 终止测试容器

**质量门**：
- 核心模块覆盖率不低于现有基线（建议 ≥ 60%）
- 无新增 `pytest` 失败

---

### 2.3 Build — main 合并触发
**触发条件**：`push` 到 `main`

**步骤**：
1. checkout
2. `docker/login-action` → GHCR
3. `docker/build-push-action` 分别 build `backend`、`frontend`
   - tag 规则：`ghcr.io/<org>/poe2li-backend:sha-<commit>` + `:main`
   - 缓存：`actions/cache` 或 `build-push-action` 内置 registry cache
4. 推送后生成 release notes（可选）

**产物**：GHCR 镜像，后续 deploy 只引用 tag

---

### 2.4 Deploy — main 合并后 / manual_dispatch
**触发条件**：
- main 合并后自动部署到 dev
- manual_dispatch 选择 staging / prod（保护分支）

**策略**：

| 环境 | 触发方式 | 主机 | 说明 |
|------|---------|------|------|
| dev | main 合并自动 | NAS（192.168.110.26） | 开发/测试用 |
| staging | manual_dispatch | 腾讯云预发实例 | 如无独立实例，可与 prod 同机不同端口 |
| prod | manual_dispatch | 腾讯云生产（159.75.231.110） | 需 reviewer 批准 |

**部署步骤**：
1. 读取对应 environment secrets（SSH key / host / port / user）
2. SSH 到目标主机
3. `docker compose -f docker-compose.yml [-f docker-compose.tencent.yml] pull`
4. `docker compose up -d --force-recreate backend frontend postgres redis`
5. 健康检查：`curl -sf http://127.0.0.1:8000/health && curl -sf http://127.0.0.1:3000/`
6. 失败自动回滚到上一 tag

**多环境差异处理**：
- dev / staging / prod 通过 GitHub Environment 注入不同 secrets
- 腾讯云特有配置保留在 `docker-compose.tencent.yml`（端口屏蔽、内存限制）
- NAS 代理变量仅在 dev 环境注入

---

## 3. Secrets 与权限规划

### 3.1 GitHub Secrets（按环境）
| Secret | 作用 | 范围 |
|--------|------|------|
| `SSH_PRIVATE_KEY` | 部署 SSH key | dev / staging / prod 分别配置 |
| `HOST` | 目标主机 IP / 域名 | dev / staging / prod |
| `HOST_SSH_PORT` | SSH 端口 | dev / staging / prod |
| `HOST_SSH_USER` | SSH 用户 | dev / staging / prod |
| `GHCR_PAT` | GHCR 推送与拉取 | repo / packages 作用域 |
| `QWEN_API_KEY` | 后端 .env | dev / staging / prod |
| `SILICONFLOW_API_KEY` | Embedding / fallback LLM | dev / staging / prod |
| `LANGFUSE_*` | Langfuse 可观测 | dev / staging / prod |
| `TRADE_CN_POESESSID` | 交易搜索 | dev / staging / prod |

**禁止**将 `.env` 直接拷贝到主机；通过 GitHub Environment 或运行时生成文件写入。

### 3.2 GitHub Environments
- 创建 `dev`、`staging`、`prod` 三个 environment
- `prod` 配置 required reviewers（人间草木 / 朝露）
- 各自 secrets 隔离

---

## 4. 实施依赖（需其他成员配合）

| 成员 | 配合事项 | 时间要求 |
|------|---------|---------|
| **织墨**（后端） | 确认 backend 测试依赖（`requirements-test.txt`）、测试数据初始化方式、pytest 入口；确认 Dockerfile 构建上下文 | Week 1 起 |
| **栖霞**（前端） | 确认前端测试命令、Next.js standalone 输出方式、构建缓存策略 | Week 1 起 |
| **守夜**（数据） | 明确测试环境是否需要 PG 测试数据；如有，提供 `backend/scripts/seed_test_data.py` 或 docker volume 快照 | Week 1 起 |
| **朝露**（项目经理） | 在 GitHub 创建 environments 与 secrets；确认 dev/staging/prod 主机清单与 reviewer 名单 | Week 1 内 |
| **人间草木**（CEO） | 审批 prod environment required reviewers；确认是否使用 GHCR 或私有镜像仓库 | Week 1 内 |

> 注：远岫（架构师）建议在方案评审时确认镜像 tag 策略与环境边界是否满足架构约束。

---

## 5. 目录结构建议（新增）

```
.github/
  workflows/
    lint.yml
    test.yml
    build.yml
    deploy.yml
  docker/
    compose.test.yml           # test 专用 compose 扩展
```

其中 `deploy.yml` 通过 `environment` 区分 dev/staging/prod。

---

## 6. 风险与缓解

| 风险 | 缓解 |
|------|------|
| GHCR 构建慢 | 使用 registry cache + Dockerfile 分层优化 |
| 测试数据敏感 | 测试用 fake data 或本地 SQLite；不灌真实账号 Cookie |
| 腾讯云小实例内存不足 | staging 优先复用 NAS 资源；prod 保留手动 gate |
| 密钥泄露 | 最小范围 secrets + 定期轮换 + 不打印到 log |

---

## 7. Week 1 交付物

1. 本方案文档评审通过
2. GitHub Actions 四段 workflow 草稿（仅 `.github/workflows/` 目录，不含环境 secrets）
3. `docker-compose.test.yml` 草稿（测试依赖 PG / Redis 启动配置）
4. 环境与 secrets 清单确认（朝露 / 人间草木）
