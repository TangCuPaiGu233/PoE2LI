# 技术债全景图（更新版）

> **基于 2026-06-27 代码实地稽核结果**
> 作者：重构 (Tech Lead) | 在远岫评估基础上修正补充
> 前置评估：`tech-architecture-assessment.md`（远岫, D0 16:00）

---

## 一、修正项：远岫评估与代码实况的偏差

| # | 远岫评估说 | 代码实况 | 偏差等级 |
|:-:|-----------|---------|:-------:|
| 1 | Step 0（session_context 移出 orchestrator）已完成，见 Phase 1 路线图 | **未执行**——session_context.py 仍在 orchestrator/，services/ 下无此文件 | 🔴 严重 |
| 2 | Step 1 抽取 `_emit_streamed_answer` 等函数到 `app/core/llm_stream.py` | 文件实际在 `app/services/llm_stream.py`（不是 core/），且 **0 个消费者** | 🟡 中 |
| 3 | Step 0 需改 import 共 3 处 | 实际需改 **7 处**（含 test 文件 3 处） | 🟡 中 |
| 4 | TC 数据缺失 70%+（T-02） | 缓存已解决——356 文件覆盖，P0 完备 | 🟢 已修复 |
| 5 |「无测试基础设施」（T-01）列为 P0 | 有少量测试文件（`tests/test_*.py` 多个），但无 CI 门禁 | 🟡 修正 |
| 6 | 架构路线图 Phase 1 时间表已过期 | 人员已更替（远岫→重构），需重排 | 🟡 中 |

---

## 二、当前技术债优先级重排

### P0 — Sprint 1 必须修复

| ID | 项目 | 影响 | 说明 |
|:--:|------|------|------|
| **T-03a** | **循环依赖：session_context 未移动** | 阻止所有重构，新旧运行时混淆 | Step 0：移文件 + 改 7 处 import |
| **T-03b** | **循环依赖：chat_agent ↔ chat_orchestrator** | 两运行时互相 import，无法独立废弃 | Step 1：去重 + 改 import 链路 |
| **T-01** | **无 CI/CD 门禁** | 每次改代码盲改，回归不可控 | 至少加 eval 基线 + 自动化测试入口 |
| **T-04** | **文档 vs 代码不一致** | 新成员入职陷阱，决策依据失准 | B4 文档对账 |

### P1 — Sprint 1 应纳入

| ID | 项目 | 影响 | 说明 |
|:--:|------|------|------|
| **T-05** | **Planner JSON 解析无 schema 验证** | LLM 格式漂移时静默失败 | 远岫评估正确，保留 |
| **T-06** | **Planner Fallback 太粗糙** | 失利时丢失交易/BD 能力 | 远岫评估正确，保留 |
| **T-07** | **LLM 流式函数存在重复实现** | 重复 3 对函数，维护双份 | Step 1.5 统一化 |
| **T-08** | **RRF + reranker 未实施** | 检索精度不足，延迟偏高 | P0-B 收尾需求 |

### P2 — Sprint 2+

| ID | 项目 | 影响 | 备注 |
|:--:|------|------|------|
| T-09 | Skills 模块命名误导 | 入职困惑 | 可重命名 |
| T-10 | CORS 全开 | 安全风险 | 生产环境限制 |
| T-11 | API 无版本前缀 | 无法平滑升级 | `/api/v1/` |
| T-12 | 开发/生产数据库不一致 | 本地测试覆盖不全 | PostgreSQL 化 |
| T-13 | 差异化超时 | 统一 120s 不合理 | 按 agent 类型 |
| T-14 | Legacy ReAct 废弃 | 代码冗余 | Step 3-4 |
| T-15 | 实体库重建 | 实体不全 | P1，等数据工程师 |

---

## 三、完整的循环依赖链（含测试文件）

```
orchestrator/session_context.py (218行)
  ↑ imports by:
    ├── orchestrator/llm_planner.py:14
    ├── orchestrator/planner.py:7
    ├── services/chat_agent.py:17        ← 核心循环
    ├── services/chat_orchestrator.py:15  ← 核心循环
    ├── tests/test_orchestrator_planner.py:7
    ├── tests/test_session_context.py:3
    └── tests/unit/test_chat_truncation.py:8

services/chat_agent.py (735行)
  ↑ imports by:
    ├── services/chat_orchestrator.py:16  (_emit_streamed_answer, _llm_client) ← 第二循环
    ├── services/chat_orchestrator.py:256 (stream_chat_agent, lazy import)
    ├── tests/test_chat_agent.py:7
    ├── tests/test_chat_orchestrator.py:318
    └── tests/test_sanitize_answer.py:9

services/llm_stream.py (206行)
  → 已抽取但 0 消费者 ← 孤立的工具文件
```

---

## 四、代码重复清单

| 函数 | chat_agent.py | llm_stream.py | 操作 |
|------|-------------|---------------|------|
| `_emit_streamed_answer` | L332 ✅ | `emit_streamed_answer` L143 ✅ | 保留 llm_stream，删除 chat_agent |
| `_llm_client` / `get_llm_client` | L302 ✅ | L127 ✅ | 保留 llm_stream，删除 chat_agent |
| `_first_choice` / `first_choice` | L327 ✅ | L137 ✅ | 保留 llm_stream，删除 chat_agent |
| `_model` / `get_model` | L306 ✅ | L132 ✅ | 保留 llm_stream，删除 chat_agent |
| `_sanitize_answer` / `sanitize_answer` | 内部 | L29 ✅ | 待确认是否重复 |
| `_sanitize_reasoning` / `sanitize_reasoning` | 内部 | L42 ✅ | 待确认是否重复 |

---

## 五、当前可用的安全网

| 安全措施 | 状态 | 说明 |
|---------|:----:|------|
| 单元测试 | ⚠️ 部分 | `tests/` 下有数个测试文件但覆盖率未知 |
| Eval 评测集 | ✅ 存在 | 24 题评测集 + 自动化打分脚本 |
| CI/CD | ❌ 无 | 无自动化构建/测试/部署管道 |
| Worktree 沙箱 | ✅ 可用 | HiveWeave worktree 机制可用于隔离变更 |

---

## 六、风险评估更新

| 风险 | 概率 | 影响 | 缓解 |
|------|:---:|:----:|------|
| Step 0 遗漏 import | 中 | 高 | 全局 regex grep + 验证脚本 |
| Step 1 删除函数后功能退化 | 中 | 高 | Eval 基线对比 + 保留 lazy import 路径 |
| 文档对账发现更多 doc-vs-code 偏差 | 高 | 低 | 随发现随修复 |
| 测试文件未覆盖解耦变更 | 中 | 中 | 手动运行关键测试 |

---

*更新于项目时间 第 1 天 00:46 | 下一次评估：Sprint 1 结束时*
