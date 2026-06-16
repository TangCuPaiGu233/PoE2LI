"""Sequential per-affix trade price comparison for chat."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections.abc import AsyncIterator
from typing import Any

from app.services.chat_async_util import LLM_EXTRACT_TIMEOUT_SEC, TRADE_QUOTE_TIMEOUT_SEC, run_sync_with_timeout
from app.services.chat_item_profile import (
    build_item_profile,
    build_searches_from_labels,
    build_searches_from_variants,
    parse_variants_from_assistant,
)

logger = logging.getLogger(__name__)

MAX_AFFIX_SEARCHES = int(os.getenv("TRADE_AFFIX_MAX", "8"))
CHAT_WALL_CLOCK_SEC = float(os.getenv("CHAT_WALL_CLOCK_SEC", "90"))

_PRICE_KEYWORDS = re.compile(
    r"(?:多少钱|多少[edED]|价格|市价|报价|最便宜|分别多少|行情|值多少|多少币)"
)
_AFFIX_COMPARE = re.compile(
    r"(?:不同|各个|各|每种|多种|分别).{0,16}(?:词条|词缀|后缀|前缀|变体|roll|Roll|组合)"
    r"|(?:词条|词缀).{0,12}(?:对比|比较|分别).{0,12}(?:价格|多少钱|市价|多少)"
    r"|对比.{0,16}(?:词条|词缀|变体)"
    r"|其他.{0,12}(?:职业|升华|起点).{0,12}(?:词缀|词条).{0,12}(?:价格|多少钱|市价|多少)"
)

SELECT_SYSTEM = """你是 PoE2 市集搜索助手。用户要从**候选变体/词条列表**中选出需要逐项比价的项。

只输出 JSON：
{"selected": ["候选标签1", "候选标签2"]}

规则：
- 只能从下方「候选列表」中选，禁止添加列表外的名称
- 用户问「不同词条分别什么价」且未指定子集 → 返回候选列表中的全部（最多 8 个）
- 用户明确提到部分变体 → 只返回那些
- 若无法匹配任何候选 → {"selected": []}
"""

EXTRACT_SYSTEM = """从对话中提取「多条独立 trade 搜索」，用于逐项对比不同词缀/变体的市价。

只输出 JSON：
{
  "searches": [
    {"label": "展示用短标签", "query": "传给 trade_search 的中文 query"}
  ]
}

规则：
- 每条 search 只包含**一个**词条或变体
- 若无法拆出至少 2 条，返回 {"searches": []}
- 不要臆造对话里没出现过的词缀
"""


def is_multi_affix_compare_query(text: str, messages: list[dict] | None = None) -> bool:
    """True when user wants per-affix/per-variant price comparison."""
    if not text or not _PRICE_KEYWORDS.search(text):
        return False
    from app.services.chat_tools import find_build_input

    if find_build_input(text) and re.search(r"(?:造价|成本|花费)", text):
        return False
    if _AFFIX_COMPARE.search(text):
        return True
    if text.count("起点") >= 2 and _PRICE_KEYWORDS.search(text):
        profile = build_item_profile(messages)
        if profile.variants and profile.item_name:
            return True
        if re.search(r"起点.{0,8}(?:和|、|与|跟).{0,8}起点", text):
            return True
    return False


def _conversation_context(messages: list[dict] | None, max_turns: int = 8) -> str:
    from app.services.chat_multimodal import extract_text

    if not messages:
        return ""
    lines: list[str] = []
    for msg in messages[-max_turns:]:
        role = msg.get("role") or "?"
        text = extract_text(msg)
        if text:
            lines.append(f"{role}: {text[:800]}")
    return "\n".join(lines)


def _dedupe_searches(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for row in rows:
        q = (row.get("query") or "").strip()
        if not q:
            continue
        key = q.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"label": row.get("label") or q[:24], "query": q})
    return out[:MAX_AFFIX_SEARCHES]


def _select_from_candidates_sync(
    user_msg: str,
    messages: list[dict] | None,
    candidates: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Constrained LLM selection from known variant list."""
    if len(candidates) < 2:
        return []

    from app.core.llm_config import LLM_MODEL, llm_message_text

    if not LLM_API_KEY:
        return []

    labels = [c["label"] for c in candidates]
    ctx = _conversation_context(messages)
    user_block = "## 候选列表\n" + "\n".join(f"- {lbl}" for lbl in labels)
    if ctx:
        user_block = f"## 最近对话\n{ctx}\n\n{user_block}\n\n## 当前问题\n{user_msg.strip()}"
    else:
        user_block += f"\n\n## 当前问题\n{user_msg.strip()}"

    from app.core.llm_client import get_llm_client
    client = get_llm_client()
    try:
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": SELECT_SYSTEM},
                {"role": "user", "content": user_block},
            ],
            temperature=0.0,
            max_tokens=512,
            response_format={"type": "json_object"},
        )
        raw = llm_message_text(resp.choices[0].message) if resp.choices else ""
        data = json.loads(raw or "{}")
        selected = data.get("selected") or []
        if not isinstance(selected, list):
            return []
        label_to_row = {c["label"]: c for c in candidates}
        out: list[dict[str, str]] = []
        for name in selected:
            name = str(name).strip()
            if name in label_to_row:
                out.append(label_to_row[name])
        return _dedupe_searches(out)
    except Exception as e:
        logger.warning("multi_affix constrained select failed: %s", e)
        return []


