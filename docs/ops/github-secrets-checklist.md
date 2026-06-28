# GitHub Secrets / Environment 配置清单

> 用途：支持 build.yml + deploy.yml 在 GitHub Actions 中端到端运行

## 必需 Secrets

| Secret | 用途 | 当前值来源 | 备注 |
|--------|------|-----------|------|
| NAS_PASS | NAS SSH 登录 | deploy_nas.py | NAS 2212 |
| TENCENT_SSH_PASS | 腾讯云 SSH 登录 | deploy_tencent.py | root 22 |
| QWEN_API_KEY | 后端 LLM | .env | 阿里云 DashScope |
| SILICONFLOW_API_KEY | Embedding + 备用 LLM | .env | SiliconFlow |
| LANGFUSE_SECRET_KEY | Langfuse | .env | 可选 |
| LANGFUSE_PUBLIC_KEY | Langfuse | .env | 可选 |
| LANGFUSE_AUTH_SECRET | Langfuse 登录 | docker-compose.yml | 可选 |
| LANGFUSE_ENCRYPTION_KEY | Langfuse | docker-compose.yml | 可选 |
| LANGFUSE_INIT_PASSWORD | Langfuse 初始化 | docker-compose.yml | 可选 |
| TRADE_CN_POESESSID | CN 交易抓取 | .env | 可选 |

## 建议 Variables（Environment）

| Variable | 默认值 | 用途 |
|----------|--------|------|
| NAS_HOST | 192.168.110.26 | NAS IP |
| NAS_PORT | 2212 | NAS SSH |
| NAS_USER | skc | NAS 用户 |
| NAS_GIT_REF | main | 部署分支 |
| TENCENT_HOST | 159.75.231.110 | 腾讯云 IP |
| TENCENT_PORT | 22 | 腾讯云 SSH |
| TENCENT_USER | root | 腾讯云用户 |
| TENCENT_ROOT | /opt/PoE2LI | 腾讯云项目路径 |

## 配置方式

1. 仓库 → Settings → Secrets and variables → Actions
2. 按上表创建 Secrets 和 Variables（Environment scope 可选 dev/staging/prod）
3. 配置 Environments：dev / staging / prod，prod 建议开启 required reviewers

## 注意

- 当前 deploy_nas.py / deploy_tencent.py 使用 SSH 密码登录；建议后续改为 SSH key。
- .env 中敏感值不要提交到 git；GitHub Secrets 为唯一可信来源。
- build.yml 推送 GHCR 可使用 GITHUB_TOKEN 自动授权；若使用独立镜像仓库，需额外配置 DOCKER_REGISTRY_TOKEN 或 GHCR_PAT。
