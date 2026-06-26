# R-01~R-05 集成地图

> 基于 `backend/app/services/chat_agent.py` 实际行号（735 行），标明每个 R 的精确集成位置、前置条件和上下游依赖。
> **本文件仅作集成指南，不修改生产代码。**

---

## 一、R-03：指数退避重试

**目标**：对 plan 阶段和 synthesis 阶段的 LLM 调用增加指数退避重试（3 次，1s/2s/4s）。

### 集成点 1：`_emit_streamed_answer` 函数（Line 332-394）

| 行号 | 当前代码 | 集成动作 |
|------|----------|----------|
| 332-338 | `async def _emit_streamed_answer(...)` | 函数签名不变 |
| 352-394 | stream → non-stream fallback 逻辑 | 将 `client.chat.completions.create(**stream_kwargs)` 和 `client.chat.completions.create(**fb_kwargs)` 替换为 `retry_with_backoff(client.chat.completions.create, **kwargs)` |

**前置条件**：
- `chat_guard.py` 已落地（✅ 已完成）
- `from app.services.chat_guard import retry_with_backoff` 已导入（需添加到 imports）

**上下游依赖**：
- 上游：`_llm_client()` 返回的 AsyncOpenAI client
- 下游：stream synthesis fallback 逻辑保持不变

### 集成点 2：plan 阶段 LLM 调用（Line 477）

| 行号 | 当前代码 | 集成动作 |
|------|----------|----------|
| 477 | `stream = await client.chat.completions.create(**plan_kwargs)` | 可选：将 plan 阶段也接入 `retry_with_backoff` |

**注意**：plan 阶段失败会触发 Line 545-555 的异常处理，直接 yield 错误并 return。接入 retry 后，plan 阶段失败会重试 3 次再进入异常处理。

---

## 二、R-04：连续失败退出

**目标**：工具调用连续失败达到阈值时 abort 循环，反馈给用户。

### 集成点 1：初始化（Line 448-449）✅ 已完成

```python
failure_tracker = ToolFailureTracker()
tool_dedup = ToolLoopDedup()
```

### 集成点 2：循环入口检查（Line 593 之后）

| 行号 | 当前代码 | 集成动作 |
|------|----------|----------|
| 593 | `for tc in tool_calls:` | 循环内第一行插入：<br>`if should_abort_on_failure(fn, failure_tracker): yield {"type": "thinking", "content": "..."}; continue` |

**前置条件**：
- `failure_tracker` 已初始化（✅ 已完成）
- `should_abort_on_failure` 已导入（✅ 已完成）

### 集成点 3：失败记录（Line 620-634）

| 行号 | 当前代码 | 集成动作 |
|------|----------|----------|
| 620 | `except Exception as e:` | 在 `logger.error(...)` 之后插入：<br>`failure_tracker.record_failure(fn)` |

### 集成点 4：成功记录（Line 636 之后）

| 行号 | 当前代码 | 集成动作 |
|------|----------|----------|
| 636 | `preview = result.content[:240] + ...` | 在 preview 之前插入：<br>`failure_tracker.record_success()` |

---

## 三、R-05：循环去重

**目标**：重复工具调用（同一工具 + 相似参数）在连续 2 轮内出现时被拦截。

### 集成点 1：去重检查（Line 602 之后）

| 行号 | 当前代码 | 集成动作 |
|------|----------|----------|
| 602 | `args = _parse_tool_args(tc.function.arguments)` | 在 `args = ...` 之后插入：<br>`if tool_dedup.is_duplicate(fn, args): yield {"type": "thinking", "content": "跳过重复调用: ..."}; continue` |

### 集成点 2：记录历史（Line 636 之后）

| 行号 | 当前代码 | 集成动作 |
|------|----------|----------|
| 636 | `preview = result.content[:240] + ...` | 在 preview 之前插入：<br>`tool_dedup.record(fn, args, tool_round)` |

---

## 四、R-01：三级截断

**目标**：控制 Orchestrator 上下文长度，防止 synthesis 阶段超出 token 预算。

### 集成点 1：Planner 输入控制（`llm_planner.py` Line 85-99）

| 行号 | 当前代码 | 集成动作 |
|------|----------|----------|
| 85-99 | `_conversation_for_planner` 函数 | 增加 token 估算：当 `_estimate_tokens(convo)` 超过阈值时，减少 `max_turns` 或截断更长轮次 |

**文件**：`backend/app/orchestrator/llm_planner.py`

### 集成点 2：子 Agent 结果优先级压缩（`runners.py`）

| 行号 | 当前代码 | 集成动作 |
|------|----------|----------|
| 137 | `context[:12000]` |  encyclopedia/build_design 结果优先保留 `entity_facts`，再保留 chunks |
| 141 | `game_context[:3000]` | 保留 game_graph 结果 |
| 97 | `facts={"trade_payload": json.loads(result.content) ...}` | trade_search 结果优先保留 `best_match` + `listing_price`，`listings` 仅 top-2 |

**文件**：`backend/app/orchestrator/runners.py`

### 集成点 3：Synthesis token 预算控制（`chat_orchestrator.py` Line 175-190）