def _extract_searches_llm_sync(user_msg: str, messages: list[dict] | None) -> list[dict[str, str]]:
    from app.core.llm_config import LLM_MODEL, llm_message_text

    ctx = _conversation_context(messages)
    user_block = user_msg.strip()
    if ctx:
        user_block = f"## 最近对话\n{ctx}\n\n## 当前问题\n{user_msg.strip()}"

    from app.core.llm_client import get_llm_client
    client = get_llm_client()
    try:
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": EXTRACT_SYSTEM},
                {"role": "user", "content": user_block},
            ],
            temperature=0.1,
            max_tokens=1024,
            response_format={"type": "json_object"},
        )
        raw = llm_message_text(resp.choices[0].message) if resp.choices else ""
        data = json.loads(raw or "{}")
        searches = data.get("searches") or []
        out: list[dict[str, str]] = []
        if not isinstance(searches, list):
            return []
        for row in searches:
            if not isinstance(row, dict):
                continue
            label = str(row.get("label") or "").strip()
            query = str(row.get("query") or "").strip()
            if not query:
                continue
            if not label:
                label = query[:24]
            out.append({"label": label, "query": query})
        return _dedupe_searches(out)
    except Exception as e:
        logger.warning("multi_affix LLM extract failed: %s", e)
        return []


def _user_wants_all_catalog_variants(user_msg: str) -> bool:
    """Generic 'compare all variants' — use full KB list without LLM selection."""
    return bool(re.search(r"(?:不同|各个|各|每种|多种|分别)", user_msg or ""))


def _user_named_specific_variants(
    user_msg: str, catalog_rows: list[dict[str, str]],
) -> list[dict[str, str]] | None:
    """User explicitly named >=2 variants from catalog."""
    hits: list[dict[str, str]] = []
    for row in catalog_rows:
        lbl = str(row.get("label") or "")
        suf = str(row.get("query_suffix") or "")
        if (lbl and lbl in user_msg) or (suf and suf in user_msg):
            hits.append(row)
    if len(hits) >= 2:
        return _dedupe_searches(hits)
    return None


def resolve_searches_sync(user_msg: str, messages: list[dict] | None) -> list[dict[str, str]]:
    """Layered: assistant parse → KB catalog → constrained select → LLM fallback."""
    profile = build_item_profile(messages)
    item_name = profile.display_name

    assistant_labels = parse_variants_from_assistant(messages)
    if assistant_labels and item_name:
        rows = _dedupe_searches(build_searches_from_labels(item_name, assistant_labels))
        if len(rows) >= 2:
            return rows

    if profile.variants and item_name:
        catalog_rows = _dedupe_searches(build_searches_from_variants(item_name, profile.variants))
        if len(catalog_rows) >= 2:
            named = _user_named_specific_variants(user_msg, catalog_rows)
            if named:
                return named
            if _user_wants_all_catalog_variants(user_msg):
                return catalog_rows
            from app.core.llm_config import LLM_API_KEY

            if LLM_API_KEY:
                selected = _select_from_candidates_sync(user_msg, messages, catalog_rows)
                if len(selected) >= 2:
                    return selected
            return catalog_rows

    llm_rows = _extract_searches_llm_sync(user_msg, messages)
    if len(llm_rows) >= 2:
        return llm_rows

    if item_name and assistant_labels:
        return _dedupe_searches(build_searches_from_labels(item_name, assistant_labels))
    return []


