#!/usr/bin/env python3
"""Audit CN↔EN alias gaps for unique items (沉默之雷 class of bugs).

Run on NAS: docker exec poe2li-backend python /app/scripts/audit_cn_en_aliases.py
Or locally with DATABASE_URL / data files.
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.name_validation import is_concatenated_name, is_trusted_en_name

DATA_DIR = "/app/data" if os.path.isdir("/app/data") else os.path.join(
    os.path.dirname(__file__), "..", "data"
)


def _load_json(path: str, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_reference_uniques() -> list[dict]:
    """poe2db CN unique index (name + slug path)."""
    for rel in (
        os.path.join(os.path.dirname(__file__), "..", "app", "services", "poe2db_uniques.json"),
        os.path.join(DATA_DIR, "poe2db_uniques.json"),
    ):
        if os.path.exists(rel):
            raw = _load_json(rel, [])
            out = []
            for row in raw:
                slug = row.get("slug", "")
                path = slug.replace("/cn/", "").replace("/us/", "")
                out.append({
                    "cn": row.get("name", "").strip(),
                    "path": path,
                    "base_cn": row.get("base_type", ""),
                })
            return out
    return []


def load_game_aliases() -> dict[str, str]:
    ga = _load_json(os.path.join(DATA_DIR, "game_aliases.json"), {})
    return {cn: info.get("en", "") for cn, info in ga.get("cn_to_en", {}).items()}


def load_caimogu_items() -> dict[str, str]:
    raw = _load_json(os.path.join(DATA_DIR, "caimogu_items.json"), [])
    return {r.get("cn", "").strip(): r.get("en", "").strip() for r in raw if r.get("cn")}


def load_curated() -> dict[str, str]:
    from app.services.entity_dict import ITEM_CN_ALIASES
    return dict(ITEM_CN_ALIASES)


def load_chunk_pairs() -> dict[str, str]:
    """CN→name_en from ingested poe2db unique chunks."""
    pairs: dict[str, str] = {}
    jsonl = os.path.join(DATA_DIR, "poe2db_uniques.jsonl")
    if not os.path.exists(jsonl):
        return pairs
    with open(jsonl, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            name_en = d.get("name_en", "")
            cn_raw = d.get("cn_data", "")
            if not cn_raw:
                continue
            try:
                cn_d = json.loads(cn_raw) if isinstance(cn_raw, str) else cn_raw
                cn = cn_d.get("name", "").strip()
            except Exception:
                continue
            if cn and name_en and cn not in pairs:
                pairs[cn] = name_en
    return pairs


def is_likely_literal_trap(cn: str, en: str) -> bool:
    """Heuristic: EN looks like word-by-word translation of CN, not official name."""
    if not cn or not en:
        return False
    # Official names are usually not pure dictionary English for poetic CN
    cn_chars = re.findall(r"[一-鿿]", cn)
    if len(cn_chars) < 2:
        return False
    en_words = set(re.findall(r"[a-zA-Z]{3,}", en.lower()))
    # 沉默之雷 -> silence + thunder style (if someone translated literally)
    trap_words = {
        "silence", "silent", "thunder", "lightning", "fire", "ice", "frost",
        "blood", "shadow", "storm", "wind", "death", "life", "soul",
    }
    if en_words & trap_words and en.lower() not in (cn.lower(),):
        # Poetic CN with generic EN words — suspicious only if EN is common words
        if len(en_words) <= 3 and en_words & trap_words:
            return True
    return False


def main():
    ref = load_reference_uniques()
    game = load_game_aliases()
    caimogu = load_caimogu_items()
    curated = load_curated()
    chunks = load_chunk_pairs()

    missing_in_game: list[dict] = []
    missing_resolver: list[dict] = []
    dirty_en_in_game: list[dict] = []
    en_mismatch: list[dict] = []
    literal_trap_risk: list[dict] = []

    for row in ref:
        cn = row["cn"]
        if not cn:
            continue
        path = row["path"]
        chunk_en = chunks.get(cn, "")
        game_en = game.get(cn, "")
        caimogu_en = caimogu.get(cn, "")
        curated_en = curated.get(cn, "")

        if cn not in game:
            missing_in_game.append({**row, "chunk_en": chunk_en})

        if not any([game_en, caimogu_en, curated_en, chunk_en]):
            missing_resolver.append(row)
        elif not game_en and not caimogu_en and not curated_en:
            # only in chunks — resolver needs reload or cache
            pass

        if game_en and is_concatenated_name(game_en):
            dirty_en_in_game.append({"cn": cn, "en": game_en, "path": path})

        if game_en and not is_trusted_en_name(game_en):
            dirty_en_in_game.append({"cn": cn, "en": game_en, "path": path, "reason": "untrusted"})

        # chunk vs game mismatch
        if chunk_en and game_en and chunk_en != game_en:
            en_mismatch.append({"cn": cn, "chunk_en": chunk_en, "game_en": game_en, "path": path})

        # LLM literal-translation risk when no alias
        best_en = curated_en or caimogu_en or game_en or chunk_en
        if not best_en and cn:
            literal_trap_risk.append({**row, "risk": "no_en_alias"})
        elif best_en and is_likely_literal_trap(cn, best_en):
            literal_trap_risk.append({**row, "en": best_en, "risk": "literal_shape"})

    print("=== CN unique alias audit ===")
    print(f"Reference uniques (poe2db index): {len(ref)}")
    print(f"game_aliases CN entries:          {len(game)}")
    print(f"chunk pairs (jsonl):              {len(chunks)}")
    print(f"caimogu_items:                    {len(caimogu)}")
    print(f"curated ITEM_CN_ALIASES:          {len(curated)}")
    print()
    print(f"1. CN in index but NOT in game_aliases:     {len(missing_in_game)}")
    print(f"2. CN with NO resolver source at all:     {len(missing_resolver)}")
    print(f"3. Dirty/untrusted EN in game_aliases:      {len(dirty_en_in_game)}")
    print(f"4. chunk_en != game_en mismatch:            {len(en_mismatch)}")
    print(f"5. Literal-translation risk (heuristic):   {len(literal_trap_risk)}")
    print()

    def _sample(title: str, items: list, n=15):
        if not items:
            return
        print(f"--- {title} (show {min(n, len(items))}/{len(items)}) ---")
        for x in items[:n]:
            print(f"  {x}")
        print()

    _sample("Missing from game_aliases", missing_in_game)
    _sample("No resolver source", missing_resolver)
    _sample("Dirty EN in game_aliases", dirty_en_in_game)
    _sample("EN mismatch", en_mismatch)

    # High priority: missing from game but have chunk_en (like 沉默之雷 before fix)
    fixable = [x for x in missing_in_game if x.get("chunk_en")]
    print(f"Auto-fixable via game_aliases regen (have chunk_en): {len(fixable)}")

    # Curated-only candidates: poetic CN, no game alias, have chunk_en
    need_curated = [
        x for x in missing_in_game
        if x.get("chunk_en") and x["cn"] not in curated
    ]
    print(f"Worth curated ITEM_CN_ALIASES (missing game, have chunk_en): {len(need_curated)}")
    _sample("Curated candidates", need_curated, 20)

    report_path = os.path.join(DATA_DIR, "alias_audit_report.json")
    report = {
        "summary": {
            "reference_uniques": len(ref),
            "game_aliases": len(game),
            "missing_in_game": len(missing_in_game),
            "missing_resolver": len(missing_resolver),
            "dirty_en": len(dirty_en_in_game),
            "en_mismatch": len(en_mismatch),
            "literal_trap_risk": len(literal_trap_risk),
        },
        "missing_in_game": missing_in_game,
        "literal_trap_risk": literal_trap_risk,
        "need_curated": need_curated,
    }
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nFull report: {report_path}")


if __name__ == "__main__":
    main()
