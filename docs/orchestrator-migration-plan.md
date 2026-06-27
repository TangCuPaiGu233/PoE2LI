# Sprint 2 双运行时统一迁移方案

**背景**：当前 `CHAT_RUNTIME=legacy` 为生产默认，orchestrator 需显式 opt-in。两套运行时并存导致维护成本翻倍、规则漂移风险高。

**目标**：统一到 orchestrator 作为唯一运行时，legacy 仅保留 fallback 直至完全废弃。

---

## 一、Orchestrator 全链路分析

### 1.1 当前架构

```
stream_chat_orchestrator(messages)
    │
    ├── build_session_context(messages)        # 多轮对话锚点
    │
    ├── plan_dispatch(session)                 # LLM planner → DispatchPlan
    │       │
    │       └── llm_plan_dispatch(messages)    # LLM 读取完整对话 → JSON tasks
    │
    ├── dispatch_parallel(tasks, user_msg)     # 并发执行子任务
    │       │
    │       └── run_task(spec, user_msg)       # 单子任务执行
    │               │
    │               └── execute_tool(name, args, ctx)  # 共享工具层
    │
    ├── _build_synthesis_messages(results)     # 打包子任务结果
    │
    └── _emit_streamed_answer(client, messages) # LLM 综合生成回答
```

### 1.2 各层职责与现状

| 层 | 模块 | 职责 | 现状 |
|----|------|------|------|
| 入口 | chat_orchestrator.py | SSE 事件流、session 构建 | ✅ 完整 |
| 规划 | llm_planner.py | LLM 读取对话 → DispatchPlan | ⚠️ JSON 解析弱、fallback 粗糙 |
| 调度 | dispatcher.py | 并发控制、超时、异常捕获 | ✅ 完整 |
| 执行 | runners.py + chat_tools.py | 子任务执行、工具调用 | ✅ 与 legacy 共享 |
| 综合 | chat_orchestrator.py | 子任务结果打包、LLM 综合 | ✅ 完整 |
| 守卫 | chat_response_guard.py + entity_validator.py | 价格声明过滤、实体验证 | ✅ 已独立测试 |

### 1.3 关键优势

1. **并行执行**：多子任务同时跑，比 legacy 串行 ReAct 性能优
2. **结构化中间结果**：SkillAgentResult（Pydantic model）便于处理和调试
3. **确定性注入**：`_merge_pob_task()` 确保 PoB 输入始终被处理，不依赖 LLM planner
4. **错误隔离**：单个子任务失败不影响其他任务

### 1.4 已知不足

| 问题 | 影响 | 优先级 |
|------|------|--------|
| planner JSON 解析无 schema 验证 | LLM 返回格式漂移时静默失败 | P1 |
| fallback 太粗糙（planner 失败 → 单百科） | 丢失 trade/recommend 能力 | P1 |
| 无循环/重复调用检测 | 可能浪费资源 | P2 |
| 超时策略单一（全部 120s） | 某些 agent 可更快超时 | P2 |
| streaming 事件不完整 | 子任务进度不可见 | P2 |

---

## 二、迁移策略：渐进式统一

### Phase 1：规则层对齐（Sprint 2 Week 1）

**目标**：将 legacy 的 36 条 system prompt 规则下沉到 orchestrator

**步骤**：
1. 逐条 review legacy AGENT_SYSTEM 规则
2. 分类映射：
   - 路由规则 → `llm_planner.py:PLANNER_SYSTEM`
   - 工具使用规则 → 各子 agent 的 skill prompt（`backend/app/skills/*.py`）
   - 输出卫生规则 → `chat_orchestrator.py:SYNTHESIS_SYSTEM`
3. 确保无遗漏、无矛盾

**验收**：orchestrator 的 prompts 覆盖 legacy 的所有关键规则

### Phase 2：Planner 加固（Sprint 2 Week 1-2）

**目标**：让 planner 输出更可靠，fallback 更有用

**步骤**：
1. 引入 Pydantic schema 验证 planner 输出
   ```python
   class PlannerOutput(BaseModel):
       tasks: list[TaskSpec]
       reasoning: str
   ```
2. LLM 强制 `response_format={"type": "json_object"}` + schema
3. 验证失败时 retry（最多 2 次）
4. 改进 fallback：
   - 保留 `_merge_pob_task` 的确定性注入
   - fallback 时至少派 `encyclopedia` + `trade_search`（根据用户消息关键词判断）
   - 不再降级到单百科

**验收**：planner JSON 解析失败率 < 1%，fallback 保留多 agent 能力

### Phase 3：Streaming 补齐（Sprint 2 Week 2）

**目标**：orchestrator 的 SSE 事件流与 legacy 同等丰富

