# R-02 价格声明硬拦截技术方案

**背景**：`chat_response_guard.py` 当前在无 trade listing 时仅对价格断言追加说明，保留原文金额。风险报告判断为高风险：LLM 可能在正文中编造价格区间，用户可能忽略末尾说明。

**目标**：将"软追加"改为"硬替换"，在无 listing 时把具体金额断言替换为占位提示。

---

## 方案 A：正则硬替换（推荐）

**改动点**：`strip_ungrounded_price_claims` 函数内，将价格断言替换为 `[需市集查询]`，而非保留原文 + 追加说明。

**实现**：
```python
def strip_ungrounded_price_claims(text: str, *, had_listing: bool) -> str:
    if had_listing or not text:
        return text
    # 硬替换：把匹配到的价格断言替换为占位符
    return _PRICE_ASSERTION.sub("[需市集查询]", text)
```

**优点**：
- 改动最小，仅改一处
- 彻底消除误导性金额
- 用户看到的是明确提示，而非可忽略的脚注

**缺点**：
- 可能过度替换（如"500 DPS"中的 500 不会被替换，因为无币种后缀，安全）
- 需要确保正则不误伤非价格数字（当前正则已要求币种后缀，安全）

**验证**：当前 26 个测试中，`test_number_without_currency_not_triggered` 和 `test_item_level_not_triggered` 已覆盖 false positive 防护。

---

## 方案 B：合成提示替换

**改动点**：保留原文结构，但将金额数字替换为 `[?]`，并追加统一说明。

```python
def strip_ungrounded_price_claims(text: str, *, had_listing: bool) -> str:
    if had_listing or not text:
        return text
    if not _PRICE_ASSERTION.search(text):
        return text
    replaced = _PRICE_ASSERTION.sub("[?]", text)
    return replaced + "\n\n*以上金额未通过市集验证，仅作参考。*"
```

**优点**：
- 保留原文句式（"大概 [?]"），用户感知更自然
- 追加说明与替换结合，双重保险

**缺点**：
- 仍保留部分原文，用户可能理解为"大概某个价格"
- 需要额外测试覆盖 `[?]` 输出格式

---

## 方案 C：整段屏蔽（不推荐）

**改动点**：如果检测到价格断言，且无 listing，则整段回答前增加免责声明，或直接返回模板化回答。

**不推荐原因**：过于粗暴，会损害用户体验。

---

## 推荐方案与后续

**推荐方案 A**，理由：
1. 改动最小，风险最低
2. 彻底消除误导
3. 与现有测试兼容（只需调整预期断言）

**后续动作**：
1. 修改 `strip_ungrounded_price_claims` 实现
2. 更新 `test_chat_response_guard.py` 中相关测试的预期输出
3. 在 `chat_agent.py` 的 `_sanitize_answer` 阶段或 synthesis prompt 中同步强化规则

**与 Sprint 1 的衔接**：
- 当前 Sprint 1 明确排除 Chat Agent 重构，但 R-02 属于"输出守卫"微调，不涉及架构变更
- 可在 Phase 1b-4 守卫测试完成后，作为同一批次的改进落地

---

*方案起草：归鸿*  
*时间：项目时间 第 1 天 18:30*