def _trade_link_line(trade_result: dict[str, Any] | None) -> str:
    if not trade_result:
        return ""
    bm = trade_result.get("best_match") or {}
    url = (bm.get("url") or "").strip()
    if not url:
        return ""
    count = bm.get("count")
    return f"\n\n[打开市集搜索（{count if count is not None else '?'} 条）]({url})"


def _format_affix_answer(label: str, query: str, quote: dict[str, Any]) -> str:
    if quote.get("error"):
        return (
            f"### {label}\n\n搜索：`{query}`\n\n查询失败：{quote['error']}"
            f"{_trade_link_line(quote.get('trade_result'))}"
        )
    lp = quote.get("listing_price")
    tr = quote.get("trade_result") or {}
    if lp and lp.get("display"):
        return (
            f"### {label}\n\n"
            f"搜索：`{query}`\n\n"
            f"市集参考价（在售最低）：**{lp['display']}**"
            f"{_trade_link_line(tr)}"
        )
    note = quote.get("price_note") or tr.get("explanation") or "暂无完全匹配在售，无法给出真实标价"
    count = (tr.get("best_match") or {}).get("count", 0)
    return (
        f"### {label}\n\n"
        f"搜索：`{query}`\n\n"
        f"{note}（当前搜索约 **{count}** 条在售）"
        f"{_trade_link_line(tr)}"
    )


def _format_summary(quotes: list[dict[str, Any]]) -> str:
    lines = ["## 词条比价汇总", ""]
    ok = fail = no_price = 0
    for q in quotes:
        label = q.get("label") or q.get("query") or "?"
        if q.get("error"):
            fail += 1
            lines.append(f"- **{label}**：查询失败（{q.get('error')}）")
            continue
        lp = q.get("listing_price")
        if lp and lp.get("display"):
            ok += 1
            lines.append(f"- **{label}**：{lp['display']}")
        else:
            no_price += 1
            note = q.get("price_note") or "无在售或无法读取标价"
            lines.append(f"- **{label}**：{note}")
    lines.extend(
        [
            "",
            "### 统计",
            f"- 有参考价 **{ok}** / 无标价 **{no_price}** / 失败 **{fail}** / 共 **{len(quotes)}** 项",
            "",
            "*每项价格为独立搜索条件下的市集最低价；不同词条搜索条件不同，不宜直接相加。*",
        ]
    )
    return "\n".join(lines)


def _quote_affix_sync(
    query: str,
    market: str = "cn",
    league: str | None = None,
    detail_count: int = 2,
) -> dict[str, Any]:
    from app.services.trade_agent import run_agent

    result = run_agent(
        query, market=market, league=league, user_msg=query, detail_count=detail_count,
    )
    best = result.get("best_match") or {}
    trade_data = {
        "best_match": (
            {
                "label": best.get("label"),
                "url": best.get("url"),
                "count": best.get("count", 0),
                "degraded": best.get("degraded", False),
                "empty": best.get("count", 0) == 0,
                "broad": best.get("broad", False),
            }
            if best.get("url")
            else None
        ),
        "alternatives": [
            {"label": a.get("label"), "url": a.get("url"), "count": a.get("count", 0)}
            for a in (result.get("alternatives") or [])[:3]
        ],
        "explanation": result.get("explanation", ""),
        "listing_price": result.get("listing_price"),
        "listings": result.get("listings") or [],
        "listings_fetched": result.get("listings_fetched", 0),
        "price_note": result.get("price_note"),
    }
    base: dict[str, Any] = {
        "query": query,
        "trade_result": trade_data,
        "listing_price": result.get("listing_price"),
        "listings": result.get("listings") or [],
        "price_note": result.get("price_note"),
    }
    if not best.get("url"):
        base["error"] = result.get("price_note") or "未生成有效市集链接"
    return base


def _base_item_query(profile) -> str:
    name = profile.display_name
    if profile.rarity == "unique" and name:
        return name
    if name and profile.base:
        return f"{profile.base} {name}".strip()
    return name or profile.base or "珠宝"


