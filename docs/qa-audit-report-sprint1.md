# Sprint 1 流程基建质量审计报告

> **审计人**：半山居（QA Engineer）
> **审计时间**：项目时间 第 2 天 02:02
> **审计范围**：`docs/review-process.md`、`docs/qa-gate-process.md`、`.github/workflows/ci.yml`、`docs/Sprint-01-Backlog.md`
> **审计标准**：QA Gate Process v1.0

---

## 一、审计总览

| 交付件 | 审计结论 | 摘要 |
|:-------|:--------:|------|
| `docs/review-process.md` | ✅ Approve | 五轴评审法完整、Review Flow 清晰、Merge 规则无歧义 |
| `docs/qa-gate-process.md` | 🟡 Comment | 介入点定义完整，但覆盖率目标缺少跟踪机制说明 |
| `.github/workflows/ci.yml` | 🟡 Comment | 骨架可用，Phase 1a/1b 切换计划可行，有 4 项中风险建议 |
| `docs/Sprint-01-Backlog.md` | 🟡 Comment | Day 1 检查点基本完整，但 CI/CD 状态未更新，风险管理缺少 CI 中风险项跟踪 |

---

## 二、逐项审计

### 2.1 `docs/review-process.md`（远岫 v1.0）

#### 五轴评审法完整性

| 轴 | 检查项数量 | 可执行性 | 结论 |
|:---|:----------:|:--------:|:----:|
| 轴一：正确性 | 4 项 | 每项有明确判断标准 | ✅ |
| 轴二：设计 | 4 项 | 与 CLAUDE.md 架构原则挂钩 | ✅ |
| 轴三：可维护性 | 4 项 | 命名/注释/配置/类型全覆盖 | ✅ |
| 轴四：测试 | 4 项 | 覆盖新增/回归/独立性/手动验证 | ✅ |
| 轴五：安全 | 4 项 | 输入校验/鉴权/泄露/降级全覆盖 | ✅ |

**结论**：✅ Approve — 五轴评审法完整可执行，checklist 颗粒度适中，不流于形式。

#### Review Flow 一致性

```
[Author] PR → [Self-Check] → [Peer] → [Architect] → [QA] → [Merge]
```

- 与 `docs/qa-gate-process.md` 中的介入点定义完全对齐
- 各环节职责、响应时限已明确
- 与 Sprint 1 Backlog 中的轨道分工一致

**结论**：✅ Approve — Review Flow 与实际流程一致。

#### Merge 规则清晰度

| 规则项 | 清晰度 | 结论 |
|:-------|:------:|:----:|
| 至少 1 个 Peer Approval | 明确 | ✅ |
| Checklist 全绿 | 明确 | ✅ |
| CI 绿 | 明确 | ✅ |
| 无未解决对话 | 明确 | ✅ |
| 架构级变更需 Architect Approve | 明确 | ✅ |
| 合并方式 | Squash & Merge | ✅ |
| 谁可合并 | 普通/架构级分类明确 | ✅ |

**结论**：✅ Approve — Merge 规则无歧义，执行层面可直接落地。

---

### 2.2 `docs/qa-gate-process.md`（半山居 v1.0 — 自检）

#### QA 介入点定义

| 阶段 | 定义完整性 | 与 Review Flow 对齐 | 结论 |
|:-----|:----------:|:-------------------:|:----:|
| Code Review | ✅ 按模块列出关注点 | ✅ 在 Architect Review 后介入 | ✅ |
| PR Merge | ✅ CI Gate + QA Gate 双闸门 | ✅ 在 CI 前作为独立闸门 | ✅ |
| Release | ✅ Preview/Staging/Production 三级 | ✅ 独立于代码审查 | ✅ |
| 每周审计 | ✅ 覆盖率趋势/技术债/安全扫描 | ✅ 补充 Review Flow 未覆盖项 | ✅ |

**结论**：✅ Approve — QA 介入点定义完整，与 Review Flow 无缝衔接。

#### 检查清单可操作性

