# 技术架构评估报告 & 技术债全景视图

**评估者**：远岫（技术架构师）
**评估时间**：项目时间 第 0 天 05:27 — 16:00（代码摸底 + 全景更新）
**状态**：已定稿 / 等人间草木确认

---

## 一、评估范围

- CLAUDE.md（项目主说明文档）、CONTEXT.md（领域词汇表）
- `backend/app/` 全量代码结构（API 层 / Core 层 / 服务层 / Orchestrator 层 / Skills 层 / Tasks 层）
- `docs/adr/` 全部 3 份架构决策记录
- `assessments/data-ops-assessment.md`（现有数据运维评估）
- `docs/orchestrator-migration-plan.md`（归鸿起草的迁移方案）
- `assessments/chat-agent-risk-assessment.md`（归鸿的风险评估）
- `backend/app/main.py`、`database.py` 等关键基础设施文件

---

## 二、架构总览评分

| 维度 | 评分 | 说明 |
|------|------|------|
| **分层清晰度** | ★★★★☆ | 三层 Agent 架构（Main Agent → Sub-Agent → Tool）职责明确 |
| **文档完备性** | ★★★★☆ | CLAUDE.md 是极好的单源 truth，ADR 覆盖关键决策 |
| **模块内聚** | ★★★★☆ | services/ 各模块边界清晰，单一职责 |
| **模块耦合** | ★★☆☆☆ | **两个运行时互相依赖** — 循环依赖，必须立即解耦 |
| **可测试性** | ★☆☆☆☆ | 未见测试基础设施，这是当前最大短板 |
| **可观测性** | ★★★☆☆ | Langfuse 覆盖 LLM 层面，但应用级监控缺失 |
| **部署成熟度** | ★★★☆☆ | Docker Compose 完整，但生产环境有配置盲区 |
| **数据管道** | ★★☆☆☆ | 全手动流程，多语言数据不完整 |

**模块耦合评分下调**：摸底后发现两个运行时存在循环依赖（详见 §3.2-1），比之前评估的更严重。

---

## 三、核心发现

### 3.1 关键架构决策 — 运行时统一

**问题**：当前 `CHAT_RUNTIME=legacy` 为生产默认，orchestrator 需显式 opt-in。两套运行时并存。

**决策**：**选 Orchestrator，废弃 Legacy ReAct。** 详见决策表：

| 维度 | Legacy ReAct | Orchestrator | 结论 |
|------|-------------|-------------|------|
| 架构意图 | AI 做路由+执行，揉在一起 | AI 做路由，代码做执行 | 🏆 Orchestrator |
| 规则维护 | 36 条规则耦合在一条 system prompt | 规则分层（planner/skill/synthesis） | 🏆 Orchestrator |
| 并行能力 | 串行工具调用 | 多子任务并行（已实现） | 🏆 Orchestrator |
| 错误隔离 | 单点失败影响整轮 | 子任务独立失败 | 🏆 Orchestrator |
| 完成度 | ✅ 生产级成熟 | ⚠️ 有可修缺口 | 过渡期问题 |
| 可观测性 | ❌ 中间状态不可见 | ✅ 结构化 SkillAgentResult | 🏆 Orchestrator |

### 3.2 关键发现：循环依赖（P0）

代码摸底发现两个运行时相互 import：

```
Legacy ReAct (chat_agent.py)
  └── 第 17 行: from app.orchestrator.session_context import build_session_context
       ↑ 依赖 Orchestrator 包

Orchestrator (chat_orchestrator.py)
  └── 第 15 行: from app.services.chat_agent import _emit_streamed_answer, _llm_client
       ↑ 依赖 Legacy
```

**影响**：
- 无法单独删除任一运行时
- 重构任何一个都需要动另一个
- 新同学理解成本高

**解决方案**（已获人间草木确认）：
1. Step 0（即时）：将 `session_context.py` 从 `app/orchestrator/` 移出到 `app/services/`
2. Step 1（D0-D1）：将 `_emit_streamed_answer` + `_llm_client` 抽到 `app/core/llm_stream.py`
3. 解耦后即可安全废弃 Legacy