async def _stream_need_user_input(
    user_msg: str,
    messages: list[dict] | None,
    *,
    market: str,
    league: str | None,
    extract_count: int,
) -> AsyncIterator[dict[str, Any]]:
    """Deterministic fallback — never route to ReAct agent."""
    profile = build_item_profile(messages)
    base_query = _base_item_query(profile)
    item_label = profile.display_name or "该物品"

    yield {
        "type": "handler_meta",
        "content": {"extract_count": extract_count, "fallback": False, "status": "need_user_input"},
    }
    yield {
        "type": "answer",
        "content": (
            f"未能自动识别出 **2 个及以上** 可独立搜索的词条/变体（当前识别 **{extract_count}** 个）。\n\n"
            f"先为你搜索基础物品 **{item_label}** 的市集链接；"
            f"若要逐项比价，请直接说明要比哪些变体，例如：「佣兵起点、战士起点分别多少钱」。\n\n"
        ),
    }

    if base_query:
        yield {"type": "thinking", "content": f"基础搜索：{base_query}"}
        try:
            quote = await run_sync_with_timeout(
                _quote_affix_sync,
                base_query,
                market,
                league,
                timeout=TRADE_QUOTE_TIMEOUT_SEC,
            )
            if quote.get("trade_result"):
                yield {"type": "trade_result", "content": quote["trade_result"]}
            yield {
                "type": "answer",
                "content": _format_affix_answer("基础物品", base_query, quote) + "\n",
            }
        except TimeoutError:
            yield {
                "type": "answer",
                "content": f"### 基础物品\n\n搜索 `{base_query}` 超时，请稍后重试或在 /trade 页手动搜索。\n",
            }
        except Exception as e:
            logger.warning("multi_affix base search failed: %s", e)
            yield {"type": "answer", "content": f"### 基础物品\n\n搜索失败：{e}\n"}

    if profile.rarity == "unique" and profile.variants:
        hints = "、".join(v.get("label", "") for v in profile.variants[:8])
        yield {"type": "answer", "content": f"\n**已知变体参考**（国服）：{hints}\n"}


async def stream_multi_affix_compare(
    user_msg: str,
    *,
    messages: list[dict] | None = None,
    market: str = "cn",
    league: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    started = time.monotonic()
    try:
        yield {"type": "thinking", "content": "正在识别要逐项比价的词条…"}
        try:
            searches = await run_sync_with_timeout(
                resolve_searches_sync,
                user_msg,
                messages,
                timeout=LLM_EXTRACT_TIMEOUT_SEC,
            )
        except TimeoutError:
            logger.warning("multi_affix resolve_searches timed out")
            searches = []

        extract_count = len(searches)
        yield {"type": "handler_meta", "content": {"extract_count": extract_count}}

        if len(searches) < 2:
            async for event in _stream_need_user_input(
                user_msg,
                messages,
                market=market,
                league=league,
                extract_count=extract_count,
            ):
                yield event
            return

        n = len(searches)
        yield {
            "type": "answer",
            "content": f"共 **{n}** 个词条/变体，将逐个搜索市集（每次只搜一个词条）…\n\n",
        }
        yield {"type": "thinking", "content": f"识别到 {n} 条独立搜索，开始逐项查价。"}

        quotes: list[dict[str, Any]] = []
        for idx, spec in enumerate(searches, start=1):
            if time.monotonic() - started > CHAT_WALL_CLOCK_SEC - 5:
                yield {
                    "type": "answer",
                    "content": f"\n*(时间预算不足，已完成 {idx - 1}/{n} 项)*\n",
                }
                break

            label = spec["label"]
            query = spec["query"]
            yield {"type": "thinking", "content": f"({idx}/{n}) 正在搜索：{label} → `{query}`"}
            try:
                quote = await run_sync_with_timeout(
                    _quote_affix_sync,
                    query,
                    market,
                    league,
                    timeout=TRADE_QUOTE_TIMEOUT_SEC,
                )
            except TimeoutError:
                quote = {"label": label, "query": query, "error": "市集查询超时"}
            quote["label"] = label
            quotes.append(quote)
            if quote.get("trade_result"):
                yield {"type": "trade_result", "content": quote["trade_result"]}
            yield {"type": "answer", "content": _format_affix_answer(label, query, quote) + "\n"}

        if quotes:
            yield {"type": "answer", "content": _format_summary(quotes)}
    finally:
        yield {"type": "done"}