- ✅ 按模块（API/chat_agent/pob_service/trade 等）列出具体审查项
- ✅ 结论类型分三级：Approve / Comment / Request Changes
- ✅ 响应时限按优先级（P0/P1/P2）区分
- ✅ 每个阶段有明确的通过/不通过条件

**结论**：✅ Approve — 检查清单可直接用于实战。

#### 覆盖率目标跟踪机制

**当前定义**：
- Sprint 1 目标：核心模块 ≥ 50%
- Sprint 2 目标：全模块 ≥ 70%
- v1.0 发布前目标：全模块 ≥ 80%

**缺失项**：
- ❌ 未定义覆盖率数据的采集方式（`pytest-cov` 输出如何汇总）
- ❌ 未定义跟踪频率（每次 CI？每日？每周？）
- ❌ 未定义谁负责跟踪、谁负责报警
- ❌ 未定义未达标时的升级路径

**结论**：🟡 Comment — 覆盖率目标已定义，但缺少跟踪机制说明。建议补充：
1. 覆盖率数据由 CI 自动采集并附于 PR 评论
2. 每周五由 QA 输出覆盖率趋势简报到 Sprint Board
3. 连续两周下滑或低于目标时，QA 触发技术债 review

---

### 2.3 `.github/workflows/ci.yml`（织墨 v1.1）

#### Phase 1a SQLite 模式

| 项 | 状态 | 说明 |
|:---|:----:|:-----|
| SQLite 数据库 | ✅ | `sqlite:///./test.db`，Phase 1a 单元测试适用 |
| PostgreSQL service | ✅ 已注释 | Phase 1b 集成测试时打开 |
| Redis service | ✅ 已注释 | Phase 1b 集成测试时打开 |
| 依赖安装 | ✅ | `pytest httpx` 已安装，TODO 待切 tests/requirements-test.txt |

**注意**：注释描述为"SQLite 内存模式"，但实际使用的是文件数据库 `./test.db`。GitHub Actions 每个 workflow run 使用独立 runner，文件冲突风险低，但建议修正注释或改为 `:memory:`。

#### Phase 1b Postgres 模式切换可行性

- 代码结构已预留切换点（注释标记）
- `DATABASE_URL` 环境变量已预留
- 切换时需：打开 postgres service + 修改 DATABASE_URL + 安装 pgvector 依赖
- **结论**：🟡 可行，但切换步骤未文档化。建议在 ci.yml 头部或 README 中写明切换 checklist。

#### 安全审计

| 检查项 | 状态 | 说明 |
|:-------|:----:|:-----|
| Secret 管理 | ✅ | LLM 凭据通过 GitHub Secrets 传入 |
| Secret 泄露风险 | 🟡 | 空字符串 fallback 可能触发真实 LLM 调用，产生费用 |
| 依赖漏洞扫描 | ❌ | 未集成 `pip-audit` 或 `safety` |
| 代码扫描 | ❌ | 未集成 `bandit` 或 `semgrep` |

#### 效率/质量审计

| 检查项 | 状态 | 说明 |
|:-------|:----:|:-----|
| `|| pytest` 回退逻辑 | 🟡 | 第 75 行，带 cov 失败时静默回退，掩盖问题 |
| coverage threshold | ❌ | 无 `--cov-fail-under`，覆盖率下滑无感知 |
| 前端 CI | ❌ | 未纳入 `npm run lint` + `npm run build` |
| 并行执行 | ❌ | 未使用 `pytest-xdist`，测试 suite 增大后耗时增加 |

**结论**：🟡 Comment — CI 骨架可用，Phase 1a/1b 切换计划可行。有 4 项中风险建议：

1. **前端 CI 缺失** → Sprint 2 加入 `npm run lint` + `npm run build`
2. **`|| pytest` 回退逻辑** → Sprint 1 收尾时移除，让 CI 严格失败
3. **coverage threshold 缺失** → Sprint 1 收尾时加 `--cov-fail-under=50`
4. **Redis service 缺失** → Phase 1b 集成测试时打开