| 行号 | 当前代码 | 集成动作 |
|------|----------|----------|
| 175 | `synth_messages = _build_synthesis_messages(...)` | 在 `_build_synthesis_messages` 后增加 `_enforce_synthesis_budget(synth_messages, budget=80000)` |

**文件**：`backend/app/services/chat_orchestrator.py`

---

## 五、R-02：声明溯源

**目标**：让 AI 的每个价格/数据声明附带可信来源引用。

### 集成点 1：`source_refs` 字段（`schemas.py` Line 32-64）

| 行号 | 当前代码 | 集成动作 |
|------|----------|----------|
| 32-64 | `SkillAgentResult` 类 | 增加 `source_refs: list[dict[str, Any]] = Field(default_factory=list)` 字段 |

**文件**：`backend/app/orchestrator/schemas.py`

### 集成点 2：子 Agent 填充 source_refs（`runners.py`）

| 行号 | 当前代码 | 集成动作 |
|------|----------|----------|
| 91-101 | `_run_trade` 返回 SkillAgentResult | 构建 `source_refs`：trade listing 价格溯源 |
| 132-146 | `_run_encyclopedia` 返回 SkillAgentResult | 构建 `source_refs`：知识库来源溯源 |
| 177-189 | `_run_build_design` 返回 SkillAgentResult | 构建 `source_refs`：知识库来源溯源 |

**文件**：`backend/app/orchestrator/runners.py`

### 集成点 3：Synthesis 强制引用规则（`chat_orchestrator.py` Line 33-49）

| 行号 | 当前代码 | 集成动作 |
|------|----------|----------|
| 33-49 | `SYNTHESIS_SYSTEM` | 增加 `## 声明溯源规则` 段落：要求 synthesis LLM 引用来源 |

**文件**：`backend/app/services/chat_orchestrator.py`

### 集成点 4：`_verify_price_claims` 硬替换兜底（`chat_orchestrator.py` Line 175-190）

| 行号 | 当前代码 | 集成动作 |
|------|----------|----------|
| 175 | `synth_messages = _build_synthesis_messages(...)` | synthesis 完成后，调用 `_verify_price_claims(answer_acc, results)` 替换未 grounding 的价格声明 |

**文件**：`backend/app/services/chat_orchestrator.py`

---

## 六、依赖关系图

```
R-03 (retry_with_backoff)
  ├── 前置：chat_guard.py 已落地 ✅
  ├── 集成：_emit_streamed_answer (Line 332)
  └── 可选：plan 阶段 (Line 477)

R-04 (ToolFailureTracker)
  ├── 前置：failure_tracker 已初始化 ✅ (Line 448)
  ├── 集成：循环入口检查 (Line 593)
  ├── 集成：失败记录 (Line 620)
  └── 集成：成功记录 (Line 636)

R-05 (ToolLoopDedup)
  ├── 前置：tool_dedup 已初始化 ✅ (Line 449)
  ├── 集成：去重检查 (Line 602)
  └── 集成：记录历史 (Line 636)

R-01 (三级截断)
  ├── 前置：无（不依赖 Step 1A）
  ├── 集成：Planner 输入 (llm_planner.py Line 85)
  ├── 集成：子 Agent 结果压缩 (runners.py Line 137/141/97)
  └── 集成：Synthesis 预算 (chat_orchestrator.py Line 175)

R-02 (声明溯源)
  ├── 前置：无（不依赖 Step 1A）
  ├── 集成：source_refs 字段 (schemas.py Line 32)
  ├── 集成：子 Agent 填充 (runners.py Line 91/132/177)
  ├── 集成：Synthesis 规则 (chat_orchestrator.py Line 33)
  └── 集成：硬替换兜底 (chat_orchestrator.py Line 175)
```

---

## 七、实施顺序建议

| 阶段 | 内容 | 预估工作量 | 依赖 |
|------|------|------------|------|
| 1 | R-03 集成到 `_emit_streamed_answer` | 30 分钟 | chat_guard.py |
| 2 | R-04 集成到工具循环 | 30 分钟 | chat_agent.py Line 593-655 |
| 3 | R-05 集成到工具循环 | 30 分钟 | chat_agent.py Line 602/636 |
| 4 | R-01 Planner 输入控制 | 1 小时 | llm_planner.py |
| 5 | R-01 子 Agent 结果压缩 | 1.5 小时 | runners.py |
| 6 | R-01 Synthesis 预算控制 | 1 小时 | chat_orchestrator.py |
| 7 | R-02 source_refs 字段 + 填充 | 2 小时 | schemas.py + runners.py |
| 8 | R-02 Synthesis 规则 + 硬替换 | 1.5 小时 | chat_orchestrator.py |

**总计**：约 8-9 小时实现 + 测试

---

## 八、与织墨 Step 1A 的交集确认

根据当前方案，**R-01~R-02 的生产代码集成不需要等待 Step 1A**：
- R-01 的 truncation 逻辑在 `llm_planner.py`、`runners.py`、`chat_orchestrator.py` 中独立存在
- R-02 的 source_refs 在 `schemas.py` 和 `runners.py` 中独立存在
- Step 1A (llm_stream.py 抽取) 与 chat_agent.py 的 integration points 无直接交集

人间草木已确认：R-01~R-05 可以基于当前 orchestrator 结构直接实现。

---

*文档结束。*