### 3.3 Orchestrator 的已知缺口

Orchestrator 当前有 4 个可修缺口（非架构问题，是代码深度问题）：

#### 缺口 1：Planner JSON 解析无 schema 验证

**当前行为**：
- `llm_planner.py:llm_plan_dispatch()` 调用 LLM 后，用 `_extract_json()` 做无 schema 的 JSON 提取
- 如果 LLM 返回的 JSON 格式漂移（字段名拼错、类型不对、结构变化），`_task_from_entry()` 静默返回 None，任务被丢弃
- 没有 retry 机制

**目标行为**：
- 引入 Pydantic `PlannerOutput(BaseModel)` schema 做输出验证
- 优先用 OpenAI `response_format={"type": "json_object"}` 让 LLM 原生输出 JSON
- 验证失败时自动 retry（最多 2 次），而不是直接 fallback

**为什么重要**：Planner 是 Orchestrator 的入口，它一旦不稳定，整个 pipeline 都受影响。当前"静默失败→单百科 fallback"的行为会让用户丢失交易搜索和 BD 推荐能力。

#### 缺口 2：Fallback 太粗糙

**当前行为**：
- `llm_planner.py` 中 `_fallback_plan()` 返回一个单 `encyclopedia` 任务
- 丢失了 `trade_search`、`recommend`、`build_design` 的能力

**目标行为**：
- Fallback 应根据用户消息关键词智能选择：
  - 包含"多少钱/价格/卖/搜" → 加 `trade_search`
  - 包含"推荐/哪个好/对比" → 加 `recommend`
  - 包含"怎么配/BD/搭配" → 加 `build_design`
- 最多保留 2 个 agent（避免 fallback 时也并行过多）

#### 缺口 3：无循环/重复调用检测

**当前行为**：无检测机制
**目标**：在 `ChatToolContext` 中记录 tool call 历史，检测同一工具+相似参数在连续轮次中重复

#### 缺口 4：超时策略单一

**当前行为**：所有 agent 统一 120s 超时
**目标**：差异化超时 — decode_pob 60s、trade_search 120s、encyclopedia 90s、recommend 60s

### 3.4 其他值得关注的问题

**Skills 模块命名误导（§3.2-3 确认）**：
- `skills/` 实际作用是提供 orchestrator synthesis 用的 prompt 片段
- `skills/router.py` 的 `get_skill()` 函数是 prompt 提供者，不是路由器
- **建议**：重命名为 `synthesis_prompts/` 或保持原样等 Sprint 2

**SQLite → PostgreSQL 双轨开发（§3.2-4 确认）**：
- `database.py` 的 `SQLiteVector` monkey-patch 让本地开发无法测试向量操作
- **建议**：本地开发默认用 docker-compose 的 PostgreSQL

**CORS 全开（§3.2-5 确认）**：
- `allow_origins=["*"]`
- **建议**：生产环境限制具体域名

---

## 四、技术债清单（按优先级排列）

### P0 — 本日/本周必须修复

| # | 项目 | 影响 | 负责人 | 建议 |
|---|------|------|--------|------|
| T-01 | **无测试基础设施** | 每次改代码都是盲改，回归风险高 | 来迟 | pytest + golden data + smoke test |
| T-02 | **TC 数据缺失 70%+** | 繁体用户核心功能不可用 | 守夜 | 修复 `export_en_tc.py` 配置，补跑 TC 导出 |
| T-03 | **循环依赖（双运行时互相 import）** | 阻止运行时废弃，混淆团队 | 远岫→织墨 | Step 0-1 解耦 |

### P1 — 短期（D0-D3）

