# Chat Agent 风险评估报告

**评估对象**：`backend/app/services/chat_agent.py` + `backend/app/services/chat_tools.py`  
**评估者**：归鸿  
**评估时间**：项目时间 第 1 天 05:30 — 06:00  
**任务编号**：AI-02（Sprint 1）

---

## 评估方法

静态代码阅读 + 路径追踪，不依赖运行环境。重点审查：
- 异常处理完整性
- 资源/预算限制
- 输出卫生（sanitization / grounding）
- 循环终止条件

---

## 风险总览

| # | 风险域 | 风险等级 | 位置 |
|---|--------|----------|------|
| R-01 | 超长上下文无截断 | **高** | `chat_agent.py` `build_agent_messages` / agent_messages 累积 |
| R-02 | 价格声明无依据（幻觉/误导） | **高** | `chat_agent.py` `strip_ungrounded_price_claims` |
| R-03 | LLM 完全失败无重试 | **中** | `chat_agent.py` `_emit_streamed_answer` / stream loop |
| R-04 | 工具调用失败无退出策略 | **中** | `chat_agent.py` tool loop + `chat_tools.py` |
| R-05 | 循环调用检测不足 | **中** | `chat_tools.py` dedup + `chat_agent.py` MAX_TOOL_ROUNDS |
| R-06 | 空回复/无内容输出 | **低** | `chat_agent.py` answer_acc 累积逻辑 |
| R-07 | 流式清洗正则覆盖不全 | **低** | `_sanitize_answer` / `_filter_reasoning_chunk` |

---

## 详细风险分析

### R-01：超长上下文无截断

**现状描述**  
`agent_messages` 在每轮工具调用后累积 assistant entry（含 tool_calls）和 tool result。多轮 ReAct 循环（最多 8 轮）会让上下文线性膨胀。`build_agent_messages` 未对历史长度做硬截断。

**当前处理方式**  
- 隐式依赖 LLM 的 context window 上限
- tool result 通过 `result.content[:240]` 做预览截断，但完整内容仍注入 agent_messages
- 无 token 计数或滑动窗口

**风险等级**：**高**  
**改进建议**：
1. 在 `build_agent_messages` 或 agent loop 入口加入 token 估算 + 滑动窗口截断
2. 旧轮次的 tool result 压缩为摘要而非全量保留
3. 设定硬上限（如 100K tokens），超限时丢弃最早的非必要轮次

---

### R-02：价格声明无依据（幻觉/误导）

**现状描述**  
`strip_ungrounded_price_claims` 在"本轮无 listing_price"时，仅在文本末尾追加说明文字，不删除原文中的具体金额断言。LLM 可能在正文中编造价格区间（如"大概 3-8 崇高"）。

**当前处理方式**  
- 后处理追加说明："本轮未能从市集读取在售标价，以上若含具体金额请忽略"
- 依赖用户阅读到末尾的说明
- 不阻断、不删除原文中的价格断言

**风险等级**：**高**  
**改进建议**：
1. 将"无 listing_price 时的价格断言"替换为占位符（如 `[需市集查询]`），而非保留原文+追加说明
2. 在 synthesis prompt 中强化规则：无 listing_price 时禁止输出任何具体金额
3. 考虑在 `_sanitize_answer` 中增加价格模式匹配，作为更早的拦截点

---

### R-03：LLM 完全失败无重试

**现状描述**  
`_emit_streamed_answer` 对 stream 失败有 fallback 到 non-stream，但 non-stream 本身无重试。`stream_chat_agent` 的 LLM 调用（plan 阶段）无重试，失败直接 yield 错误消息并退出。

**当前处理方式**  
- stream 失败 → non-stream fallback（一次性）
- non-stream 失败 → raise RuntimeError("LLM returned no choices")
- plan 阶段失败 → yield "AI 规划失败: {e}" 并 return

**风险等级**：**中**  
**改进建议**：
1. 对 plan 阶段增加指数退避重试（最多 2-3 次），区分网络错误和模型错误
2. synthesis 阶段同理
3. 重试全部失败时，给出更友好的 fallback（如"AI 服务暂时不可用，请稍后重试"）

---

### R-04：工具调用失败无退出策略

**现状描述**  
tool loop 中单个工具失败会被 catch，记录错误后继续循环。但如果连续多个工具失败，或关键工具（如 decode_pob、trade_search）失败，LLM 可能陷入"继续尝试→继续失败"的循环。

**当前处理方式**  
- 单工具失败 → 记录 error → 继续下一轮
- 失败次数无上限（仅受 MAX_TOOL_ROUNDS = 8 限制）
- 无"连续失败 N 次后 abort"机制