低风险项排入 Sprint 2：
- 依赖漏洞扫描（`pip-audit`）
- 代码安全扫描（`bandit`）
- 并行执行（`pytest-xdist`）

---

### 2.4 `docs/Sprint-01-Backlog.md`（织墨 v1.1）

#### Day 1 里程碑检查点完整性

| 检查项 | 目标 | 实际 | 状态 | 一致性 |
|:-------|:----|:----|:----:|:------:|
| B4 文档对账完成 | Day 1 04:00 | Day 1 04:00 前 | ✅ | ✅ |
| Review 流程发布 | Day 1 | Day 1 | ✅ | ✅ |
| QA 节点定义发布 | Day 1 | Day 1 | ✅ | ✅ |
| Onboarding checklist 发布 | Day 1 | Day 1 | ✅ | ✅ |
| 全工程师 dispatch | Day 1 | Day 1 | ✅ | ✅ |
| CI/CD 草案 | Day 1 | Day 1（远岫反馈待落地） | 🟡 | ❌ |
| AI-02 风险预研报告 | Day 1 | Day 1 | ✅ | ✅ |
| TC 诊断报告 | Day 1 | Day 1 | ✅ | ✅ |

**不一致项**：CI/CD 草案状态标记为"远岫反馈待落地"，但 `.github/workflows/ci.yml` v1.1 已发布。建议更新为"✅ Done — v1.1 已发布，待 QA 审计"。

#### 风险管理跟踪

| 风险 | Day 1 状态 | 跟踪完整性 | 结论 |
|:-----|:----------:|:----------:|:----:|
| 远岫过载 | 🟡 缓解有效 | ✅ 有缓解措施和状态 | ✅ |
| 暮鼓 Phase 1a 延误 | 🟢 风险可控 | ✅ 有缓解措施和状态 | ✅ |
| FE-03 范围蔓延 | 🟢 已设边界 | ✅ 有边界描述 | ✅ |
| 新工程师环境配置 | 🟢 Onboarding 已发布 | ✅ 有状态 | ✅ |
| LLM API 成本 | 🟢 已规划 mock | ✅ 有状态 | ✅ |

**遗漏项**：
- ❌ 未跟踪 CI/CD 的 4 项中风险建议（前端 CI、|| 回退、coverage threshold、Redis service）
- ❌ 未跟踪 QA 审核流程文档的覆盖率跟踪机制缺失

**结论**：🟡 Comment — 风险管理框架完整，但缺少 CI 中风险项和 QA 文档改进项的跟踪。

---

## 三、审计结论与建议

### 3.1 总体结论

| 交付件 | 结论 | 优先级 |
|:-------|:----:|:------:|
| `docs/review-process.md` | ✅ Approve | — |
| `docs/qa-gate-process.md` | 🟡 Comment | P2 — 补充覆盖率跟踪机制 |
| `.github/workflows/ci.yml` | 🟡 Comment | P1 — 修复 || 回退 + 加 threshold |
| `docs/Sprint-01-Backlog.md` | 🟡 Comment | P2 — 更新 CI/CD 状态 + 补充风险跟踪 |

### 3.2 优先修复项（Sprint 1 收尾前）

1. **CI/CD `||` 回退逻辑**（ci.yml 第 75 行）→ 移除，让 CI 严格失败
2. **coverage threshold** → 加 `--cov-fail-under=50`
3. **Sprint-01-Backlog.md CI/CD 状态** → 更新为"v1.1 已发布，待 QA 审计完成"

### 3.3 排入 Sprint 2 项

1. 前端 CI 纳入（`npm run lint` + `npm run build`）
2. Redis service 在 Phase 1b 打开
3. 依赖漏洞扫描（`pip-audit`）
4. QA 覆盖率跟踪机制文档化
5. Sprint-01-Backlog.md 补充 CI 中风险项跟踪

---

## 四、审计签名

- **审计人**：半山居（QA Engineer）
- **审计日期**：项目时间 第 2 天 02:02
- **下次审计**：首个工程师 PR 提交后，按 QA Gate Process v1.0 执行 PR Merge 前审计
