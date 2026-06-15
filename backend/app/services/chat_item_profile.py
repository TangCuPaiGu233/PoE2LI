"""Session item profile — entity + variant catalog for compare handlers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.services.chat_multimodal import extract_text
from app.services.entity_dict import CLASS_CN_TO_EN
from app.services.trade_stats_index import normalize_variant_label

# PoE2 人格分裂：按职业起点分的变体（字典优先，Gotcha 9 取不到则 NeedUserInput）
_SPLIT_PERSONALITY_VARIANTS: list[tuple[str, str]] = [
    ("佣兵起点", "佣兵"),
    ("魔巫起点", "魔巫"),
    ("战士起点", "战士"),
    ("游侠起点", "游侠"),
    ("暗影起点", "暗影"),
    ("圣堂武僧起点", "圣堂武僧"),
]

UNIQUE_VARIANT_CATALOG: dict[str, dict[str, Any]] = {
    "人格分裂": {
        "en": "Split Personality",
        "rarity": "unique",
        "base": "红玉",
        "variants": [{"label": lbl, "query_suffix": suf} for lbl, suf in _SPLIT_PERSONALITY_VARIANTS],
    },
    "Split Personality": {
        "cn": "人格分裂",
        "en": "Split Personality",
        "rarity": "unique",
        "base": "红玉",
        "variants": [{"label": lbl, "query_suffix": suf} for lbl, suf in _SPLIT_PERSONALITY_VARIANTS],
    },
}

_JEWEL_BASE = re.compile(r"(蓝玉|红玉|日象之饰|珠宝|宝石)")
_LIST_ITEM = re.compile(
    r"(?:^|\n)\s*(?:[-*•]|\d+[.)])\s*([^\n:：]{2,40}(?:起点|词缀|变体|roll)?)",
    re.MULTILINE,
)
_QUOTED = re.compile(r"[「『]([^」』]{2,30})[」』]")
_CLASS_START_MOD = re.compile(r"可以从(.+?)的起点配置")
_CLASS_START_MOD_LOOSE = re.compile(r"(?:从|自)(.+?)的起点")


def variant_label_from_mods(mods: list[str] | None) -> str | None:
    """Parse PoE2 class-start jewel mod → e.g. 佣兵起点."""
    for mod in mods or []:
        m = _CLASS_START_MOD.search(mod or "")
        if m:
            return f"{m.group(1).strip()}起点"
    return None


def extract_class_variant_hint(text: str) -> str | None:
    """Best-effort variant label from user text / screenshot OCR (人格分裂)."""
    blob = (text or "").strip()
    if not blob:
        return None
    m = _CLASS_START_MOD.search(blob)
    if m:
        canon = normalize_variant_label(m.group(1).strip())
        return f"{canon}起点" if canon else None
    m = _CLASS_START_MOD_LOOSE.search(blob)
    if m:
        canon = normalize_variant_label(m.group(1).strip())
        return f"{canon}起点" if canon else None
    for lbl, suf in _SPLIT_PERSONALITY_VARIANTS:
        if lbl in blob or suf in blob:
            return lbl
    for alias, canon in (("女巫", "魔巫"), ("行者", "圣堂武僧"), ("圣堂", "圣堂武僧")):
        if alias in blob:
            return f"{canon}起点"
    return None

@dataclass
class ItemProfile:
    item_name: str = ""
    item_name_en: str = ""
    rarity: str = ""  # unique | rare | magic | unknown
    base: str = ""
    variants: list[dict[str, str]] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        return self.item_name or self.item_name_en


def _catalog_entry(name: str) -> dict[str, Any] | None:
    if name in UNIQUE_VARIANT_CATALOG:
        return UNIQUE_VARIANT_CATALOG[name]
    for key, entry in UNIQUE_VARIANT_CATALOG.items():
        if entry.get("cn") == name or entry.get("en") == name:
            return entry
    return None


def _scan_conversation_text(messages: list[dict] | None) -> str:
    if not messages:
        return ""
    parts: list[str] = []
    for msg in messages[-12:]:
        text = extract_text(msg)
        if text:
            parts.append(text)
    return "\n".join(parts)


def build_item_profile(messages: list[dict] | None) -> ItemProfile:
    """Best-effort item profile from recent conversation (no LLM)."""
    blob = _scan_conversation_text(messages)
    profile = ItemProfile()

    for key in UNIQUE_VARIANT_CATALOG:
        entry = UNIQUE_VARIANT_CATALOG[key]
        cn = entry.get("cn") or (key if any("\u4e00" <= c <= "\u9fff" for c in key) else "")
        en = entry.get("en") or key
        if (cn and cn in blob) or (en and en in blob) or key in blob:
            profile.item_name = cn or key
            profile.item_name_en = en
            profile.rarity = entry.get("rarity") or "unique"
            profile.base = entry.get("base") or ""
            profile.variants = list(entry.get("variants") or [])
            return profile

    m = _JEWEL_BASE.search(blob)
    if m:
        profile.base = m.group(1)
        if "RARE" in blob.upper() or "稀有" in blob:
            profile.rarity = "rare"
        elif "UNIQUE" in blob.upper() or "传奇" in blob or "暗金" in blob:
            profile.rarity = "unique"

    return profile


def parse_variants_from_assistant(messages: list[dict] | None) -> list[str]:
    """Extract variant/affix labels mentioned in the last assistant turn."""
    if not messages:
        return []
    last_assistant = ""
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            last_assistant = extract_text(msg)
            break
    if not last_assistant:
        return []

    labels: list[str] = []
    seen: set[str] = set()
    for pat in (_LIST_ITEM, _QUOTED):
        for m in pat.finditer(last_assistant):
            label = (m.group(1) or "").strip().strip("*")
            if len(label) < 2 or label in seen:
                continue
            seen.add(label)
            labels.append(label)

    for cn in CLASS_CN_TO_EN:
        if cn in last_assistant and f"{cn}起点" not in seen:
            lbl = f"{cn}起点"
            seen.add(lbl)
            labels.append(lbl)
    return labels


def build_searches_from_variants(
    item_name: str,
    variants: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Catalog variant rows → trade queries (one affix/variant per search)."""
    name = (item_name or "").strip()
    if not name:
        return []
    out: list[dict[str, str]] = []
    for row in variants:
        label = str(row.get("label") or "").strip()
        suffix = str(row.get("query_suffix") or label).strip()
        if not label:
            continue
        query = f"{name} {suffix}".strip() if suffix and suffix not in name else name
        out.append({"label": label, "query": query})
    return out


def build_searches_from_labels(item_name: str, labels: list[str]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for label in labels:
        label = label.strip()
        if not label:
            continue
        suffix = label.replace("起点", "").strip() or label
        query = f"{item_name} {suffix}".strip() if item_name else label
        out.append({"label": label, "query": query})
    return out
