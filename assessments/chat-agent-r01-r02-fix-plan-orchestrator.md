# Chat Agent R-01/R-02 修复方案（基于 Orchestrator）

**评估对象**：`backend/app/orchestrator/` + `backend/app/services/chat_orchestrator.py`  
**评估者**：归鸿  
**评估时间**：项目时间 第 0 天  
**任务编号**：AI-02（Sprint 1）续  

**前提**：远岫已决策选 Orchestrator 运行时，废弃 Legacy ReAct。本方案基于 Orchestrator 架构设计。

---

## 一、Orchestrator 上下文管理现状

在深入 R-01/R-02 之前，先梳理 Orchestrator 的现有上下文压缩机制，这是修复方案的基础。

### 1.1 现有压缩点

| 位置 | 机制 | 限制 |
|------|------|------|
| `session_context.py:62-73` | `effective_user_msg()` 截断到 2400 字符 | 工具/子 Agent 输入 |
| `session_context.py:140-157` | `_build_prior_snippet()` 取最近 4 轮，每轮 400 字符，总上限 1200 | 对话历史摘要 |
| `llm_planner.py:85-99` | `_conversation_for_planner()` 取最近 8 轮，每轮 600 字符 | Planner 输入 |
| `runners.py:137,141` | 子 Agent 结果 `context` 截断到 12000 字符 | 单子 Agent 输出 |
| `schemas.py:73-79` | `_short_json()` 截断到 8000 字符 | synthesis block 中的 JSON |

### 1.2 仍存在的膨胀风险

Orchestrator 的上下文膨胀不是线性累积（如 Legacy ReAct），而是**集中式 synthesis 爆发**：
- 一轮可能有 3-5 个子 Agent 并行运行
- 每个子 Agent 返回最多 12000 字符的 context
- 所有结果在 `_build_synthesis_messages` 中合并为单个 user message
- 极端情况：5 个子 Agent × 12000 字符 = 60000 字符 + 系统 prompt + 对话历史 = 可能超过 100K tokens

---

## 二、R-01：超长上下文无截断（Orchestrator 视角）

### 2.1 根因分析（Orchestrator 特定）

在 Orchestrator 架构下，R-01 的根因与 Legacy ReAct 不同：

**Legacy ReAct**：上下文在每轮 tool call 后线性累积，无截断。  
**Orchestrator**：上下文在**synthesis 阶段集中爆发**。子 Agent 结果虽然各自有 12000 字符限制，但多个子 Agent 结果合并后可能超出 synthesis LLM 的 budget。

具体位置：
- `chat_orchestrator.py:175-190` — `_build_synthesis_messages()` 构建 synthesis 输入
- `chat_orchestrator.py:192-200` — `_emit_streamed_answer()` 调用 synthesis LLM
- `runners.py:137,141` — 子 Agent 结果截断点（12000 字符/字段）

**关键发现**：Orchestrator 已经比 Legacy ReAct 有更好的压缩意识（SessionContext + 子 Agent 截断），但缺少**全局 token 预算管理**。

### 2.2 截断策略

**原则**：在 Orchestrator 中，截断应发生在**三个层级**，而非单一入口。

#### 层级 1：子 Agent 结果压缩（已有，需加固）

当前 `runners.py` 对子 Agent 结果有硬截断，但策略过于简单：
- `context[:12000]` — 对 encyclopedia/build_design 的 RAG 上下文
- `_short_json(facts, max_len=4000)` — 对结构化 facts

**改进**：
1. **优先级保留**： encyclopedia/build_design 的 context 应先保留 `entity_facts`（已验证的游戏数据），再保留 chunks。当前顺序是 chunks first，entity_facts 可能被截断。
2. **trade_search 特殊处理**：trade 结果中 `listings` 最占空间。应优先保留 `best_match`、`listing_price`、`explanation`，`listings` 仅保留 top-2 的摘要而非完整对象。
3. **warnings 提升优先级**：warnings 字段应放在 synthesis block 最前面，确保 synthesis LLM 看到。

#### 层级 2：Synthesis 输入预算控制

