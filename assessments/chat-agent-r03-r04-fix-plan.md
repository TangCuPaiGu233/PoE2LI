# Chat Agent 诊断报告 + R-03/R-04 修复方案

**评估对象**：`backend/app/services/chat_agent.py` + `backend/app/services/chat_tools.py`  
**评估者**：归鸿  
**评估时间**：项目时间 第 0 天  
**任务编号**：AI-02（Sprint 1）续  

---

## 一、诊断总览

| 编号 | 风险域 | 风险等级 | 根因摘要 | 修复优先级 |
|------|--------|----------|----------|------------|
| R-01 | 超长上下文无截断 | **高** | agent_messages 在多轮 ReAct 中线性累积，无 token 预算意识 | P0 |
| R-02 | 价格声明无依据（幻觉/误导） | **高** | `strip_ungrounded_price_claims` 仅追加说明，不删除原文金额断言 | P0 |
| R-03 | LLM 完全失败无重试 | **中** | plan / synthesis 阶段的 LLM 调用无重试，失败直接退出 | P1 |
| R-04 | 工具调用失败无退出策略 | **中** | 单工具失败后继续循环，无连续失败计数和 abort 机制 | P1 |
| R-05 | 循环调用检测不足 | **中** | 仅 RAG 有单工具去重，跨轮次、跨工具类型无通用循环检测 | P1 |

---

## 二、逐条诊断

### R-01：超长上下文无截断

**根因分析**  
`chat_agent.py` 的 ReAct 循环中，每轮 assistant entry（含 tool_calls）和 tool result 都被完整追加到 `agent_messages`。`MAX_TOOL_ROUNDS = 8` 允许最多 8 轮工具调用，上下文随轮数线性膨胀。当前处理方式：
- tool result 通过 `result.content[:240]` 做预览截断，但完整 `result.content` 仍被注入 `agent_messages`
- 无 token 计数、无滑动窗口、无旧轮次压缩

**影响范围**  
- 多轮复杂查询（如先 decode_pob 再 rag_search 再 trade_search）极易超过 64K-128K token 预算
- 超过 LLM context window 时会被静默截断，导致早期工具结果丢失、回答质量骤降
- 长上下文也显著增加 API 延迟和成本

**当前代码位置**  
- `chat_agent.py:449` — `agent_messages = build_agent_messages(...)`
- `chat_agent.py:575-585` — assistant entry 追加
- `chat_agent.py:646-652` — tool result 追加（完整 `result.content`）

**修复方案**  
1. **Token 估算 + 硬截断**：在每轮循环入口估算 `agent_messages` 的 token 数（可用 `len(json.dumps(messages)) / 4` 近似或引入 tiktoken）。设定硬上限（如 100K tokens），超限时丢弃最早的非必要轮次。
2. **旧轮次摘要化**：超过 4 轮后，将前 1-3 轮的 tool result 压缩为 1-2 句摘要，保留关键结论而非全量文本。
3. **滑动窗口**：保留最近 3-4 轮的完整上下文，更早的轮次仅保留摘要或最相关片段。

---

### R-02：价格声明无依据（幻觉/误导）

**根因分析**  
`strip_ungrounded_price_claims` 在"本轮无 listing_price"时，仅在文本末尾追加说明文字（如"本轮未能从市集读取在售标价，以上若含具体金额请忽略"），不删除原文中的具体金额断言。LLM 可能在正文中编造价格区间（如"大概 3-8 崇高"），用户如果没看到末尾说明就会被误导。

**影响范围**  
- 用户可能根据 AI 编造的价格做出错误的交易决策
- 这是信任类风险：一次严重幻觉就可能让用户不再信任整个系统
- 当前 system prompt 已有规则（规则 15/19），但后处理守卫是"软拦截"，LLM 仍然可以输出金额

**当前代码位置**  
- `chat_agent.py:658, 674, 714` — `strip_ungrounded_price_claims` 调用点
- `chat_agent.py:238-243` — system prompt 中的价格规则
- `chat_response_guard.py` — 守卫实现（需确认当前逻辑）

**修复方案**  
1. **硬替换而非追加说明**：当 `had_listing=False` 时，用正则将正文中的价格模式（数字+货币单位）替换为 `[需市集查询]`，而非保留原文+追加说明。
2. **synthesis prompt 强化**：在 synthesis 阶段明确要求"无 listing_price 时禁止输出任何具体金额，包括区间估算"。
3. **早期拦截**：在 `_sanitize_answer` 中增加价格模式匹配，作为更早的拦截点。

---

### R-03：LLM 完全失败无重试

