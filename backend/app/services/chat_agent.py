"""Chat agent runtime — ClawCode-style ReAct loop: AI chooses tools, scripts execute."""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import AsyncIterator
from typing import Any

import asyncio

from app.core.llm_config import LLM_MODEL, llm_thinking_extra_body
from app.core.llm_client import get_async_llm_client
from app.core.game_context import POE2_SITE_RULE
from app.orchestrator.session_context import build_session_context
from app.services.chat_multimodal import build_agent_messages, message_has_images, resolve_user_text
from app.services.follow_up_suggestions import generate_follow_up_questions

from app.services.chat_tools import (
    RAG_SOFT_LIMIT,
    SEARCH_GAME_MAX_PER_TURN,
    TOOL_DEFINITIONS,
    TOOL_LABELS,
    ChatToolContext,
    detect_input_signals,
    execute_tool,
)
from app.services.entity_validator import validate_answer
from app.services.observability import flush, trace_chat_turn

logger = logging.getLogger(__name__)


def _save_chat_history(messages: list[dict], user_msg: str, answer: str, ctx, reasoning: str = "") -> None:
    """Persist chat turn to chat_history table."""
    try:
        import json, hashlib, psycopg2
        # Use hash of first user message as thread_id, stable across multi-turn
        first_user = ""
        for m in (messages or []):
            if m.get("role") == "user":
                first_user = m.get("content", "")
                if isinstance(first_user, list):
                    first_user = str(first_user[0].get("text", "")) if first_user else ""
                break
        thread_id = hashlib.md5((first_user or user_msg)[:200].encode()).hexdigest()[:12]
        db_url = os.getenv("DATABASE_URL", "postgresql://poe2li:poe2li_secret@postgres:5432/poe2li")
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        tool_info = []
        if hasattr(ctx, 'rag_queries') and ctx.rag_queries:
            tool_info.append({"type": "rag_queries", "queries": ctx.rag_queries})
        if ctx.last_sources:
            tool_info.append({"type": "sources", "count": len(ctx.last_sources),
                              "previews": [s.get("preview","")[:80] for s in ctx.last_sources[:3]]})
        tools_json = json.dumps(tool_info, ensure_ascii=False) if tool_info else None
        cur.execute(
            "INSERT INTO chat_history (thread_id, role, content, tool_calls) VALUES (%s, 'user', %s, NULL)",
            (thread_id, user_msg[:5000])
        )
        cur.execute(
            "INSERT INTO chat_history (thread_id, role, content, tool_calls, reasoning) VALUES (%s, 'assistant', %s, %s, %s)",
            (thread_id, answer[:10000], tools_json, reasoning[:5000] if reasoning else None)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.warning("[CHAT] save chat_history failed: %s", e)


def _validate_answer_entities(answer: str, ctx) -> list[dict]:
    """Post-hoc entity validation: scan answer against retrieval evidence."""
    try:
        evidence = getattr(ctx, "last_chunks", None) or []
        return validate_answer(answer, evidence_texts=list(evidence))
    except Exception as e:
        logger.warning("[CHAT] entity validation failed: %s", e)
        return []

MAX_TOOL_ROUNDS = 8
TRADE_SEARCH_MAX_PER_TURN = int(os.getenv("CHAT_TRADE_SEARCH_MAX", "8"))

# Patterns for sanitizing LLM output
# Handle both fullwidth ｜ (U+FF5C) and ASCII | (U+007C), with optional spaces
_TOOL_CALL_XML_RE = re.compile(r'<\s*[｜|]\s*DSML\s*[｜|][^>]*>.*?</\s*[｜|]\s*DSML\s*[｜|][^>]*>', re.DOTALL)
# Also match unclosed / standalone opening tags (e.g. <｜DSML｜tool_calls> with no closing)
_TOOL_CALL_XML_OPEN_RE = re.compile(r'<\s*[｜|]\s*DSML\s*[｜|][^>]*/?\s*>', re.DOTALL)
_WIKI_LINK_RE = re.compile(r'\[\[(?:poe:)?([^|\]]+)\|([^\]]+)\]\]')  # [[poe:X|Y]] or [[X|Y]] → Y
_WIKI_BRACKET_RE = re.compile(r'\[poe:([^\]|\n]+?)(?:\|[^\]|\n]+?)?\]')  # [poe:X] → X, [poe:X|Y] → X
# Unclosed [poe:Name... without closing ] — split across table cells or truncated by LLM
_WIKI_ORPHAN_RE = re.compile(r'\[poe:([^|\n\]]+)')  # **[poe:法师之血** → **法师之血**
_WIKI_PIPE_RE = re.compile(r'\|poe:')  # stray |poe: tags


def _sanitize_answer(text: str) -> str:
    """Strip wiki syntax and tool-call XML leaks from LLM output."""
    if not text:
        return text
    # Remove raw tool call XML (e.g. <｜DSML｜tool_calls>...</｜DSML｜tool_calls>)
    text = _TOOL_CALL_XML_RE.sub('', text)
    text = _TOOL_CALL_XML_OPEN_RE.sub('', text)
    # Convert wiki links [[page|display]] → display
    text = _WIKI_LINK_RE.sub(r'\2', text)
    # Convert single-bracket [poe:name] or [poe:name|en] → name
    text = _WIKI_BRACKET_RE.sub(r'\1', text)
    # Catch remaining unclosed [poe:Name fragments (split across table cells by |)
    text = _WIKI_ORPHAN_RE.sub(r'\1', text)
    # Remove stray |poe: fragments
    text = _WIKI_PIPE_RE.sub('', text)
    return text.strip()


def _sanitize_reasoning(text: str) -> str:
    """Strip tool-call XML and wiki syntax from reasoning/thinking content (shown in UI)."""
    if not text:
        return text
    text = _TOOL_CALL_XML_RE.sub('', text)
    text = _TOOL_CALL_XML_OPEN_RE.sub('', text)
    text = _WIKI_LINK_RE.sub(r'\2', text)
    text = _WIKI_BRACKET_RE.sub(r'\1', text)
    text = _WIKI_ORPHAN_RE.sub(r'\1', text)
    text = _WIKI_PIPE_RE.sub('', text)
    return text.strip()


# Regex to detect tool-call XML tags (handles fullwidth ｜ and ASCII |, optional spaces)
_TOOL_TAG_RE = re.compile(r'<\s*[｜|]\s*DSML\s*[｜|][^>]*>')
_TOOL_TAG_CLOSE_RE = re.compile(r'</\s*[｜|]\s*DSML\s*[｜|][^>]*>')

def _filter_reasoning_chunk(
    text: str, in_tool_xml: bool, partial: str
) -> tuple[str, bool, str]:
    """Filter tool-call XML from a streaming reasoning chunk.

    Returns (clean_text, still_in_tool_xml, leftover_partial).
    Strips everything between <...DSML...> and </...DSML...> tags.
    """
    combined = partial + text
    if not combined:
        return "", in_tool_xml, ""

    result_chars: list[str] = []
    i = 0
    while i < len(combined):
        ch = combined[i]
        if in_tool_xml:
            # We're inside a DSML block — suppress everything until we find
            # the closing </｜DSML｜...> or </...DSML...>
            m = _TOOL_TAG_CLOSE_RE.search(combined, i)
            if m:
                # Found closing tag — skip to after it
                i = m.end()
                in_tool_xml = False
            else:
                # No closing tag in this chunk — suppress everything
                return "".join(result_chars), True, ""
        elif ch == '<':
            # Check for opening DSML tag: <｜DSML｜...> or <|DSML|...>
            rest = combined[i:]
            tag_match = _TOOL_TAG_RE.match(rest)
            if tag_match:
                # Found complete opening tag — skip it and enter suppression mode
                i += tag_match.end()
                in_tool_xml = True
            elif len(rest) <= 25 and any(
                rest.startswith(pfx)
                for pfx in ('<|', '<｜', '< |', '< ｜', '<|D', '<｜D', '< |D', '< ｜D',
                            '<| D', '<｜ D', '< | D', '< ｜ D')
            ):
                # Possible partial opening tag at end — buffer it for next chunk
                return "".join(result_chars), in_tool_xml, rest
            else:
                result_chars.append(ch)
                i += 1
        else:
            result_chars.append(ch)
            i += 1

    return "".join(result_chars), in_tool_xml, ""


def _is_tool_call_only(text: str) -> bool:
    """Check if the text is entirely tool-call XML (no real answer content)."""
    if not text or not text.strip():
        return False
    cleaned = _TOOL_CALL_XML_RE.sub('', text).strip()
    return len(cleaned) < 10  # only whitespace/trivial text left

AGENT_SYSTEM = """你是「流放漓」Path of Exile 2 智能助手。""" + POE2_SITE_RULE + """

## 游戏数据验证（最高优先级）
- 你的训练数据中关于 PoE2 的信息大量来自 PoE1，**极不可靠**。
- 涉及以下主题时，**必须首先调用 search_game** 查证（在 entity_resolve 和 rag_search 之前）：
  职业、升华、天赋节点、技能宝石、物品基底、词缀、暗金、怪物、机制
- **只要用户消息中提到具体职业名、升华名、技能名**（如"战士"、"灵魂行者"、"女巫召唤"），即使是问开荒/BD/攻略等策略问题，也**必须先 search_game** 查证这些实体的游戏数据。
- **search_game 是权威游戏数据源**，查不到就意味着该实体在 PoE2 中可能不存在。
- 如果 search_game 返回"未找到"，**必须明确告知用户**该内容在 PoE2 当前版本中不存在，绝不可用训练数据补充或编造。
- search_game 返回的中文名是官方翻译，引用时**必须使用**。

## 工作方式（必须遵守）
0. 没有服务端强制路由或专用流水线；所有查价/搜索/检索都由你自主调用工具完成。
1. 你是编排者：先判断用户意图，再调用工具获取事实，最后基于工具结果用中文回答。
2. 不要在没有调用工具的情况下编造物品、技能数值、BD 数据或交易链接。
3. 用户消息若含 PoB 分享码(eN开头)、pobb.in 或 poe.ninja 或 wegame.com.cn/helper/poe2 分享链接 → 必须先调用 decode_pob。
4. 百科/机制/技能/物品问题 → **先 search_game**（查证游戏数据），再 entity_resolve（如有中文专名），再 rag_search。**search_game 必须使用用户的语言**：当前用户是国服中文，所以用中文关键词搜索（如搜"光环"不搜"aura"，搜"野兽"不搜"beast"）。只有中文搜索无结果时才用英文 fallback。不要重复调用。
5. 找装备/市价/交易 → trade_search（detail_count 1-10 控制返回前 N 条完整 listing；问价通常 1-3，对比可 2-5）。
6. 「哪个更好/推荐/对比」→ recommend。
7. **多物品市价列表**（用户一次问多个装备/暗金分别多少钱）：逐个调用 trade_search，每查完一个物品先输出该物品报价，全部完成后再给汇总；不要在一次 trade_search 里混查多个物品。
8. 可连续调用多个工具；当前问题与历史无关时（例如仅贴链接），不要沿用上一轮话题。
9. 工具失败时如实告知用户（例如 poe.ninja 角色不存在、链接失效）。
10. plan_and_search 的 subqueries 最多 3 个英文短语，从不同角度覆盖用户问题。如需先解析中文实体名，写入 entities 字段。大多数问题调用一次 plan_and_search 即可，不要重复调用。
11. **poe.ninja BD 造价（无链接）**：用户提到忍者网/poe.ninja 并询问 BD 造价，但消息里没有 poe.ninja 角色链接、PoB 码等可解析构建输入时，直接说明如何复制并粘贴链接，不要调用 decode_pob 或 BD 造价流水线。
12. **WeGame 分享链接**：`stats:` 行含 Life/FireRes/LightningRes 等时，即 WeGame 面板数据，**必须原样引用**（火/冰/闪抗即元素抗性，闪电抗勿改称「魔抗」）。仅当含 `data_limitation` 时才禁止编造面板数值。WeGame 无升华字段。
14. **用户附图**：消息可能含 PoE2 游戏截图（装备、天赋、技能、市集等）。先描述图中可见内容，再结合工具/知识库回答；看不清的数值如实说明，不要编造。
15. **估价/值多少钱**：只能引用 trade_search 返回的 `listing_price.display`；若无 listing_price 或 price_note 说无在售，必须明确「无法从市集估价」，**禁止**编造具体金额区间（如 3-8 崇高、建议挂 5E 等）。
16. **trade_search 的 query**：只写词缀/装备类型/暗金名；**不要**把截图里的物品等级(物等/ilvl)写进 query，除非用户原话明确要求物等条件。
17. **trade_search 次数**：多物品/多变体比价时逐项调用；同一件装备避免无意义重复搜索。
18. **暗金查价**（人格分裂、猎首等）：trade_search 的 query **只写暗金名**，不要加红玉/蓝玉基底或无关词缀描述。
19. **追问价格/其他变体词缀**：仍须 trade_search；结合对话里的物品名构造 query，禁止不查市集就报具体价格。
20. **多词条/多变体分别比价**（「不同词条分别多少钱」「各词缀价格对比」）：每条 query **只含一个词条或一种变体**，逐项调用 trade_search；全部搜完后用 markdown 表格或列表**汇总**，禁止把多个词条塞进一次搜索，禁止未搜索就报各词条价格。

21. **词缀解析/归一化**：装备或词缀搜索前，先理解用户提到的抗性/伤害/召唤等级/移速等，写成标准中文词缀名，再 `resolve_trade_stat(canonical_label=...)`；`canonical_label` **不得**包含数值后缀（如 +4、15% 等），数值只写在 operator/value 或用户说明中；禁止把口语/缩写原样传入。
22. **歧义处理**：若 `need_disambiguation` 为 true，结合 suggestions 与上下文选定 stat_id 并说明理由，再调用 `trade_search`。
23. **trade_search query 用词**：`trade_search` 的 query 必须使用已确认的 `text_cn`（来自 resolve 的 best 或你选定的那条 suggestion）。

## 多轮对话（必读历史，工具参数由你构造）
24. 当前句很短或含「这个/这件/上面/差不多/同款」而**未重复描述装备** → 必须从对话历史还原物品再 `trade_search`，禁止用「值多少钱」等当 query。
25. 用户纠正搜索（「不是珠宝」「别搜蓝玉」）→ 根据历史中真实装备类型/词缀**重新** `trade_search`；纠正句只作说明，不要当搜索词。
26. 「如何搭配/配装/怎么配/装备选择」→ 先 `search_game`（查职业/升华/技能数据），再 `entity_resolve` + `rag_search`，由你分析配装；**不要**用 `recommend`（`recommend` 仅用于用户明确对比多个具名装备「哪个更好」）。
27. 附图 + 问价：先描述图中装备，再 `trade_search`；query 写词缀/类型，不要把纠正或情绪句塞进 query。
28. 规划工具时默认**已阅读**上方完整对话；同一轮可先 `rag_search` 再 `trade_search`，顺序由你决定。
29. **扭曲项链 vs 畸变项链**：国服 Trade 译名中 **扭曲项链=Distorted Amulet**（普通基底词缀池），**畸变项链=Twisted Amulet**（Delirium 涂油/Instilled 底）。用户说「扭曲项链」且未提涂油时，按 Distorted Amulet 检索；涂油/Instilled/扭曲护身符才指 Twisted Amulet。
30. **物品百科 vs 市集**：仅物品/基底名、或问「词条/词缀/能出什么/介绍/是什么」→ **必须** `search_game` + `entity_resolve` + `rag_search`；**禁止** `trade_search`（除非用户明确要搜装备/查价/多少钱）。检测信号含 `bare_item_name` 或 `item_knowledge_query` 时遵守本条。
31. 若仍调用 `trade_search` 且 query 含基底名，query **只写基底 CN 名**（如「扭曲项链」），服务端会自动加 `type` 过滤；不要对百科问题返回泛类目搜索结果。
32. **search_game 效率**：同一主题最多调用 **3 次** search_game（如：中文关键词 → 中文+表过滤 → 英文 Id fallback）。拿到结果后就基于已有数据回答，**禁止**穷举所有可能的关键词变体（如 MonsterAuraDamage、MonsterAuraSpeed、MonsterAuraFire...逐个搜一遍）。如果 3 次搜索已返回足够数据，直接组织回答。
33. **search_game 结果使用（必须遵守）**：当 search_game 返回了匹配结果（显示"匹配: N 个"），你**必须**在回答中引用这些结果。结果列表中的每一条都是游戏数据库中真实存在的实体，**禁止**说"未找到相关数据"或"没有找到"。即使结果不完全匹配用户的问题，也要如实报告搜索到的内容并解释与用户问题的关系。例如：搜索"光环"返回了 16 个 Mods 实体，就应当列出这些词缀并说明它们属于怪物光环系统。
34. **trade_search 预算策略与装备档次**：
    - 用户说"X 以下最好的/最优/性价比最高"时，**不要只搜最低价**。应搜**预算上限附近**的多词缀好货，而不是列一堆 1 崇高的垃圾。核心逻辑：用户有预算，就要在预算内找到**词缀最好**的，不是**最便宜**的。
    - **关键词缀有档次之分**：很多词缀存在 +1/+2/+3/+4 等多个等级，高等级远比低等级强。例如召唤项链：+3/+4 所有召唤生物技能等级 >>> +2。搜索时**必须先搜高档次**（如 +3、+4），如果预算内买不到再降到 +2。其他常见高档次需求举例：技能等级 +3/+4、大生命/大抗性词缀、T1 词缀等。
    - **搜索策略**：先 trade_search 高档次（如"+3 召唤技能等级 项链"），看价格是否在预算内；如果太贵，再降一档搜 +2 并搭配更多辅助词缀。最终回答中应列出不同档次的选择供用户对比。
35. **装备搜索前主动追问（需求模糊时）**：当用户的装备/搜索需求**缺少关键信息**时，**不要直接开搜**，先用 1-2 句话引导用户补充条件，然后再搜索。
    - **什么时候追问**：用户只说了装备类型和预算，但**没说具体想要什么词缀/属性**。例如："找一条召唤项链 10D以下"——没说最看重什么（召唤技能等级？精魂？抗性？生命？施法速度？），此时应追问。
    - **什么时候不追问**：用户已经给出了具体词缀需求（如"+3 召唤技能等级 精魂 项链"），或者只是查价格/百科，直接搜。
    - **怎么追问**：简短自然，列出 2-3 个可能的方向供用户选择，**不要列一大堆问题**。例如：
      "召唤项链的核心词缀有好几个方向，你最看重哪个？
      ① 召唤技能等级（+3/+4 提升最大）
      ② 精魂（多开光环/捷）
      ③ 生存向（生命/抗性）
      也可以组合，比如'+3 等级 + 精魂'。告诉我侧重点，我好帮你精准搜。"
    - **追问后搜索**：根据用户回复构造精确的 trade_search query，不要再用模糊查询。
## 回答格式
- 使用清晰的中文 markdown（### 小标题、列表、**关键数值**）
- 资料不足就说明不足，标注 [推测] 仅限合理推断
- 交易搜索结果需在正文中解释最佳匹配含义；有 listing_price 时写「市集参考价：XXX」，并说明是近似匹配最低价
- **禁止使用 Wiki 链接语法**：不要出现 `[poe:名称]`、`[[poe:名称]]`、`[[名称|显示]]`、`|poe:` 等 PoE Wiki / MediaWiki 格式。直接用中文名称即可，必要时括号注明英文原名。**尤其在表格中**：表格单元格内只能用纯文本，绝对不要写 `[poe:...]`，否则管道符 `|` 会破坏表格结构。
  ✅ `| 法师之血 | 腰带 | 5 div |`
  ❌ `| [poe:法师之血] | 腰带 | 5 div |`
- **不要生成空白条目**：每个列表项、bullet point 后面必须有具体内容。如果某一条没有可写的内容，就不要列出来，不要留空白的 • 或 -。
"""


def _active_tools(ctx: ChatToolContext) -> list[dict[str, Any]]:
    """Return available tools for this turn, removing exhausted ones."""
    active = list(TOOL_DEFINITIONS)
    if ctx.trade_search_calls >= TRADE_SEARCH_MAX_PER_TURN:
        active = [t for t in active if t["function"]["name"] != "trade_search"]
    if ctx.rag_search_calls >= RAG_SOFT_LIMIT:
        active = [t for t in active if t["function"]["name"] != "rag_search"]
    return active


def _llm_client():
    return get_async_llm_client()


def _model() -> str:
    return LLM_MODEL


def _build_system_message(user_msg: str) -> str:
    signals = detect_input_signals(user_msg)
    extra = ""
    if signals:
        extra = "\n\n## 检测信号（供你决策，非强制路由）\n" + ", ".join(signals)
    return AGENT_SYSTEM + extra


def _parse_tool_args(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _first_choice(obj: Any) -> Any | None:
    choices = getattr(obj, "choices", None) or []
    return choices[0] if choices else None


async def _emit_streamed_answer(
    client: AsyncOpenAI,
    messages: list[dict[str, Any]],
    *,
    temperature: float = 0.3,
    max_tokens: int = 8192,
) -> AsyncIterator[tuple[str, str]]:
    """Yield (event_type, text) for answer/reasoning. Falls back to non-stream if needed."""
    stream_kwargs: dict[str, Any] = {
        "model": _model(),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    thinking = llm_thinking_extra_body()
    if thinking:
        stream_kwargs["extra_body"] = thinking
        stream_kwargs["reasoning_effort"] = "max"

    answer_parts: list[str] = []
    try:
        stream = await client.chat.completions.create(**stream_kwargs)
        async for chunk in stream:
            choice = _first_choice(chunk)
            if choice is None:
                continue
            delta = choice.delta
            reasoning = getattr(delta, "reasoning_content", None) or (
                delta.model_extra.get("reasoning_content")
                if hasattr(delta, "model_extra") and delta.model_extra
                else None
            )
            if reasoning:
                yield ("reasoning", reasoning)
            if delta.content:
                answer_parts.append(delta.content)
                yield ("answer", delta.content)
    except Exception as e:
        logger.warning("[CHAT] stream synthesis failed, fallback: %s", e)

    if answer_parts:
        return

    # MiMo sometimes returns empty stream chunks — non-stream fallback
    fb_kwargs = dict(stream_kwargs)
    fb_kwargs.pop("stream", None)
    fb_kwargs.pop("extra_body", None)
    fb_kwargs.pop("reasoning_effort", None)
    if thinking:
        fb_kwargs["extra_body"] = thinking
        fb_kwargs["reasoning_effort"] = "max"
    resp = await client.chat.completions.create(**fb_kwargs)
    choice = _first_choice(resp)
    if choice is None:
        raise RuntimeError("LLM returned no choices")
    msg = choice.message
    reasoning = getattr(msg, "reasoning_content", None) or ""
    if reasoning:
        yield ("reasoning", reasoning)
    text = msg.content or ""
    if text:
        yield ("answer", text)




async def _follow_up_event(user_msg: str, answer: str) -> dict[str, Any] | None:
    questions = await generate_follow_up_questions(user_msg, answer)
    if questions:
        return {"type": "follow_ups", "content": questions}
    return None


async def _stream_with_follow_ups(
    user_msg: str,
    source: AsyncIterator[dict[str, Any]],
) -> AsyncIterator[dict[str, Any]]:
    answer_acc = ""
    async for event in source:
        if event.get("type") == "answer":
            chunk = event.get("content") or ""
            if isinstance(chunk, str):
                answer_acc += chunk
        if event.get("type") == "done":
            fu = await _follow_up_event(user_msg, answer_acc)
            if fu:
                yield fu
        yield event
        if event.get("type") == "done":
            return


async def _yield_done_with_follow_ups(
    user_msg: str,
    answer: str,
) -> AsyncIterator[dict[str, Any]]:
    fu = await _follow_up_event(user_msg, answer)
    if fu:
        yield fu
    yield {"type": "done"}



async def stream_chat_agent(messages: list[dict]) -> AsyncIterator[dict[str, Any]]:
    """Run the agent loop and yield SSE event dicts."""

    user_msg = resolve_user_text(messages)
    last_msg = messages[-1] if messages else {}
    has_images = message_has_images(last_msg)

    if has_images:
        yield {"type": "thinking", "content": "已收到图片，正在视觉分析…"}

    session = build_session_context(messages)
    ctx = ChatToolContext(user_msg=session.effective_user_msg())
    client = _llm_client()

    agent_messages = build_agent_messages(messages, _build_system_message(user_msg))

    yield {"type": "thinking", "content": "AI 正在分析意图并规划工具..."}

    used_tools = False
    answer_acc = ""
    reasoning_acc = ""
    tool_round = 0
    while tool_round < MAX_TOOL_ROUNDS:
        tool_round += 1
        try:
            plan_kwargs: dict[str, Any] = {
                "model": _model(),
                "messages": agent_messages,
                "tools": _active_tools(ctx),
                "tool_choice": "auto",
                "temperature": 0.2,
                "max_tokens": 8192,
                "stream": True,
            }
            thinking = llm_thinking_extra_body()
            if thinking:
                plan_kwargs["extra_body"] = thinking
                plan_kwargs["reasoning_effort"] = "high"
            stream = await client.chat.completions.create(**plan_kwargs)

            # Accumulate streaming chunks
            content_parts: list[str] = []
            reasoning_parts: list[str] = []
            tool_calls_acc: dict[int, dict] = {}
            # State for filtering tool-call XML from reasoning stream
            _in_tool_xml = False
            _partial_tag = ""
            # Small buffer for content streaming: catches cross-delta wiki syntax
            # and tool-call XML leaks before they reach the user
            _content_buf = ""
            _STREAM_BUF_THRESHOLD = 80  # chars before flushing

            async for chunk in stream:
                delta = getattr(chunk.choices[0], "delta", None) if chunk.choices else None
                if delta is None:
                    continue

                # Accumulate reasoning (with tool-call XML filtering)
                reasoning_chunk = getattr(delta, "reasoning_content", None) or (
                    delta.model_extra.get("reasoning_content")
                    if hasattr(delta, "model_extra") and delta.model_extra
                    else None
                )
                if reasoning_chunk:
                    clean_text, _in_tool_xml, _partial_tag = _filter_reasoning_chunk(
                        reasoning_chunk, _in_tool_xml, _partial_tag
                    )
                    if clean_text:
                        reasoning_parts.append(clean_text)
                        yield {"type": "reasoning", "content": clean_text}

                # Accumulate content AND stream in real-time (with small buffer)
                if delta.content:
                    content_parts.append(delta.content)
                    _content_buf += delta.content
                    if len(_content_buf) >= _STREAM_BUF_THRESHOLD:
                        sanitized_chunk = _sanitize_answer(_content_buf)
                        if sanitized_chunk:
                            answer_acc += sanitized_chunk
                            yield {"type": "answer", "content": sanitized_chunk}
                        _content_buf = ""

                # Accumulate tool calls
                delta_tool_calls = getattr(delta, "tool_calls", None)
                if delta_tool_calls:
                    for tc_chunk in delta_tool_calls:
                        idx = tc_chunk.index
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                        if tc_chunk.id:
                            tool_calls_acc[idx]["id"] = tc_chunk.id
                        if tc_chunk.function:
                            if tc_chunk.function.name:
                                tool_calls_acc[idx]["function"]["name"] += tc_chunk.function.name
                            if tc_chunk.function.arguments:
                                tool_calls_acc[idx]["function"]["arguments"] += tc_chunk.function.arguments

            # Flush remaining content buffer
            if _content_buf:
                sanitized_tail = _sanitize_answer(_content_buf)
                if sanitized_tail:
                    answer_acc += sanitized_tail
                    yield {"type": "answer", "content": sanitized_tail}
                _content_buf = ""

        except Exception as e:
            logger.error("[CHAT] agent plan failed: %s", e)
            err = f"AI 规划失败: {e}"
            yield {"type": "answer", "content": err}
            async for ev in _yield_done_with_follow_ups(user_msg, err):
                yield ev
            flush()
            return

        full_content = "".join(content_parts)
        round_reasoning = "".join(reasoning_parts)
        # Build tool_calls list (sorted by index)
        tool_calls = []
        for idx in sorted(tool_calls_acc.keys()):
            tc_data = tool_calls_acc[idx]
            if tc_data["id"] and tc_data["function"]["name"]:
                # Create a simple namespace object to match non-streaming interface
                tool_calls.append(type("TC", (), {
                    "id": tc_data["id"],
                    "function": type("Fn", (), {
                        "name": tc_data["function"]["name"],
                        "arguments": tc_data["function"]["arguments"],
                    })(),
                })())

        if not tool_calls:
            # Content was already streamed in real-time during the LLM loop above.
            # No need to re-emit — just break out of the agent loop.
            break

        # Append assistant message with tool calls
        assistant_entry: dict[str, Any] = {"role": "assistant", "content": full_content or ""}
        assistant_entry["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in tool_calls
        ]
        agent_messages.append(assistant_entry)
        used_tools = True

        # Track rag calls within this batch to dedup/skip
        rag_this_batch = 0
        for tc in tool_calls:
            fn = tc.function.name

            # Skip rag_search if budget was consumed earlier in this same batch
            if fn == "rag_search":
                if rag_this_batch >= 1 and ctx.rag_search_calls >= RAG_SOFT_LIMIT:
                    continue  # LLM spammed multiple rag_search in one turn — skip extras
                rag_this_batch += 1

            args = _parse_tool_args(tc.function.arguments)
            label = TOOL_LABELS.get(fn, fn)
            yield {"type": "thinking", "content": f"调用工具: {label}..."}
            yield {
                "type": "tool_use",
                "content": {"name": fn, "arguments": args},
            }

            try:
                result = await execute_tool(fn, args, ctx)
            except Exception as e:
                logger.error("[CHAT] tool %s failed: %s", fn, e)
                result_content = json.dumps({"error": str(e)}, ensure_ascii=False)
                yield {
                    "type": "tool_result",
                    "content": {"name": fn, "ok": False, "preview": str(e)[:200]},
                }
                agent_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_content,
                    },
                )
                continue

            preview = result.content[:240] + ("..." if len(result.content) > 240 else "")
            yield {
                "type": "tool_result",
                "content": {"name": fn, "ok": True, "preview": preview},
            }

            if result.trade_result:
                yield {"type": "trade_result", "content": result.trade_result}
            if result.recommend_result:
                yield {"type": "recommend_result", "content": result.recommend_result}

            agent_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result.content,
                },
            )


    if not used_tools:
        if ctx.last_sources:
            yield {"type": "sources", "content": ctx.last_sources}
        _save_chat_history(messages, user_msg, answer_acc, ctx, reasoning_acc)
        async for ev in _yield_done_with_follow_ups(user_msg, answer_acc):
            yield ev
        flush()
        return

    # If the tool loop already produced an answer (LLM answered without tool calls
    # after previous tool rounds), skip synthesis to avoid duplicate output.
    if answer_acc.strip():
        # Final sanitization pass (catches wiki patterns spanning delta chunks)
        answer_acc = _sanitize_answer(answer_acc)
        if ctx.last_sources:
            yield {"type": "sources", "content": ctx.last_sources}
        _save_chat_history(messages, user_msg, answer_acc, ctx, reasoning_acc)
        async for ev in _yield_done_with_follow_ups(user_msg, answer_acc):
            yield ev
        flush()
        return

    # Stream final synthesis after tool rounds
    yield {"type": "thinking", "content": "正在综合工具结果生成回答..."}

    try:
        async for kind, text in _emit_streamed_answer(client, agent_messages):
            if kind == "reasoning":
                clean = _sanitize_reasoning(text)
                if clean:
                    reasoning_acc += clean
                    yield {"type": "reasoning", "content": clean}
            else:
                sanitized = _sanitize_answer(text)
                if sanitized:
                    answer_acc += sanitized
                    yield {"type": "answer", "content": sanitized}
    except Exception as e:
        logger.error("[CHAT] agent stream failed: %s", e)
        err = f"生成失败: {e}"
        answer_acc += err
        yield {"type": "answer", "content": err}

    if ctx.last_sources:
        yield {"type": "sources", "content": ctx.last_sources}

    # Final sanitization pass on accumulated answer (catches wiki patterns spanning chunks)
    if answer_acc:
        answer_acc = _sanitize_answer(answer_acc)

    # Post-hoc entity validation
    if answer_acc:
        suspicious = _validate_answer_entities(answer_acc, ctx)
        if suspicious:
            yield {"type": "entity_warnings", "content": suspicious}
            logger.info("[CHAT] entity validation: %d suspicious entities found", len(suspicious))
        _save_chat_history(messages, user_msg, answer_acc, ctx, reasoning_acc)

    async for ev in _yield_done_with_follow_ups(user_msg, answer_acc):
        yield ev

    flush()