在 `_build_synthesis_messages` 中引入**总 token 预算**：

```
总预算：SYNTHESIS_TOKEN_BUDGET = 80000 tokens（约 60000 字符）
分配：
  - 系统 prompt：~2000 tokens（固定）
  - 对话历史（prior_snippet）：~3000 tokens（已有 1200 字符限制，约 1000 tokens）
  - 当前用户消息：~1000 tokens
  - 子 Agent 结果：剩余预算按权重分配
    - trade_search：权重 3（价格信息最关键）
    - encyclopedia：权重 2
    - build_design：权重 2
    - recommend：权重 1
    - decode_pob：权重 1
```

**实现方式**：
```python
_SYNTHESIS_TOKEN_BUDGET = 80000
_SYNTHESIS_SYSTEM_TOKENS = 2000
_SYNTHESIS_HISTORY_TOKENS = 3000

def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~1.5 tokens per Chinese char, ~0.7 tokens per ASCII char."""
    if not text:
        return 0
    cn = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    ascii_len = len(text) - cn
    return int(cn * 1.5 + ascii_len * 0.7)

def _budget_for_agent(agent: str, total_remaining: int) -> int:
    weights = {
        "trade_search": 3,
        "encyclopedia": 2,
        "build_design": 2,
        "recommend": 1,
        "decode_pob": 1,
    }
    w = weights.get(agent, 1)
    total_w = sum(weights.values())
    return int(total_remaining * w / total_w)
```

#### 层级 3：Planner 输入控制

`llm_planner.py` 已有 `_conversation_for_planner(max_turns=8)` 和每轮 600 字符限制。但 planner 的输入还包括 `user_block`（对话记录 + 当前轮），总字符数可能达到 5000+。

**改进**：在 planner 输入中增加 token 估算，超过预算时减少 `max_turns` 或截断更长轮次。

### 2.3 与 Orchestrator 消息结构对接

Orchestrator 的消息流与 Legacy ReAct 完全不同，截断策略需要适配：

**Legacy ReAct 消息结构**：
```
system → user → assistant(tool_calls) → tool → assistant(tool_calls) → tool → ... → synthesis
```
截断点：每轮 tool result 后，可丢弃早期轮次。

**Orchestrator 消息结构**：
```
system(planner) → user(对话+当前) 
  → [parallel sub-agents] → results
  → system(synthesis) + user(子 Agent blocks) → stream answer
```
截断点：
1. **Planner 输入**：控制对话历史长度
2. **子 Agent 结果**：控制每个结果的输出长度
3. **Synthesis 输入**：控制总 token 预算

**对接方式**：
- 在 `chat_orchestrator.py` 的 `stream_chat_orchestrator` 中，`_build_synthesis_messages` 后增加 `_enforce_synthesis_budget()` 调用
- 子 Agent 结果的截断在 `runners.py` 的各个 `_run_*` 函数中实现
- 预算参数通过环境变量或配置中心注入，便于调整

### 2.4 具体修改点

| 文件 | 修改点 | 说明 |
|------|--------|------|
| `backend/app/orchestrator/runners.py` | `_run_trade` 中 listings 截断策略 | 优先保留 best_match + listing_price，listings 仅 top-2 |
| `backend/app/orchestrator/runners.py` | `_run_encyclopedia/_run_build_design` 中 context 优先级 | 先保留 entity_facts，再保留 chunks |
| `backend/app/orchestrator/chat_orchestrator.py` | `_build_synthesis_messages` 后增加预算控制 | 估算总 tokens，超限时按权重压缩 |
| `backend/app/orchestrator/llm_planner.py` | `_conversation_for_planner` 增加 token 估算 | 超预算时减少轮次 |

---

## 三、R-02：价格声明无依据 / 幻觉误导（Orchestrator 视角）

### 3.1 根因分析（Orchestrator 特定）

在 Orchestrator 架构下，R-02 的表现形式与 Legacy ReAct 不同：

