"""Sequential multi-item trade price quoting for chat."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from collections.abc import AsyncIterator
from typing import Any

logger = logging.getLogger(__name__)

_PRICE_KEYWORDS = re.compile(
    r"(?:多少钱|多少[edED]|价格|市价|报价|最便宜|分别多少|行情|混池|神圣|崇高)"
)
_ITEM_SPLIT = re.compile(r"[、，,;/\n和及与]+")
_STRIP_NOISE = re.compile(
    r"(?:分别|各自|都|一下|查询|查一下|帮我|请问|多少|价格|市价|报价|最便宜|多少币|行情|钱)"
)

EXTRACT_SYSTEM = """从用户消息中提取要查市价的 PoE2 物品/装备名称（暗金、基底等）。
只输出 JSON：{"items": ["名称1", "名称2", ...]}
规则：
- 仅列出用户明确要查价格的物品，不要臆造
- 去掉价格、礼貌用语等无关词
- 国服常用中文名保留；英文暗金名可保留英文
- 若只有一个物品，items 仍返回单元素数组
"""


def is_multi_item_price_query(text: str) -> bool:
    """True when the message asks for prices on 2+ distinct items."""
    if not text or not _PRICE_KEYWORDS.search(text):
        return False
    items = _fallback_split_items(text)
    if len(items) >= 2:
        return True
    parts = [p.strip() for p in re.split(r"[、，,/]", text) if p.strip()]
    named = [p for p in parts if len(p) >= 2]
    return len(named) >= 2


def _fallback_split_items(text: str) -> list[str]:
    chunks = [c.strip() for c in _ITEM_SPLIT.split(text.strip()) if c.strip()]
    items: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        cleaned = _STRIP_NOISE.sub("", chunk).strip()
        if not cleaned or len(cleaned) < 2:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append(cleaned)
    return items


def _extract_items_sync(text: str) -> list[str]:
    from openai import OpenAI

    client = OpenAI(
        base_url=os.getenv("LLM_BASE_URL", "https://api.siliconflow.cn/v1"),
        api_key=os.getenv("LLM_API_KEY", ""),
    )
    model = os.getenv("LLM_MODEL", "deepseek-ai/DeepSeek-V4-Flash")
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": EXTRACT_SYSTEM},
                {"role": "user", "content": text},
            ],
            temperature=0.1,
            max_tokens=256,
            response_format={"type": "json_object"},
        )
        data = json.loads((resp.choices[0].message.content or "{}").strip())
        items = data.get("items") or []
        if isinstance(items, list):
            out = [str(x).strip() for x in items if str(x).strip()]
            if out:
                return out
    except Exception as e:
        logger.warning("multi_item LLM extract failed: %s", e)
    return _fallback_split_items(text)


def _currency_label(currency: str) -> str:
    return {
        "chaos": "混沖石",
        "divine": "神圣石",
        "exalted": "崇高石",
        "mirror": "镜子",
    }.get((currency or "").lower(), currency or "?")


def _format_item_answer(item: str, quote: dict[str, Any]) -> str:
    if quote.get("error"):
        return f"### {item}\n\n查询失败：{quote.get('error')}"
    amount = quote.get("amount")
    currency = _currency_label(str(quote.get("currency", "")))
    name = quote.get("item_name") or item
    line = f"**{amount}** {currency}"
    if name and name != item:
        line += f"（市集条目：{name}）"
    return f"### {item}\n\n当前最低标价：{line}"


def _format_summary(quotes: list[dict[str, Any]]) -> str:
    lines = ["## 市价汇总", ""]
    totals: dict[str, float] = {}
    ok = fail = 0
    for q in quotes:
        item = q.get("item") or "?"
        if q.get("error"):
            fail += 1
            lines.append(f"- **{item}**：查询失败（{q.get('error')}）")
            continue
        ok += 1
        cur = str(q.get("currency", "")).lower()
        amt = q.get("amount")
        if cur and amt is not None:
            try:
                totals[cur] = totals.get(cur, 0.0) + float(amt)
            except (TypeError, ValueError):
                pass
        lines.append(
            f"- **{item}**：{q.get('amount')} {_currency_label(str(q.get('currency', '')))}"
        )
    lines.extend(["", "### 统计", f"- 成功 **{ok}** / 失败 **{fail}** / 共 **{len(quotes)}** 项"])
    if totals:
        lines.append("")
        lines.append("### 同币种合计（未做汇率换算）")
        for cur, total in sorted(totals.items()):
            if total == int(total):
                total_s = str(int(total))
            else:
                total_s = f"{total:g}"
            lines.append(f"- {_currency_label(cur)}：**{total_s}**")
    lines.extend(
        [
            "",
            "*价格为市集当前最低价，实际成交可能浮动；点击上方交易链接可查看详情。*",
        ]
    )
    return "\n".join(lines)


def _quote_one_sync(
    item: str,
    market: str = "cn",
    league: str | None = None,
) -> dict[str, Any]:
    from app.services.trade_service import fetch_cheapest_listing, search_unique_by_name

    search = search_unique_by_name(item, market=market, league=league)
    resolved = search.get("resolved") or {}
    unique_en = resolved.get("unique_name") or item
    label = f"{unique_en} ({search.get('total_results', 0)} 条)" if search.get("trade_url") else unique_en
    trade_data = {
        "best_match": (
            {
                "label": label,
                "url": search.get("trade_url"),
                "count": search.get("total_results", 0),
            }
            if search.get("trade_url")
            else None
        ),
        "alternatives": [],
        "explanation": search.get("intent_summary") or resolved.get("source") or "",
    }
    base: dict[str, Any] = {"item": item, "trade_result": trade_data}
    if search.get("error"):
        base["error"] = search["error"]
        return base
    if not search.get("trade_url"):
        base["error"] = "未找到交易结果"
        return base
    listing = fetch_cheapest_listing(
        search["trade_url"],
        market=market,
        league=league,
        skip_rate_limit=True,
        item_ids=search.get("item_ids"),
    )
    if listing.get("error"):
        base["error"] = listing["error"]
        return base
    base.update(
        {
            "amount": listing.get("amount"),
            "currency": listing.get("currency"),
            "item_name": listing.get("item_name"),
        }
    )
    return base


async def stream_multi_item_prices(
    user_msg: str,
    market: str = "cn",
    league: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    yield {"type": "thinking", "content": "正在识别要查价的物品…"}
    fallback = _fallback_split_items(user_msg)
    if len(fallback) >= 2:
        items = fallback
    else:
        items = await asyncio.to_thread(_extract_items_sync, user_msg)
    if len(items) <= 1:
        yield {"type": "route", "content": "default_agent"}
        return

    yield {
        "type": "answer",
        "content": f"共 **{len(items)}** 件装备，逐个查询国服市集（约 {len(items) * 8} 秒）…\n\n",
    }
    yield {
        "type": "thinking",
        "content": f"识别到 {len(items)} 个物品，将逐个查询国服市集最低价。",
    }
    quotes: list[dict[str, Any]] = []
    for idx, item in enumerate(items, start=1):
        yield {
            "type": "thinking",
            "content": f"({idx}/{len(items)}) 正在搜索：{item}",
        }
        quote = await asyncio.to_thread(_quote_one_sync, item, market, league)
        quotes.append(quote)
        if quote.get("trade_result"):
            yield {"type": "trade_result", "content": quote["trade_result"]}
        yield {"type": "answer", "content": _format_item_answer(item, quote)}

    yield {"type": "answer", "content": _format_summary(quotes)}
    yield {"type": "done"}
