# QA 审核流程文档

> **负责人**：半山居（QA Engineer）
> **版本**：v1.0
> **状态**：Sprint 1 已发布
> **输入**：`docs/review-process.md`（远岫 / 代码审查流程）
> **协作**：远岫、织墨、朝露

---

## 一、目标与适用范围

**目标**：在代码审查、PR 合并、发布三个节点设置可执行的 QA 闸门，确保 Sprint 1 建立的测试基建和 Sprint 后续增量变更都有质量兜底。

**适用范围**：
- `backend/` 全量代码（FastAPI + Services + Orchestrator + Tasks）
- `frontend/` 页面与组件（Next.js / React / TypeScript）
- `.github/workflows/` 等工程化配置
- `docs/` 与项目文档一致性

**原则**：
1. 质量是“设计出来的”，不是“测出来的”。QA Gate 不替代好设计。
2. QA 只拦截“可预防的问题”，不拦截“需要讨论的问题”——后者走 review。
3. 初期以“轻量但必须过”为主，避免流程变成速度瓶颈。

---

## 二、QA 在开发流程中的介入点

```
[Author] PR
    │
    ▼
[Self-Check] — 作者自检（远岫 Checklist）
    │
    ▼
[Peer Review] — 同级工程师
    │
    ▼
[Architect Review] — 远岫（架构级变更）
    │
    ├──▶ [QA Code Review Gate] ← 半山居在此介入（见第三章）
    │
    ▼
[CI Gate] — 织墨的 CI/CD 自动检查（见第四章）
    │
    ▼
[Merge] — Squash & Merge
    │
    ▼
[QA Release Sign-off] — 发布前（见第五章）
    │
    ▼
[Release]
```

### 介入规则

| 节点 | QA 是否介入 | 触发条件 |
|:----:|:-----------:|---------|
| Code Review | ✅ 必须 | 涉及 API、数据模型、AI 输出逻辑、安全配置、CI/CD 的 PR |
| PR Merge | ✅ 必须 | 所有 `main` 分支 PR |
| Release | ✅ 必须 | 任何生产/预览环境发布 |

**例外**：纯文档、注释修正、README 更新可豁免 QA Gate，但仍需 Peer Review。

---

## 三、Code Review 阶段 — QA 审查清单

远岫的五轴评审法覆盖了**正确性、设计、可维护性、测试、安全**。QA 在此基础上补充**质量风险视角**，不做重复审查。

### 3.1 QA 审查重点

| 维度 | QA 看什么 | 典型问题 |
|:-----|-----------|---------|
| **测试覆盖** | 新代码是否有测试？ | 新 API 端点无集成测试；边界条件未覆盖 |
| **回归风险** | 修改是否影响既有模块？ | 改了 `entity_resolver.py` 但未跑相关测试 |
| **AI/LLM 安全** | LLM 调用是否有输入/输出控制？ | prompt 注入风险、输出无 schema 验证 |
| **数据安全** | 数据库操作是否安全？ | SQL 拼接、敏感数据日志、向量操作类型 |
| **外部依赖** | 新增/修改的依赖是否必要？ | 为了小功能引入大库 |
| **错误处理** | 失败路径是否可观测？ | try/except 吞异常、无日志、无降级 |
| **性能** | 是否存在明显性能陷阱？ | 循环内 DB 查询、无缓存的热路径 |

### 3.2 按模块的 QA 关注点

| 模块 | QA 特别关注 |
|:-----|-------------|
| `api/*` | 参数校验、响应 schema、错误码一致性、无敏感信息泄露 |
| `services/chat_agent.py` | LLM 超时、空回复、工具调用失控、上下文长度 |
| `services/chat_tools.py` | 工具输入 schema 校验、副作用（DB 写入/外部调用） |
| `services/pob_service.py` | 畸形 PoB code 的错误恢复、zombie XML 解析 |
| `services/entity_resolver.py` | 别名消歧准确性、fallback 行为 |
| `services/filter_generator.py` | 生成的 filter 语法正确性、注入风险 |
| `services/trade_*.py` | 外部 API 超时、限流、缓存失效策略 |
| `core/database.py` | SQLite/PostgreSQL 行为一致性、pgvector 类型 |
| `orchestrator/*` | 并行调用异常传播、session 泄漏 |
| `tasks/*` | Celery 任务幂等性、失败重试、死信风险 |

