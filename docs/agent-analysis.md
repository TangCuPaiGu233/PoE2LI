# PoE2LI Agent 现状分析

## 架构概览

三层 Agent 架构：

```
用户消息 → 主 Agent (ReAct loop / LLM Planner)
              ↓
         子 Agent (并行, stateless)
              ↓
         工具层 (Trade API, pgvector, PoB decode, entity lookup)
```

- **主 Agent**: ReAct 循环（默认）或 Orchestrator 模式。LLM 阅读对话，决定调用哪个工具
- **工具层**: `entity_resolve`, `rag_search`, `trade_search`, `decode_pob`, `recommend`, `resolve_trade_stat`
- **LLM**: MiMo-V2.5，OpenAI 兼容协议
- **RAG**: pgvector + BGE-M3 向量检索，~23K chunks（poe2db + poe2wiki + PoB 构建数据）
- **知识图谱**: kb_entities（4,439 个实体） + kb_edges（18,759 条边）

---

## 当前核心问题

### 1. Agent 工具调用失控

**现象**：用户问"帮我配一套召唤女巫的开荒BD"，Agent 在一轮对话中调用 `rag_search` 4-6 次，每次 1.5-2.2 秒，加上每轮 LLM 决策耗时，总响应 76-87 秒。

**根因**：
- ReAct 循环中 LLM 倾向于"再搜一次试试"，用略有不同的英文 rewording 重复搜索同一主题
- 系统 prompt 写了"最多调 3 次 rag_search"但 LLM 不遵守（实测经常 5-6 次）

**已修**：Jaccard 去重（阈值 0.30）+ 软上限 5 次。测试中已拦截近重复查询，但仍会消耗 5 次有效调用。

**未解决**：去重只拦完全相似的 query，Agent 仍然会搜 5 次不同方向（比如搜完"witch summon leveling"再搜"infernalist ascendancy"再搜"skeletal warrior skills"），每次搜回来的 chunk 有重叠噪音。

### 2. LLM 幻觉 / 实体编造

**现象**：Agent 在回答中提到"合金战弩提供魔侍武士的技能"——两个实体都可能不存在或关系是错误的。回答里混入了 PoE1 的技能名（Unearth、Minion Mastery）而非 PoE2 的正确技能。

**根因**：
- RAG 检索回来的 10 chunks 中包含来自 PoB 用户构建数据（source=pob）的 chunk，这些 chunk 里提到了 PoE1 实体名
- LLM 在合成阶段无法区分 chunk 中的"事实"vs"噪音"——它看到某个 chunk 里出现了一个实体名，就直接拿来用
- kb_entities 表有 4,439 个经过验证的实体，但在检索阶段没有被系统地作为"权威实体列表"注入给 LLM

**已修**：`_collect_entity_facts()` —— 检索后从 chunks 中提取实体名，查 kb_entities 获取权威信息，注入到合成 prompt 顶部，并约束 LLM"只引用下方列出的实体属性"。

**未解决**：
- 注入的实体信息来源混杂——很多来自 pob source 而非 poe2db/poe2wiki 官方数据，质量不高
- 约束只存在于 context 文本中，没有在代码层 enforce——LLM 仍然可以忽略约束
- kb_entities 的覆盖率未知——不知道有多少 PoE2 实体在表里

### 3. 检索精度不够

**现象**：同一个主题换英文 phrasing 搜出来的结果差异不大，Agent 浪费多次调用。`structured_entity_lookup`（基于 ILIKE 的精确实体查找）只在 entity chip 请求时才触发，不在 rag_search 流程里主动调用。

**根因**：
- 纯向量检索——缺少精确匹配层（"Rattling Sceptre" 在 kb_entities 里有精确记录，但 rag_search 走的是语义搜索，可能排在靠后位置）
- `concept_links` 扩展有时带来更多噪音——比如搜 witch build 被扩展到 dog/minion 相关概念

**未修**。

### 4. system prompt 臃肿

`AGENT_SYSTEM` 有 31 条规则（~2,000 tokens），每条规则都是经验教训的沉淀（"扭曲项链 vs 畸变项链"、"禁止对百科问题返回泛类目搜索结果"等）。每次 LLM 调用都要在 prompt 里塞这么多规则。规则越多，LLM 遵守每条规则的概率越低。

---

## 困难点

### 1. ReAct 循环的"自主性 vs 可控性"矛盾

Agent 的自主决策（自己选 tool，自己决定搜什么、搜几次）既是核心价值也是核心问题。限制太多变成 keyword router，限制太少变成无限循环。LoopBuster/DriftGuard 这类开源项目提供了检测机制，但本质是外挂——不能从根本上解决 LLM 决策质量的问题。

### 2. RAG 噪声无法避免

向量检索天然有噪声。poe2db/pob/wiki 数据混合，PoE1/PoE2 实体共存，同一个名字在不同上下文含义不同。工业界做法是 reranker + 实体 grounding，但 reranker 增加延迟和成本，entity grounding 依赖 kb_entities 覆盖率。

### 3. 实体库的维护成本

kb_entities 的 4,439 个实体来自自动化爬虫灌库（poe2db scraper、wiki crawler），但没有人工审核流程。哪些实体是 PoE2 的？哪些中文名是正确的？依赖链路不清楚。实体校准需要这个表质量高、覆盖全——但目前质量未知。

### 4. 缺少评测体系

没有标注数据集来量化"幻觉率降低了多少"、"检索精度提升了多少"。所有改进靠肉眼判断。RAGAS、AgentEval 等工具需要先建 eval set，工程量大。

### 5. Orchestrator 模式未充分使用

当前默认用 legacy ReAct，而 orchestrator（LLM Planner → 并行 dispatch → synthesis）的设计意图是减少连续的 ReAct 往返。但 Planner 本身也是 LLM 调用，也会出错。两种模式各有利弊，没有 A/B 对比数据。

---

## 近期改动摘要

| 改动 | 文件 | 效果 |
|------|------|------|
| LLM 客户端统一工厂 | `core/llm_client.py` | 所有 LLM 调用走统一出口，可切换 Langfuse 追踪 |
| 工具去重 | `chat_tools.py` | Jaccard 0.30 拦截近重复 rag_search |
| 实体校准 | `chat_tools.py` | 检索结果注入 kb_entities 权威信息 |
| DB league/version 修复 | NAS 直修 | 23K chunks + 12 builds 补齐元数据 |
| 灌库脚本修复 | 5 个脚本 | 防止未来 league/version 再次丢失 |

---

## 建议优先探索方向

1. **Agent eval set**：收集 20-50 个典型用户问题 + 期望答案，建立自动化回归
2. **检索流水线加 reranker**：BGE reranker 在向量检索后重排，降低噪音
3. **Orchestrator 模式压测**：对比 legacy 和 orchestrator 在幻觉率、延迟上的差异
4. **实体库质量审计**：抽查 kb_entities 中 item/skill 类型的实体，评估覆盖率和准确率
5. **system prompt 瘦身**：31 条规则 → 5-8 条核心原则，非核心规则移到 skill 级别