| # | 项目 | 影响 | 建议 |
|---|------|------|------|
| T-04 | **Planner JSON 解析无 schema 验证** | LLM 格式漂移时静默失败 | 加 Pydantic schema + retry |
| T-05 | **Planner Fallback 太粗糙** | 失利时丢失交易/BD能力 | 智能判断 fallback agent |
| T-06 | **Skills/ 模块命名误导** | 新成员入职困惑 | 重命名为 `synthesis_prompts/` |
| T-07 | **数据管道自动化** | 版本更新时人工操作易遗漏 | Makefile / shell script |
| T-08 | **Celery Beat 生产配置确认** | 定时价格扫描可能不运行 | 验证 docker-compose 配置 |

### P2 — 中期改进（Sprint 2）

| # | 项目 | 影响 | 建议 |
|---|------|------|------|
| T-09 | **CORS 全开** | 安全风险 | 生产环境限制具体域名 |
| T-10 | **API 无版本前缀** | 无法平滑升级 API | 引入 `/api/v1/` 路由前缀 |
| T-11 | **开发/生产数据库不一致** | 本地测试覆盖不到 pgvector | 本地默认用 PostgreSQL |
| T-12 | **Observability 仅覆盖 LLM** | 应用级问题无法追踪 | 补充应用指标 |
| T-13 | **Entity Catalog 重建未自动化** | KB 更新后 UI 可能不同步 | 加入 deploy pipeline |
| T-14 | **差异化超时** | 统一 120s 不合理 | 按 agent 类型设不同超时 |
| T-15 | **重复调用检测** | 可能浪费资源 | ChatToolContext 中记录 tool call 历史 |

---

## 五、架构路线图（更新版）

```
Phase 1（D0-D3）—— 稳基础 + 清债务
├── 【远岫】Step 0: session_context.py 移出 orchestrator 包
├── 【远岫→织墨】Step 1: 抽 _emit_streamed_answer 到 core/
├── 【归鸿】AI Chat 稳定性修复（基于 orchestrator）
├── 【来迟】测试体系建设
├── 【守夜】TC 数据修复 + 数据管道脚本化
│
Phase 1.5（D3-D7）—— 运行时切换
├── 【远岫→织墨】Step 2: 切换 CHAT_RUNTIME 默认值
├── 【远岫→织墨】Step 3: 规则迁移（36 条规则分层）
├── 【远岫】验证 orchestrator 稳定性
│
Phase 2（Sprint 2）—— 清理 + 提质量
├── 【远岫→织墨】Step 4: Legacy 废弃
├── Skills 模块重命名
├── 开发环境 PostgreSQL 化
├── Observability 增强
├── API 版本化
│
Phase 3（中期）
├── 性能基准 + 压测
├── Entity Catalog 自动化
├── Browser Extension（M7/M8）
```

---

## 六、对 Phase 1 的任务建议

### 6.1 Step 0：解耦 session_context.py

**文件移动**：
- `backend/app/orchestrator/session_context.py` → `backend/app/services/session_context.py`

**需改 import 的文件**（共 3 处）：
1. `backend/app/services/chat_agent.py` 第 17 行:
   ```python
   # 改前: from app.orchestrator.session_context import build_session_context
   # 改后: from app.services.session_context import build_session_context
   ```
2. `backend/app/services/chat_orchestrator.py` 第 14 行: 同上
3. `backend/app/orchestrator/llm_planner.py` 第 14 行: 同上
4. `backend/app/orchestrator/planner.py` 第 7 行: 同上
5. `backend/app/orchestrator/__init__.py`：删除 `session_context` 的导出（可选）

**测试**：全局 grep 确认 `from app.orchestrator.session_context` 全部替换完成。

### 6.2 Step 1：抽公共 LLM 流式函数到 core/

**新文件**：`backend/app/core/llm_stream.py`

**职责**：
- `get_llm_client()` — LLM 客户端工厂（已存在于 `app.core.llm_client`，但 `chat_agent.py` 有自有的 `_llm_client()` 包装函数）
- `emit_streamed_answer()` — 流式/非流式 LLM 合成
- `_sanitize_answer()` / `_sanitize_reasoning()` — 输出卫生