**Legacy ReAct**：LLM 在 tool loop 中直接生成回答，可能混入未 grounding 的价格。  
**Orchestrator**：synthesis LLM 只根据子 Agent 结果生成回答。问题变成：
1. 子 Agent（特别是 trade_search）已经做了部分过滤（`runners.py:82-83` 的 warnings）
2. 但 synthesis LLM 可能**忽略 warnings**，或基于不完整的 trade_data 推断价格
3. 更隐蔽的幻觉：synthesis LLM 可能将"装备A 售价 5 div"和"装备B 售价 3 div"组合成"这类装备价格在 3-5 div 之间"，而实际上 listing_price 可能只有一个样本

**关键发现**：Orchestrator 的 R-02 风险从"LLM 编造价格"转变为"synthesis LLM 过度推断/合并价格数据"。

### 3.2 声明溯源机制设计

**目标**：让 AI 的每个价格/数据声明附带可信来源引用，用户可验证。

#### 3.2.1 子 Agent 层：结构化来源标记

在 `SkillAgentResult` 中增加 `source_refs` 字段，每个子 Agent 返回时必须标记关键声明的来源：

```python
class SkillAgentResult(BaseModel):
    # ... 现有字段 ...
    source_refs: list[dict[str, str]] = Field(default_factory=list)
    # 示例：[{"type": "trade_listing", "id": "abc123", "field": "listing_price", "value": "5 div"}]
    # 示例：[{"type": "game_graph", "entity": "法师之血", "field": "base_type"}]
```

**trade_search 子 Agent**：
```python
# runners.py _run_trade 中
source_refs = []
if trade_data and trade_data.get("listing_price"):
    source_refs.append({
        "type": "trade_listing",
        "id": best.get("url", "").split("/")[-1][:12],
        "field": "listing_price",
        "value": trade_data["listing_price"].get("display", ""),
        "confidence": "high",  # 来自真实在售标价
    })
else:
    source_refs.append({
        "type": "trade_search",
        "field": "listing_price",
        "value": None,
        "confidence": "none",
        "note": "无在售标价样本",
    })
```

**encyclopedia/build_design 子 Agent**：
```python
# runners.py _run_encyclopedia 中
source_refs = []
for src in (result.sources or [])[:3]:
    source_refs.append({
        "type": src.get("source", "unknown"),
        "preview": src.get("preview", "")[:80],
        "confidence": "high" if src.get("source") in ("poe2db", "poe2wiki") else "medium",
    })
```

#### 3.2.2 Synthesis 层：来源引用强制规则

在 `SYNTHESIS_SYSTEM` 中增加**强制引用规则**：

```
## 声明溯源规则（必须遵守）
1. 任何价格/数值声明必须来自子 Agent 的 source_refs。
2. 引用格式：[来源: trade_listing#abc123] 或 [来源: poe2db]。
3. 如果 source_refs 中某字段的 confidence 为 "none"， synthesis 中禁止输出该字段的具体数值。
4. 综合多个样本时，只能报告"样本价格区间"而非"建议价格"。
5. 子 Agent 的 warnings 必须原样转述给用户，不得忽略。
```

#### 3.2.3 后处理层：硬替换兜底

在 `chat_orchestrator.py` 的 synthesis 后增加**价格声明验证**：

```python
def _verify_price_claims(answer: str, results: list[SkillAgentResult]) -> tuple[str, list[str]]:
    """Verify price claims against source_refs. Return (verified_answer, warnings)."""
    # 1. 提取答案中的价格声明
    price_claims = _extract_price_claims(answer)
    
    # 2. 检查每个声明是否有对应的 source_ref
    verified = answer
    warnings = []
    for claim in price_claims:
        has_source = any(
            ref.get("field") == "listing_price" and ref.get("value") is not None
            for r in results
            for ref in r.source_refs
        )
        if not has_source:
            # 硬替换：删除未 grounding 的价格声明
            verified = _replace_price_claim(verified, claim, "[需市集查询]")
            warnings.append(f"未 grounding 的价格声明已替换: {claim}")
    
    return verified, warnings
```

### 3.3 与 Orchestrator 工具调用机制配合