**步骤**：
1. 子任务执行时 streaming 中间事件：
   - `sub_agent_start`：子任务开始
   - `sub_agent_done`：子任务完成（已有）
   - `tool_use` / `tool_result`：工具调用和结果
2.  heartbeat 机制（legacy 有，orchestrator 暂无）
3.  错误事件的实时推送

**验收**：前端 UI 能实时显示子任务进度和工具调用

### Phase 4：循环检测与超时优化（Sprint 2 Week 3）

**目标**：提升稳定性和资源效率

**步骤**：
1. 在 `ChatToolContext` 中增加 tool call 历史记录
2. 检测同一工具+相似参数在连续轮次中的重复调用
3. 根据 agent 类型设置差异化超时：
   - `decode_pob`：60s
   - `trade_search`：120s（可能慢）
   - `encyclopedia`：90s
   - `recommend`：60s

**验收**：无重复调用导致的资源浪费

### Phase 5：切换默认运行时（Sprint 2 Week 3）

**目标**：orchestrator 成为生产默认

**步骤**：
1. 将 `CHAT_RUNTIME` 默认值从 `legacy` 改为 `orchestrator`
2. legacy 作为 fallback：orchestrator 连续失败 N 次后自动切换
3. 监控指标：
   - orchestrator 成功率
   - 平均响应时间
   - 子任务并发度

**验收**：生产环境 95%+ 请求走 orchestrator

### Phase 6：Legacy 废弃（Sprint 2 Week 4+）

**目标**：彻底移除 legacy runtime

**步骤**：
1. 确认 orchestrator 成功率稳定 > 98%
2. 移除 `stream_chat_agent()` 及相关代码
3. 清理 legacy 专属的 system prompt 和规则
4. 更新文档

**验收**：代码库中无 legacy runtime 代码

---

## 三、关键技术决策

### 3.1 为什么保留 orchestrator？

| 维度 | Legacy ReAct | Orchestrator |
|------|--------------|--------------|
| 架构意图 | AI 做路由+执行（揉在一起） | AI 做路由，代码做执行（分层清晰） |
| 并行能力 | ❌ 串行工具调用 | ✅ 多子任务并行 |
| 可维护性 | ❌ 36 条规则耦合在 prompt | ✅ 规则分层（planner/skill/synthesis） |
| 可观测性 | ❌ 中间状态不可见 | ✅ 结构化 SkillAgentResult |
| 错误隔离 | ❌ 单点失败影响整轮 | ✅ 子任务独立失败 |
| 规则漂移风险 | ❌ 高（36 条规则交织） | ✅ 低（分层管理） |

### 3.2 规则迁移原则

1. **不复制，重组织**：不是把 legacy prompt 原样搬过去，而是按职责拆分
2. **代码优先**：能代码实现的规则（如 PoB 注入、ilvl 过滤）不放在 prompt 里
3. **prompt 是最后一公里**：prompt 只负责 LLM 的决策，不负责代码的执行

### 3.3 Schema 验证策略

- **Planner 输出**：优先采用 OpenAI structured output / tool calling，让 LLM 原生返回结构化 JSON，避免格式漂移；验证成本为零。备选方案仍保留 Pydantic `PlannerOutput` + `response_format=json_object` 作为 fallback。
- **子任务结果**：已有 `SkillAgentResult` Pydantic model
- **工具参数**：已有 JSON Schema（`TOOL_DEFINITIONS`）
- **最终回答**：已有 post-hoc guards（`strip_ungrounded_price_claims`、`validate_answer`）

---

## 四、风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| orchestrator 成功率低于 legacy | 中 | 高 | 并行期保留 legacy fallback，监控对比 |
| planner JSON 格式漂移 | 中 | 中 | schema 验证 + retry + fallback |
| 并行导致 API 限流 | 中 | 中 | semaphore 控制 + 已有 Redis 缓存 |
| 子任务超时累积 | 低 | 中 | 差异化超时 + 并行 barrier |

---

## 五、依赖关系

```
Phase 1（规则对齐）
    │
    ├──→ Phase 2（Planner 加固）
    │
Phase 2（Planner 加固）
    │
    ├──→ Phase 3（Streaming 补齐）
    │
    ├──→ Phase 4（循环检测）
    │
Phase 3 + Phase 4
    │
    └──→ Phase 5（切换默认）
            │
            └──→ Phase 6（Legacy 废弃）
```

**关键路径**：Phase 1 → Phase 2 → Phase 5 → Phase 6

---

## 六、与 Sprint 1 的衔接

Sprint 1 完成的 guard 测试（R-02、sanitize、entity_validator）在 Sprint 2 中继续发挥价值：
- 规则迁移时，guard 测试确保行为一致
- 切换默认运行时后，guard 测试防止回归
- 双运行时并行期，guard 测试是 cross-check 手段

---

*方案起草：归鸿*  
*时间：项目时间 第 4 天 03:00*
