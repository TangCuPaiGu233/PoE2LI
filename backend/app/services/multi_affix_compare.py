"""Sequential per-affix trade price comparison for chat."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from collections.abc import AsyncIterator
from typing import Any

logger = logging.getLogger(__name__)

AFFIX_QUOTE_GAP_SEC = float(os.getenv("TRADE_AFFIX_GAP_SEC", "3"))
MAX_AFFIX_SEARCHES = int(os.getenv("TRADE_AFFIX_MAX", "8"))

_PRICE_KEYWORDS = re.compile(
    r"(?:多少钱|多少[edED]|价格|市价|报价|最便宜|分别多少|行情|值多少|多少币)"
)
_AFFIX_COMPARE = re.compile(
    r"(?:不同|各个|各|每种|多种|分别).{0,16}(?:词条|词缀|后缀|前缀|变体|roll|Roll|组合)"
    r"|(?:词条|词缀).{0,12}(?:对比|比较|分别).{0,12}(?:价格|多少钱|市价|多少)"
    r"|对比.{0,16}(?:词条|词缀|变体)"
    r"|其他.{0,12}(?:职业|升华|起点).{0,12}(?:词缀|词条).{0,12}(?:价格|多少钱|市价|多少)"
)

EXTRACT_SYSTEM = """从对话中提取「多条独立 trade 搜索」，用于逐项对比不同词缀/变体的市价。

只输出 JSON：
{
  "searches": [
    {"label": "展示用短标签（如：佣兵起点）", "query": "传给 trade_search 的中文 query"}
  ]
}

规则：
- 用户要对比多个词条/变体/roll 的价格时，每条 search 只包含**一个**词条组合，禁止把多个词缀塞进同一条 query
- 从最近对话中识别装备名（暗金名、基底如蓝玉/红玉）和所有需要比价的变体
- 暗金变体示例：{"label": "佣兵起点", "query": "人格分裂 佣兵"}
- 稀有珠宝示例：{"label": "召唤暴击", "query": "蓝玉 召唤生物暴击伤害加成"}
- label 简短中文；query 可直接用于国服市集搜索
- 若无法拆出至少 2 条独立 query，返回 {"searches": []}
- 不要臆造对话里没出现过的词缀；若用户只说「不同词条价格」但未列出具体词条，从 assistant 上一轮列出的词缀/变体中推断
"""


def is_multi_affix_compare_query(text: str, messages: list[dict] | None = None) -> bool:
    """True when user wants per-affix/per-variant price comparison."""
    if not text or not _PRICE_KEYWORDS.search(text):
        return False
    if not _AFFIX_COMPARE.search(text):
        return False
    from app.services.chat_tools import find_build_input

    if find_build_input(text) and re.search(r"(?:造价|成本|花费)", text):
        return False
    return True


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


def _extract_searches_sync(user_msg: str, messages: list[dict] | None) -> list[dict[str, str]]:
    from openai import OpenAI

    from app.core.llm_config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, llm_message_text

    ctx = _conversation_context(messages)
    user_block = user_msg.strip()
    if ctx:
        user_block = f"## 最近对话\n{ctx}\n\n## 当前问题\n{user_msg.strip()}"

    client = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)
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
        return out[:MAX_AFFIX_SEARCHES]
    except Exception as e:
        logger.warning("multi_affix LLM extract failed: %s", e)
        return []


def _currency_label(currency: str) -> str:
    return {
        "chaos": "混沌石",
        "divine": "神圣石",
        "exalted": "崇高石",
        "mirror": "镜子",
    }.get((currency or "").lower(), currency or "?")


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
        return f"### {label}\n\n搜索：`{query}`\n\n查询失败：{quote['error']}{_trade_link_line(quote.get('trade_result'))}"
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


def _quote_affix_sync(query: str, market: str = "cn", league: str | None = None) -> dict[str, Any]:
    from app.services.trade_agent import run_agent

    result = run_agent(query, market=market, league=league, user_msg=query)
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
            {
                "label": a.get("label"),
                "url": a.get("url"),
                "count": a.get("count", 0),
            }
            for a in (result.get("alternatives") or [])[:3]
        ],
        "explanation": result.get("explanation", ""),
        "listing_price": result.get("listing_price"),
        "price_note": result.get("price_note"),
    }
    base: dict[str, Any] = {
        "query": query,
        "trade_result": trade_data,
        "listing_price": result.get("listing_price"),
        "price_note": result.get("price_note"),
    }
    if not best.get("url"):
        base["error"] = result.get("price_note") or "未生成有效市集链接"
    return base


async def stream_multi_affix_compare(
    user_msg: str,
    *,
    messages: list[dict] | None = None,
    market: str = "cn",
    league: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    yield {"type": "thinking", "content": "正在识别要逐项比价的词条…"}
    searches = await asyncio.to_thread(_extract_searches_sync, user_msg, messages)
    if len(searches) < 2:
        yield {"type": "route", "content": "default_agent"}
        return

    n = len(searches)
    gap = int(AFFIX_QUOTE_GAP_SEC)
    yield {
        "type": "answer",
        "content": f"共 **{n}** 个词条/变体，将逐个搜索市集（每次只搜一个词条，项间等待 {gap} 秒）…\n\n",
    }
    yield {
        "type": "thinking",
        "content": f"识别到 {n} 条独立搜索，开始逐项查价。",
    }

    quotes: list[dict[str, Any]] = []
    for idx, spec in enumerate(searches, start=1):
        label = spec["label"]
        query = spec["query"]
        yield {"type": "thinking", "content": f"({idx}/{n}) 正在搜索：{label} → `{query}`"}
        quote = await asyncio.to_thread(_quote_affix_sync, query, market, league)
        quote["label"] = label
        quotes.append(quote)
        if quote.get("trade_result"):
            yield {"type": "trade_result", "content": quote["trade_result"]}
        yield {"type": "answer", "content": _format_affix_answer(label, query, quote) + "\n"}
        if idx < n and AFFIX_QUOTE_GAP_SEC > 0:
            yield {"type": "thinking", "content": f"已完成 {label}，{gap} 秒后继续下一词条…"}
            await asyncio.sleep(AFFIX_QUOTE_GAP_SEC)

    yield {"type": "answer", "content": _format_summary(quotes)}
    yield {"type": "done"}