**风险等级**：**中**  
**改进建议**：
1. 在 `ChatToolContext` 中增加 `consecutive_failures` 计数器
2. 连续失败 >= 3 次时 abort 循环，直接 synthesis 或 fallback
3. 对关键工具（decode_pob、trade_search）的失败做单独计数和更快 abort

---

### R-05：循环调用检测不足

**现状描述**  
- `MAX_TOOL_ROUNDS = 8` 是硬轮数上限，但 LLM 可能在 8 轮内重复调用同一工具
- RAG 有 Jaccard dedup，但仅对 rag_search 有效
- trade_search 有每轮上限（8次），但跨轮无 dedup
- 无"同一查询在 N 轮内重复调用"检测

**当前处理方式**  
- RAG：`_check_rag_dedup` 基于 Jaccard similarity > 0.5 拦截
- trade_search：`ctx.trade_search_calls >= TRADE_SEARCH_MAX_PER_TURN` 拦截
- 无跨工具类型、跨轮次的通用循环检测

**风险等级**：**中**  
**改进建议**：
1. 在 `ChatToolContext` 中记录所有 tool call 历史（name + 参数摘要）
2. 当同一工具+相似参数在连续 2 轮内出现时，注入警告并跳过执行
3. 对 trade_search 增加跨轮次 query 相似度检测（防止"换个说法搜同一个东西"）

---

### R-06：空回复/无内容输出

**现状描述**  
如果 LLM 在多轮 tool loop 后返回空 content 且无 tool_calls，`answer_acc` 可能保持空字符串。最终会进入 synthesis 阶段，但 synthesis 的输入可能只有 tool results 无 assistant 文本。

**当前处理方式**  
- `if not tool_calls: break` — 直接退出循环
- 退出后检查 `if answer_acc.strip():` — 有内容则走 sanitize + guard
- 无内容则继续到 synthesis

**风险等级**：**低**  
**改进建议**：
1. 在 break 后增加 `if not answer_acc.strip()` 判断，直接 fallback 到 synthesis 或生成默认回答
2. 确保 synthesis prompt 能在"仅有 tool results 无 assistant 文本"时正常生成回答

---

### R-07：流式清洗正则覆盖不全

**现状描述**  
`_sanitize_answer` 和 `_filter_reasoning_chunk` 使用正则处理 wiki 语法和 DSML XML。正则覆盖了大部分已知模式，但依赖 LLM 输出格式稳定。

**当前处理方式**  
- 正则匹配 `[[...]]`、`[poe:...]`、`|poe:`、DSML XML tags
- 流式 buffer 有 `_safe_flush_point` 避免截断未闭合 pattern
- 无 schema 验证或结构化输出

**风险等级**：**低**  
**改进建议**：
1. 在 system prompt 中明确禁止输出 wiki 语法（而非仅后处理清洗）
2. 考虑对 reasoning content 做更宽松的清洗（允许更多"思考痕迹"）
3. 增加单元测试覆盖边缘 pattern

---

## 跨文件共性观察

1. **无 token 预算意识**：`chat_agent.py` 和 `chat_tools.py` 均不追踪 token 消耗，上下文膨胀是系统性风险
2. **后处理守卫是"软拦截"**：`strip_ungrounded_price_claims` 和 `entity_validator` 都是追加说明/警告，不阻断输出。对于高置信度幻觉（如价格断言），应考虑硬替换
3. **循环终止依赖轮数而非语义**：`MAX_TOOL_ROUNDS = 8` 是唯一硬循环边界，缺少"问题已解决/无法解决"的语义判断

---

## 改进优先级建议

| 优先级 | 风险 | 改进难度 | 影响 |
|--------|------|----------|------|
| P0 | R-02 价格声明无依据 | 低 | 高 — 直接防止误导性输出 |
| P0 | R-01 超长上下文无截断 | 中 | 高 — 防止 OOM / 截断 |
| P1 | R-04 工具失败无退出 | 低 | 中 — 防止无效循环 |
| P1 | R-05 循环调用检测 | 中 | 中 — 防止浪费和死循环 |
| P2 | R-03 LLM 失败重试 | 低 | 中 — 提升可用性 |
| P2 | R-07 清洗正则 | 低 | 低 — 边缘 case |
| P3 | R-06 空回复 | 低 | 低 — 已有基本处理 |

---

## 与 Sprint 1 后续工作的衔接

- **Phase 1b-4（输出守卫单元测试）**：优先为 `strip_ungrounded_price_claims` 和 `_sanitize_answer` 补测试
- **双运行时统一（Sprint 2）**：R-01/R-04/R-05 的改进应同步到 orchestrator runtime
- **测试基建（暮鼓）**：RAG dedup、tool timeout、LLM fallback 都需要 mock 环境验证

---

*报告结束。*