### 3.3 QA 审查结论类型

- **✅ Approve**：无问题，可进入 CI Gate
- **🟡 Comment**：非阻塞建议，可合并后跟进
- **🔴 Request Changes**：阻塞项，必须修复后重新审查

**QA 响应时限**：P0 PR ≤ 2 项目时，P1 ≤ 8 项目时，P2 ≤ 1 项目日。

---

## 四、PR 合并前 — QA 批准条件

### 4.1 自动化检查（CI Gate）

织墨的 CI/CD 已定义以下检查：

| 检查项 | 工具/方式 | 通过条件 |
|:-------|:----------|:---------|
| pytest | `pytest -v --tb=short --cov=app` | 0 failure |
| 覆盖率报告 | `pytest-cov` | 有输出（Sprint 1 无强制阈值） |
| lint | `ruff check .` | 0 error |
| 代码格式 | `ruff format --check .` | 0 error（当前 `continue-on-error`，Sprint 2 收紧） |

**Sprint 1 覆盖率目标**：核心模块（`pob_service.py`、`entity_resolver.py`、`chat_response_guard.py`、`api/`）≥ 50%。
**Sprint 2 覆盖率目标**：全模块 ≥ 70%。
**v1.0 发布前覆盖率目标**：全模块 ≥ 80%。

> 注：上述覆盖率为项目目标，具体阈值需与工程师确认可行性后调整为强制红线。

### 4.1.1 覆盖率跟踪机制

| 环节 | 方式 | 频率 | 负责人 |
|:-----|:-----|:-----|:------|
| **数据采集** | `pytest-cov` 生成覆盖率报告，CI 以 artifact 或 PR comment 形式输出 | 每次 CI 自动执行 | CI 自动 |
| **趋势跟踪** | QA 每周五汇总本周覆盖率数据，输出《覆盖率趋势简报》到 Sprint Board | 每周一次 | 半山居（QA） |
| **达标判定** | 与第 4.1 节目标对比，标记达标/未达标模块 | 每周简报中执行 | 半山居（QA） |
| **升级路径** | 连续 2 周覆盖率下滑，或任一目标模块低于目标值 10% 以上，触发技术债 review | 按需触发 | 半山居（QA）发起，远岫 + 织墨参与 |
| **改进落地** | 技术债 review 输出改进计划，织墨排入下轮 Sprint | 技术债 review 后 | 织墨（PM） |

**执行细则**：
- CI 覆盖率报告优先以 PR comment 形式呈现，方便 Review 者直观看到增量影响。
- 周报格式固定为：模块名 / 当前覆盖率 / 目标 / 趋势（↑/↓/→） / 备注。
- 技术债 review 需产出具体 action items，不允许“观察一轮”后无结论。

### 4.2 CI 草案审计发现（织墨 / `.github/workflows/ci.yml`）

审计时间：项目时间 第 1 天 18:55

| 发现项 | 风险 | 状态 | 建议 |
|:-------|:-----|:-----|:-----|
| 前端未纳入 CI | 前端代码质量无自动兜底 | 🟡 中 | Sprint 2 加入 `npm run lint` + `npm run build` |
| `|| pytest -v --tb=short` 回退 | 带 cov 的失败被静默吞掉 | 🟡 中 | 移除回退，CI 必须跑带 cov 的版本 |
| 无 coverage threshold | 覆盖率可能持续下滑 | 🟡 中 | 加 `--cov-fail-under=50`（Sprint 1 后） |
| 无 secret/依赖扫描 | 依赖供应链风险 | 🟢 低 | Sprint 2 接入 `pip-audit` 或 `safety` |
| 硬编码测试凭据 | 低风险（CI 内短生命周期） | 🟢 低 | 保持现状，确保 secrets 不泄露到日志 |
| Redis 未作为 service | 依赖 REDIS_URL 但未声明 | 🟡 中 | 当前未强制 Redis，如后续需要需补 service |
| Python 3.11 与 repo 是否一致 | 潜在版本差异 | 🟢 低 | 确认 `pyproject.toml` 或 `runtime.txt` 指定版本 |

**审计结论**：CI 骨架基本可用，PR 阶段已有测试+lint 门禁。上述中风险项建议在 Sprint 1 收尾时修复 `||` 回退逻辑和 coverage threshold；低风险项排入 Sprint 2。

