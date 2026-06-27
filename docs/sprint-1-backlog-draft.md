# Sprint 1 Backlog 草案

> 版本：draft v1
> 起草：拼图（PM）
> 状态：待与重构对齐后提交白鹭审核

---

## Sprint 1 主题：稳基础 · 清债务（D0-D3）

### Sprint Goal

完成运行时解耦 Phase 1（Step 0 → Step 1），建立测试基础设施雏形，完成文档对账，为 Sprint 2 的"实体库重建 + 质量门禁上线"铺平道路。

### 对齐企业 KR

| 企业 KR | Sprint 1 贡献 |
|---------|--------------|
| ② 运行时解耦（P0） | Step 0 + Step 1 解耦，目标：CHAT_RUNTIME 可安全切换 |
| ④ 质量门禁上线（P0） | 测试基础设施搭建（pytest + smoke test），为 Eval 自动化打基础 |
| （间接）⑤ CI/CD 管道建立 | 测试跑通后 CI 可接入 |

---

## Backlog（按优先级排序）

### P0 — 本周必须完成

| # | 任务 | 负责人 | 预估工时 | 依赖 | 交付物 |
|---|------|--------|---------|------|--------|
| S1-01 | **运行时解耦 Step 0：session_context.py 移出 orchestrator 包** | 重构 | 0.5d | 无 | PR：文件移动 + 5处import更新，全局grep无残留 |
| S1-02 | **运行时解耦 Step 1：抽公共 LLM 流式函数到 core/llm_stream.py** | 重构 + 缓存 | 1d | S1-01 | PR：新建 llm_stream.py，chat_agent.py 减负 ~90行，chat_orchestrator import 更新 |
| S1-03 | **测试基础设施搭建** | 来日方长 + 缓存 | 1d | 无（可并行） | pytest + pytest-asyncio 配置，首个 smoke test 通过，`pytest` 输出绿色 |
| S1-04 | **文档对账** | 拼图 + 重构 | 0.5d | 无 | CLAUDE.md / ADR / HANDOVER 一致性修复 PR |

### P1 — 本周尽量完成

| # | 任务 | 负责人 | 预估工时 | 依赖 | 交付物 |
|---|------|--------|---------|------|--------|
| S1-05 | **Planner JSON schema 验证 + Retry 机制** | 缓存 | 1d | S1-02（建议） | Pydantic PlannerOutput schema，替换 _extract_json()，retry ≤2 次 fallback |
| S1-06 | **Planner Fallback 智能改进** | 卡农 | 0.5d | S1-05（建议） | 按关键词智能判断 fallback agent，最多保留 2 个 |
| S1-07 | **TC 数据修复** | 卡农 | 0.5d | 无 | export_en_tc.py 配置修复 + 补跑 TC 导出 |
| S1-08 | **前端开发环境确认 + 首个 FE task** | 像素 | 0.5d | 无 | 开发环境就绪，已知 UI bug 修复（待确认具体） |

### 可选/待定

| # | 任务 | 说明 | 放入条件 |
|---|------|------|---------|
| S1-09 | Eval 基线跑一次 | 运行现有 eval set 记录四指标 | 测试基础设施跑通后 |
| S1-10 | 切换 CHAT_RUNTIME 默认值（Step 2） | 从 legacy → orchestrator | 仅当 Step 0+1 验证通过且风险可控 |

---

## 依赖关系图

```
S1-04 文档对账（无依赖，可最先做）
  │
S1-01 Step 0（无依赖）
  │
  └── S1-02 Step 1（依赖 S1-01）
        │
        ├── S1-05 Planner JSON schema（建议依赖 S1-02）
        │     └── S1-06 Fallback 改进（建议依赖 S1-05）
        │
S1-03 测试基础设施（无依赖，并行）
  │
S1-07 TC 数据修复（无依赖，并行）
  │
S1-08 前端环境（无依赖，并行）
```

---

## 人员分工

| 角色 | 姓名 | Sprint 1 重点工作 |
|------|------|-----------------|
| Tech Lead | 重构 | S1-01, S1-02（主导）, 全员 PR review |
| PM | 拼图 | S1-04（主导）, Sprint 进度跟踪, 风险跟踪 |
| Backend | 缓存 | S1-02（配合重构）, S1-03（配合 QA）, S1-05 |
| Backend | 卡农 | S1-06, S1-07 |
| Frontend | 像素 | S1-08 |
| QA | 来日方长 | S1-03（主导测试框架） |

---

## 风险登记册

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| Step 0/1 解耦引入回归 | 低 | 中 | 每一步代码移动后 review 确认，优先合并 small PR |
| 人员同时多任务并行导致上下文切换成本 | 中 | 低 | 每个开发者最多 2 个并行任务，串行执行 |
| Step 2 切换运行时后 orchestrator 稳定性低于 legacy | 中 | 高 | 暂不纳入 Sprint 1，留待 Sprint 2 充分验证后切换 |
| 缓存和卡农不熟悉代码库 | 中 | 中 | 重构提供代码走读 + 首个 task 安排较小粒度 |

---

## Sprint 1 验收标准

1. ✅ 循环依赖解除（Step 0+1 合并后，Legacy 和 Orchestrator 不再互相 import）
2. ✅ `pytest` 可运行，至少 1 个 smoke test 通过
3. ✅ 文档版本一致（CLAUDE.md / ADR 无过时信息）
4. ✅ （目标）S1-05 到 S1-08 至少完成 50%

---

*本草案待与重构对齐后提交白鹭审核。*