**根因分析**  
`_emit_streamed_answer` 对 stream 失败有 fallback 到 non-stream，但 non-stream 本身无重试。`stream_chat_agent` 的 plan 阶段 LLM 调用无重试，失败直接 yield 错误消息并退出。偶发网络抖动、模型服务波动都会导致用户看到"AI 规划失败"。

**影响范围**  
- 可用性下降：用户一次请求失败就需要重试
- 无区分网络错误和模型错误：5xx 应该重试，4xx 不应该
- 无降级方案：全部失败后直接报错，无友好 fallback

**当前代码位置**  
- `chat_agent.py:331-393` — `_emit_streamed_answer`（stream → non-stream fallback，无重试）
- `chat_agent.py:460-552` — plan 阶段 stream 调用，异常直接 yield 错误并 return

**修复方案 — 详细设计**  
**目标**：对 plan 和 synthesis 阶段的 LLM 调用增加指数退避重试，区分可重试错误和不可重试错误。

**重试策略**：
```
最大重试次数：3 次（含首次）
退避间隔：1s → 2s → 4s（指数退避）
重试触发条件：
  - 网络超时（Timeout, ConnectionError）
  - 服务端错误（5xx, ServiceUnavailable）
  - 空响应（no choices）
不重试条件：
  - 认证失败（401, 403）
  - 请求非法（400, 422）
  - 模型不存在（404）
  - 内容过滤（ContentFilterError）
```

**伪代码**：
```python
async def _llm_call_with_retry(client, messages, **kwargs):
    max_retries = 3
    base_delay = 1.0
    
    for attempt in range(max_retries):
        try:
            return await client.chat.completions.create(
                model=kwargs.get("model", _model()),
                messages=messages,
                **{k: v for k, v in kwargs.items() if k != "model"}
            )
        except _RETRYABLE_ERRORS as e:
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning("[CHAT] LLM call failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1, max_retries, delay, e)
                await asyncio.sleep(delay)
            else:
                raise
        except _NON_RETRYABLE_ERRORS:
            raise
    
    raise RuntimeError("LLM call exhausted retries")
```

**降级方案**：  
全部重试失败时，返回用户友好的 fallback 消息："AI 服务暂时不可用，请稍后重试。如问题持续，请检查网络连接或联系管理员。" 不暴露内部异常细节。

---

### R-04：工具调用失败无退出策略

**根因分析**  
tool loop 中单个工具失败会被 catch，记录错误后继续循环。但如果连续多个工具失败，或关键工具（如 decode_pob、trade_search）失败，LLM 可能陷入"继续尝试→继续失败"的循环。当前仅受 `MAX_TOOL_ROUNDS = 8` 限制，但 8 轮内仍可能大量无效尝试。

**影响范围**  
- 用户等待时间被无效循环拉长
- 关键工具失败后，后续轮次继续调用同一工具浪费配额
- 无"连续失败 N 次后 abort"机制

**当前代码位置**  
- `chat_agent.py:607-631` — tool execution + error handling
- `chat_agent.py:588-597` — rag_search 批内去重（但无跨轮次失败计数）
- `chat_tools.py` — `execute_tool` 分发（需确认是否有超时）

**修复方案 — 详细设计**  
**目标**：在 ChatToolContext 中增加失败计数，连续失败达到阈值时 abort 循环并进入 synthesis/fallback。

**状态转移逻辑**：

```
状态机：
  IDLE → [工具调用] → SUCCESS / FAILURE
  SUCCESS → 重置连续失败计数 → 继续下一轮
  FAILURE → 增加连续失败计数
    → 连续失败 < 3: 继续循环
    → 连续失败 >= 3: ABORT → 进入 synthesis 或 fallback
    
关键工具特殊处理：
  - decode_pob: 连续失败 2 次即 abort（输入通常是固定链接，重试无意义）
  - trade_search: 连续失败 3 次 abort，但允许下一轮再尝试（可能是临时网络问题）
```

**伪代码**：
```python
# 在 ChatToolContext 中新增
consecutive_failures: int = 0
critical_tool_failures: dict[str, int] = field(default_factory=dict)

# 在 tool loop 中
try:
    result = await execute_tool(fn, args, ctx)
    ctx.consecutive_failures = 0  # 成功则重置
except Exception as e:
    ctx.consecutive_failures += 1
    ctx.critical_tool_failures[fn] = ctx.critical_tool_failures.get(fn, 0) + 1
    
    # 关键工具快速 abort
    if fn in ("decode_pob",) and ctx.critical_tool_failures[fn] >= 2:
        yield {"type": "thinking", "content": f"{fn} 连续失败，跳过..."}
        continue  # 或 break
    
    # 通用连续失败 abort
    if ctx.consecutive_failures >= 3:
        yield {"type": "thinking", "content": "连续多次工具调用失败，将基于已有信息回答..."}
        break  # 退出 tool loop，进入 synthesis
```