### 4.3 QA Merge 批准条件

以下条件**全部满足**时，QA 方可批准合并：

- [ ] CI 全绿（pytest + lint）
- [ ] QA Code Review Gate 已通过（或豁免）
- [ ] 新增/修改代码有对应测试（核心模块覆盖率达标）
- [ ] 无未解决的 P0/P1 安全风险
- [ ] 无硬编码密钥/凭证/内部路径进入代码库
- [ ] PR 描述完整（What + Why + 验证结果）

**谁可批准合并**：
- 普通 PR：Peer Reviewer Approve + QA Approve
- 架构级 PR：远岫 Approve + QA Approve

---

## 五、发布前 — QA Sign-off

### 5.1 发布类型定义

| 类型 | 环境 | 说明 |
|:-----|:-----|:-----|
| **Preview** | Vercel / 测试环境 | 前端联调、功能验收 |
| **Staging** | 预发布环境 | 与生产一致的配置，回归测试 |
| **Production** | 生产环境 | 用户可见的正式发布 |

### 5.2 QA Sign-off 条件

发布前，QA 必须确认以下事项：

#### 通用条件（所有发布类型）

- [ ] 本版本所有 PR 已过 CI Gate
- [ ] 本版本所有 P0/P1 bug 已修复或明确延期
- [ ] 回滚方案已就绪（数据库 migration 可回滚、配置可还原）
- [ ] 发布说明（Release Notes）已起草

#### Staging / Production 额外条件

- [ ] **冒烟测试通过**：`/health` 返回 `{"status": "ok"}`，P0 API 端点可正常调用
- [ ] **P0 核心链路验证**：
  - PoB 解码 → AI 攻略生成 → 存储 → 前端展示
  - 市集搜索基础路径
  - 实体悬浮提示基础路径
- [ ] **数据完整性**：知识图谱、实体目录、交易数据索引在目标环境正常
- [ ] **依赖版本锁定**：`requirements.txt` / `package-lock.json` 已提交
- [ ] **配置审计**：`DATABASE_URL`、`LLM_API_KEY`、`REDIS_URL` 等环境变量在目标环境正确配置，且未硬编码
- [ ] **CORS 配置**：生产环境 `allow_origins` 已限制（当前为 `["*"]`，上线前必须收紧）
- [ ] **错误监控**：Langfuse / 日志链路在目标环境可访问

### 5.3 Sign-off 流程

1. 织墨在 PR 合并完成后发起发布申请
2. 半山居在 4 项目时内完成上述检查
3. 检查通过 → 发布；不通过 → 退回修复，记录原因
4. 发布完成后 1 项目日内输出《发布质量报告》

---

## 六、质量门禁总表

| 节点 | 责任人 | 检查内容 | 通过条件 | 阻塞级别 |
|:-----|:-------|:---------|:---------|:---------|
| Self-Check | PR 作者 | Checklist 五轴 | 自检通过 | 建议 |
| Peer Review | 同领域工程师 | 代码正确性、可维护性 | Approve | 🔴 阻塞 |
| Architect Review | 远岫 | 架构合理性 | Approve（架构级变更） | 🔴 阻塞 |
| QA Code Review Gate | 半山居 | 测试/安全/AI/性能风险 | Approve | 🔴 阻塞 |
| CI Gate | GitHub Actions | pytest + lint + cov | 全绿 | 🔴 阻塞 |
| QA Release Sign-off | 半山居 | 冒烟/P0链路/配置/数据 | Sign-off | 🔴 阻塞 |

---

## 七、与现有流程的衔接

### 7.1 与 Review 流程的关系

- `docs/review-process.md` 定义了 **Peer → Architect → QA** 的顺序
- 本文档定义了 QA 在每一阶段的具体检查内容和通过标准
- 两文档互补，不替代

### 7.2 与 CI/CD 的关系

- CI 负责自动化检查（pytest、lint、cov）
- QA 负责 CI 无法覆盖的部分（架构风险、AI 安全、发布验证）
- CI 是 QA Gate 的**必要非充分条件**

### 八、文档维护

- 维护人：半山居
- 最后更新：项目时间 第 1 天
- 修订须经朝露或远岫审批
