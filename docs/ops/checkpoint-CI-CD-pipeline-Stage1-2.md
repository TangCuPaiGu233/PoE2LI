# Checkpoint — CI/CD Pipeline Stage 1+2

> 时间：项目时间第 1 天 11:16  
> 执行人：行舟（ops_engineer）  
> 协调人：朝露

## 沙箱未提交改动清单
- `.github/workflows/lint.yml` — Lint stage（ESLint + Prettier + ruff）
- `.github/workflows/test.yml` — Test stage（pytest + jest，含 PG/Redis service）
- `.github/workflows/build.yml` — Build stage placeholder
- `.github/workflows/deploy.yml` — Deploy stage placeholder
- `docs/ops/checkpoint-CI-CD-pipeline-Stage1-2.md` — 本 checkpoint

## 实现摘要
- lint.yml：push/PR 触发，前端 npm run lint + npx prettier --check，后端 ruff check .
- test.yml：PR/develop push 触发，后端 pytest（带 PG/Redis service + 覆盖率），前端 jest
- build.yml/deploy.yml：保留 TODO placeholder，明确列出对接条件

## 对接条件
1. 织墨完成 Docker Step 0（Dockerfile / 构建上下文验证）
2. 朝露配置 GitHub Environments + secrets（dev/staging/prod）
3. 人间草木确认 prod reviewers + 镜像仓库策略

## 状态
等待朝露 review 后 merge main。
