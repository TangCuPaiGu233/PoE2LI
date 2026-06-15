"""Post-sampling guards for chat assistant text."""

from __future__ import annotations

import re

# Specific price assertions (not bare currency words in user quotes)
_PRICE_ASSERTION = re.compile(
    r"(?:约|大概|估计|建议|参考)?\s*\d+(?:\.\d+)?\s*(?:[-~～至到]\s*\d+(?:\.\d+)?\s*)?"
    r"(?:神圣|崇高|混沌|d|D|e|E|ex|div|c)\b"
    r"|(?:售价|报价|市价|值)\s*(?:为|约|是)?\s*\d+"
)


def has_listing_price_in_turn(trade_event_count: int) -> bool:
    return trade_event_count > 0


def strip_ungrounded_price_claims(text: str, *, had_listing: bool) -> str:
    """If no trade listing was produced, replace specific price assertions."""
    if had_listing or not text:
        return text
    if not _PRICE_ASSERTION.search(text):
        return text
    return (
        text
        + "\n\n*说明：本轮未能从市集读取在售标价，以上若含具体金额请忽略；"
        "需要准确价格请使用下方市集链接或重新发起 trade 搜索。*"
    )