**用户提示**：  
abort 时在 thinking 中告知用户"部分工具调用失败，将基于已有信息回答"，不暴露内部错误细节。

---

### R-05：循环调用检测不足

**根因分析**  
- `MAX_TOOL_ROUNDS = 8` 是硬轮数上限，但 LLM 可能在 8 轮内重复调用同一工具
- RAG 有 Jaccard dedup（`_check_rag_dedup`），但仅对 `rag_search` 有效
- `trade_search` 有每轮上限（8次），但跨轮无 dedup
- 无"同一查询在 N 轮内重复调用"检测

**影响范围**  
- LLM 可能通过"换个说法搜同一个东西"绕过 trade_search 的每轮上限
- 浪费 API 配额，增加延迟
- 用户体验：看到重复的"调用工具: 交易搜索..."

**当前代码位置**  
- `chat_tools.py:85-95` — `_check_rag_dedup`（仅 rag_search）
- `chat_tools.py:43-57` — `ChatToolContext`（无通用 tool call 历史）
- `chat_agent.py:588-597` — rag_search 批内去重

**修复方案**  
1. **通用 tool call 历史**：在 `ChatToolContext` 中增加 `tool_call_history: list[dict]`，记录每轮的工具名和参数摘要。
2. **跨轮次重复检测**：当同一工具 + 相似参数在连续 2 轮内出现时，注入警告并跳过执行。
3. **trade_search 跨轮次 query 相似度**：对 trade_search 的 query 做 Jaccard 检测，防止"换个说法搜同一个东西"。

**伪代码**：
```python
# ChatToolContext 新增
tool_call_history: list[dict] = field(default_factory=list)

# 在 tool loop 中，执行前检查
def _is_duplicate_tool_call(fn: str, args: dict, ctx: ChatToolContext) -> bool:
    if not ctx.tool_call_history:
        return False
    last = ctx.tool_call_history[-1]
    if last["fn"] != fn:
        return False
    # 对 trade_search 做 query 相似度
    if fn == "trade_search":
        prev_query = last.get("args", {}).get("query", "")
        curr_query = args.get("query", "")
        if _query_jaccard(prev_query, curr_query) > 0.6:
            return True
    # 对其他工具，参数完全相同即重复
    return last.get("args") == args

# 执行前
if _is_duplicate_tool_call(fn, args, ctx):
    yield {"type": "thinking", "content": f"跳过重复调用: {TOOL_LABELS.get(fn, fn)}"}
    continue

# 执行后记录
ctx.tool_call_history.append({"fn": fn, "args": args, "round": tool_round})
```

---

## 三、跨风险共性观察

1. **无 token 预算意识**：R-01 的上下文膨胀问题说明当前系统对 token 消耗没有全局感知。建议引入轻量级 token 计数器（近似即可），在 agent loop 入口做预算检查。
2. **后处理守卫是"软拦截"**：R-02 的价格声明问题本质是"拦截不够硬"。对于高置信度幻觉（如价格断言），应考虑硬替换而非追加说明。
3. **循环终止依赖轮数而非语义**：R-04 和 R-05 都暴露出"8 轮上限"是唯一的硬边界，缺少"问题已解决/无法解决"的语义判断。建议在循环出口增加语义检查（如 LLM 是否已生成完整回答、关键工具是否已成功调用）。

---

## 四、与后续工作的衔接

- **双运行时统一（远岫负责）**：R-03/R-04/R-05 的改进应同步到 orchestrator runtime，确保两个运行时的行为一致。
- **测试基建（来迟负责）**：R-03 重试逻辑、R-04 失败计数、R-05 去重逻辑都需要 mock 环境验证。建议来迟在测试框架中提供 LLM mock 和 tool mock。
- **R-01 上下文截断**：需要与 embedding 服务配合，确保截断后仍保留足够信息用于检索和回答。

---

## 五、实施建议（按优先级）

| 优先级 | 风险 | 预估工作量 | 建议实施顺序 |
|--------|------|------------|--------------|
| P0 | R-02 价格声明无依据 | 1-2 小时 | 第 1 个做 — 快速 win，防止误导 |
| P0 | R-01 超长上下文无截断 | 4-6 小时 | 第 2 个做 — 高影响但需谨慎测试 |
| P1 | R-04 工具失败无退出 | 2-3 小时 | 第 3 个做 — 改动小，收益明确 |
| P1 | R-05 循环调用检测 | 3-4 小时 | 第 4 个做 — 与 R-04 可并行 |
| P2 | R-03 LLM 失败重试 | 2-3 小时 | 第 5 个做 — 需确认 LLM client 的异常层次 |

---

*报告结束。*