**当前分布**：
- `chat_agent.py` 第 301-306 行: `_llm_client()` 和 `_model()` — 本质是 `get_async_llm_client()` + `LLM_MODEL` 的薄包装
- `chat_agent.py` 第 331-393 行: `_emit_streamed_answer()` — 流式/非流式 LLM 调用，带 reasoning_content 处理
- `chat_agent.py` 第 99-127 行: `_sanitize_answer()` / `_sanitize_reasoning()` — wiki 语法和 tool-call XML 清理
- `chat_agent.py` 第 130-146 行: `_safe_flush_point()` — streaming 缓冲安全切割

这些函数本质上是公共工具，不属于任何一个运行时。

**变更影响**：
- `chat_agent.py` 删除 ~90 行（纯工具函数），保留 ReAct 循环
- `chat_orchestrator.py` 第 15 行 import 从 `chat_agent` 改为 `app.core.llm_stream`
- 其他可能引用 `_sanitize_answer` 的地方（全局搜）

### 6.3 Planner JSON 验证改进（归鸿可并行）

**代码位置**：`backend/app/orchestrator/llm_planner.py`

**改动内容**：
1. 新增 Pydantic model:
   ```python
   class PlannerOutput(BaseModel):
       tasks: list[PlannerTask]
       reasoning: str = ""
   
   class PlannerTask(BaseModel):
       agent: Literal["trade_search", "encyclopedia", "build_design", "recommend", "decode_pob"]
       query: str | None = None
       question: str | None = None
       input: str | None = None
       detail_count: int = 3
   ```
2. 在 `llm_plan_dispatch()` 中，LLM 调用后先过 schema 验证
3. 验证失败 → retry（最多 2 次）→ retry 仍失败 → 改进的 fallback
4. 当前 `_extract_json()` 和 `_task_from_entry()` 的脆弱逻辑可逐步替换

### 6.4 Fallback 改进

**代码位置**：`backend/app/orchestrator/llm_planner.py` 中 `_fallback_plan()`

**当前代码**（第 157-172 行）：
```python
def _fallback_plan(ctx: SessionContext) -> DispatchPlan:
    return DispatchPlan(
        tasks=[TaskSpec(agent="encyclopedia", ...)],
        planning_note="llm_planner_fallback",
    )
```

**目标行为**：
```python
def _fallback_plan(ctx: SessionContext) -> DispatchPlan:
    text = ctx.current_user_text
    agents = ["encyclopedia"]  # 兜底
    if any(kw in text for kw in ["多少钱", "价格", "搜", "卖", "市价", "查价"]):
        agents.append("trade_search")
    if any(kw in text for kw in ["推荐", "哪个好", "对比", "vs"]):
        agents.append("recommend")
    if any(kw in text for kw in ["怎么配", "BD", "搭配", "配装"]):
        agents.append("build_design")
    # 最多保留 2 个
    agents = agents[:2]
    tasks = [TaskSpec(agent=a, ...) for a in agents]  
    # ...确保 trade_anchor/pob 处理
    return DispatchPlan(tasks=tasks, planning_note="rule_fallback")
```

---

## 七、风险评估

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| orchestrator 切换后成功率低于 legacy | 中 | 高 | 并行期保留 legacy fallback，监控对比 |
| planner JSON 格式漂移 | 中 | 中 | schema 验证 + retry + 改进 fallback |
| 循环依赖解耦引入回归 | 低 | 中 | 每一步都是机械性代码移动（改 import 路径），review 即可 |
| 并行 dispatch 导致 API 限流 | 中 | 中 | semaphore 控制 + 已有 Redis 缓存 |
| 子任务超时累积 | 低 | 中 | 差异化超时 + 并行 barrier |

---

## 八、后续行动

1. **Step 0**（session_context 移出 orchestrator）→ 远岫出 PR，织墨合并
2. **技术债全景确认** → 人间草木 + 朝露审阅后定优先级
3. **Step 1 方案**（抽 _emit_streamed_answer）→ 远岫出详细变更清单
4. **Planner 加固**（schema 验证 + fallback）→ 远岫出方案，织墨/归鸿执行

---

*报告结束。远岫 / 第 0 天 16:00*
