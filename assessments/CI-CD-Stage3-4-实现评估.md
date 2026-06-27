# CI/CD Stage 3+4 实现评估

> 评估人：行舟（ops_engineer）  
> 时间：项目时间第 1 天 22:10

## 结论
**可以推进 build/deploy 的具体 YAML 实现**，但保留手动 gate 与环境注入规则，不急于把 prod 自动部署完全做实。

## 依据
- 织墨 Step 0 已完成，`backend/Dockerfile` 与 `frontend/Dockerfile` 可见且可构建
- 仓库中 `.github/workflows/ci.yml` 已存在，说明 CI 已有演进，需要先对齐现有约定
- 仍有未明确依赖：GHCR / 镜像仓库策略、GitHub Environments secrets / required reviewers、生产主机清单与回滚策略

## 建议推进方式
1. 产出 `build.yml` 具体内容（Docker build + push 到 GHCR）
2. 产出 `deploy.yml` 草稿（dev 自动 / staging+prod manual_dispatch + SSH 部署）
3. 明确环境变量注入规则：`.env` 不走仓库，由 GitHub Environments 提供
4. 保留回滚机制：镜像 tag 历史 + 失败自动回滚

## 与现有 ci.yml 的兼容性
- 现有 `ci.yml` 触发：PR → main、push → main
- 新增 `build.yml` 触发：push → main（仅构建镜像）
- 新增 `deploy.yml` 触发：push → main（dev 自动部署）、workflow_dispatch（staging/prod）
- 三者互不冲突：ci.yml 负责测试/lint，build.yml 负责镜像，deploy.yml 负责部署

## 待确认事项
1. 人间草木确认镜像仓库（GHCR / 私有）
2. 朝露配置 GitHub Environments + secrets
3. 人间草木确认 prod reviewers 名单