在 Orchestrator 架构下，工具调用发生在**子 Agent 内部**（`runners.py` 调用 `execute_tool`），synthesis LLM 不直接调用工具。这改变了 R-02 的配合方式：

**Legacy ReAct 配合**：
- tool loop 中 `trade_search` 返回 listing_price
- `strip_ungrounded_price_claims` 在回答生成后检查
- LLM 可能在同一轮中编造价格，后处理拦截

**Orchestrator 配合**：
- 子 Agent 返回结构化 `source_refs`
- Synthesis LLM 只能基于 `source_refs` 生成回答（系统 prompt 强制规则）
- 后处理 `_verify_price_claims` 作为第二道防线
- **关键**：synthesis LLM 不能调用工具，所以价格声明只能来自子 Agent 结果，天然降低了"编造"风险，但"过度推断"风险增加

### 3.4 具体修改点

| 文件 | 修改点 | 说明 |
|------|--------|------|
| `backend/app/orchestrator/schemas.py` | `SkillAgentResult` 增加 `source_refs` 字段 | 结构化来源标记 |
| `backend/app/orchestrator/runners.py` | `_run_trade` 中构建 source_refs | trade listing 价格溯源 |
| `backend/app/orchestrator/runners.py` | `_run_encyclopedia/_run_build_design` 中构建 source_refs | 知识库来源溯源 |
| `backend/app/services/chat_orchestrator.py` | `SYNTHESIS_SYSTEM` 增加溯源规则 | 强制 synthesis LLM 引用来源 |
| `backend/app/services/chat_orchestrator.py` | synthesis 后增加 `_verify_price_claims` | 硬替换兜底 |
| `backend/app/services/chat_response_guard.py` | `strip_ungrounded_price_claims` 保留作为 Legacy 兼容 | Orchestrator 路径改用新机制 |

---

## 四、与 Legacy ReAct 的兼容性

当前系统同时存在 `stream_chat_agent`（Legacy ReAct）和 `stream_chat_orchestrator`（Orchestrator）两个运行时。R-01/R-02 修复应：

1. **优先在 Orchestrator 路径实现**：这是远岫决策的默认运行时
2. **Legacy 路径保持兼容**：不破坏现有 `chat_agent.py` 的逻辑，待运行时统一后再废弃
3. **共享组件提取**：token 估算、价格验证等逻辑提取到独立模块，两个运行时共用

---

## 五、实施建议

| 优先级 | 修改点 | 预估工作量 | 风险 |
|--------|--------|------------|------|
| P0 | R-02: source_refs + synthesis 溯源规则 | 2-3 小时 | 低 — 纯新增字段，不影响现有逻辑 |
| P0 | R-02: _verify_price_claims 硬替换 | 1-2 小时 | 低 — 后处理，不影响上游 |
| P1 | R-01: 子 Agent 结果优先级压缩 | 2-3 小时 | 中 — 需测试不同压缩策略对回答质量的影响 |
| P1 | R-01: Synthesis token 预算控制 | 3-4 小时 | 中 — 需要 token 估算准确性验证 |
| P2 | R-01: Planner 输入 token 控制 | 1-2 小时 | 低 — 已有基础截断，增强即可 |

---

## 六、验收检查清单

- [ ] R-01: `_build_synthesis_messages` 在超过 80000 tokens 时按权重压缩子 Agent 结果
- [ ] R-01: trade_search 子 Agent 结果优先保留 listing_price + best_match，listings 仅 top-2
- [ ] R-01: encyclopedia/build_design 子 Agent 结果优先保留 entity_facts
- [ ] R-02: `SkillAgentResult` 增加 `source_refs` 字段，所有子 Agent 填充
- [ ] R-02: `SYNTHESIS_SYSTEM` 增加强制引用规则
- [ ] R-02: synthesis 后处理 `_verify_price_claims` 替换未 grounding 的价格声明
- [ ] R-02: 用户可见的声明附带来源引用（如 `[来源: 市集#abc123]`）
- [ ]  Legacy ReAct 路径不受影响

---

*报告结束。*
