# Checkpoint — CI/CD 方案设计

> 时间：项目时间第 1 天 00:02  
> 执行人：行舟（ops_engineer）  
> 协调人：朝露

## 交付物
- `assessments/CI-CD-方案设计-GitHub-Actions.md` — GitHub Actions 四段 pipeline 方案

## 方案摘要
- Lint：提交即触发（ESLint/Prettier + Python 检查）
- Test：PR 触发（pytest + jest，含覆盖率）
- Build：main 合并触发（Docker image → GHCR）
- Deploy：main 后自动 dev，manual_dispatch 选择 staging/prod（需 reviewer 审批）

## 多环境策略
- dev（NAS）：main 合并自动部署
- staging：manual_dispatch（可复用 prod 同机不同端口）
- prod（腾讯云）：manual_dispatch + required reviewers

## 实施依赖（待人间草木确认方向）
- 织墨：backend 测试依赖与 pytest 入口确认
- 栖霞：前端测试命令与 Next.js standalone 输出
- 守夜：测试环境数据依赖
- 朝露：GitHub environments / secrets 配置
- 人间草木：prod reviewer 名单 + 镜像仓库选择（GHCR / 私有）

## 当前状态
等待人间草木确认方向 + 朝露五轴 review 完成后进入实施。
