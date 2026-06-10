"""inject_cn_names.py — 批量给 knowledge_chunks 注入中文名，重做 embedding。

从 caimogu_skills.json 匹配技能，从 game_aliases.json 匹配装备/词缀。
匹配到的 chunk：search_text 前加 "CN名 (EN名)\n"，重做 BGE-M3 embedding。
"""
import json
import os
import sys
import requests

_proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _proj_root)
from app.core.database import SessionLocal
from app.models.build import KnowledgeChunk

EMBEDDING_URL = os.getenv("EMBEDDING_API_URL", "https://api.siliconflow.cn/v1/embeddings")
EMBEDDING_KEY = os.getenv("EMBEDDING_API_KEY", "")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")


def get_embedding(text: str) -> list[float] | None:
    if not EMBEDDING_KEY:
        print("ERROR: EMBEDDING_API_KEY not set")
        return None
    try:
        resp = requests.post(
            EMBEDDING_URL,
            headers={"Authorization": f"Bearer {EMBEDDING_KEY}"},
            json={"model": EMBEDDING_MODEL, "input": [text]},
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json()["data"][0]["embedding"]
        print(f"  Embed API error {resp.status_code}: {resp.text[:150]}")
        return None
    except Exception as e:
        print(f"  Embed API exception: {e}")
        return None


def load_alias_maps(data_dir: str) -> dict[str, str]:
    """Load CN→EN alias maps from all available sources.
    Returns: {lowercase_en_name: cn_name}
    """
    en_to_cn: dict[str, str] = {}

    # 1. caimogu skills
    skills_path = os.path.join(data_dir, "caimogu_skills.json")
    if os.path.exists(skills_path):
        with open(skills_path, "r", encoding="utf-8") as f:
            skills = json.load(f)
        for s in skills:
            en_lower = s["en"].lower().strip()
            if en_lower not in en_to_cn:
                en_to_cn[en_lower] = s["cn"]
        print(f"Loaded {len(skills)} caimogu skills")

    # 2. game_aliases.json (items, mods from poe2db)
    aliases_path = os.path.join(data_dir, "game_aliases.json")
    if os.path.exists(aliases_path):
        with open(aliases_path, "r", encoding="utf-8") as f:
            aliases = json.load(f)
        en_to_cn_map = aliases.get("en_to_cn", {})
        for en_lower, info in en_to_cn_map.items():
            if en_lower not in en_to_cn:
                en_to_cn[en_lower] = info.get("cn", "")
        print(f"Loaded {len(en_to_cn_map)} poe2db item/mod aliases")

    return en_to_cn


def match_chunk(data: dict, chunk_type: str, en_to_cn: dict[str, str]) -> str | None:
    """Try to find a CN name for this chunk. Returns CN name or None."""
    # Strategy 1: extract EN name from chunk data
    en_name = ""

    if chunk_type in ("skill", "gem"):
        # poe2db skills: search_text has [EN] {"name": "..."}
        st = data.get("search_text", "")
        import re
        m = re.search(r'"name":\s*"([^"]+)"', st)
        if m:
            en_name = m.group(1)
        else:
            en_name = data.get("name_en", "") or data.get("name", "")
        # PoB gems: name field
        if not en_name:
            en_name = data.get("name", "")

    elif chunk_type == "item":
        en_name = data.get("name_en", "") or data.get("name", "")

    elif chunk_type == "mod":
        # Mods are free text, try matching against known mod names
        en_data_raw = data.get("en_data", "")
        if isinstance(en_data_raw, str):
            try:
                en_data = json.loads(en_data_raw)
                en_mods = en_data.get("explicit_mods", [])
                if en_mods:
                    for mod_text in en_mods:
                        cn = en_to_cn.get(mod_text.lower().strip())
                        if cn:
                            return cn  # Return first match
            except (json.JSONDecodeError, TypeError):
                pass
        return None  # Mods handled differently

    if not en_name:
        return None

    # Try exact match first, then normalized
    en_key = en_name.lower().strip()
    cn = en_to_cn.get(en_key)

    if not cn:
        # Try without underscores
        normalized = en_key.replace("_", " ")
        cn = en_to_cn.get(normalized)

    return cn


def inject(data_dir: str, dry_run: bool = False):
    """Main injection loop."""
    en_to_cn = load_alias_maps(data_dir)
    if not en_to_cn:
        print("No alias data loaded, aborting")
        return
    print(f"Total alias entries: {len(en_to_cn)}")

    db = SessionLocal()
    try:
        # Query chunks that could benefit from CN injection
        chunk_types = ["skill", "gem", "item"]
        total = (
            db.query(KnowledgeChunk)
            .filter(KnowledgeChunk.chunk_type.in_(chunk_types))
            .count()
        )
        print(f"Chunks to process (skill/gem/item): {total}")

        updated, skipped, failed = 0, 0, 0
        batch_size = 500
        processed = 0

        for offset in range(0, total, batch_size):
            chunks = (
                db.query(KnowledgeChunk)
                .filter(KnowledgeChunk.chunk_type.in_(chunk_types))
                .offset(offset).limit(batch_size).all()
            )

            for chunk in chunks:
                processed += 1
                try:
                    data = json.loads(chunk.content)
                except (json.JSONDecodeError, TypeError):
                    failed += 1
                    continue

                cn_name = match_chunk(data, chunk.chunk_type, en_to_cn)
                if not cn_name:
                    skipped += 1
                    continue

                old_search_text = data.get("search_text", "")

                # Skip if already has CJK prefix
                if old_search_text and any(ord(ch) > 0x2000 for ch in old_search_text[:20]):
                    skipped += 1
                    continue

                new_search_text = f"{cn_name}\n{old_search_text}"

                if dry_run:
                    updated += 1
                    if updated <= 3:
                        print(f"  [DRY] {cn_name} ← {chunk.chunk_type}/{chunk.source}")
                    continue

                embedding = get_embedding(new_search_text)
                if not embedding:
                    failed += 1
                    continue

                data["search_text"] = new_search_text
                chunk.content = json.dumps(data, ensure_ascii=False)
                chunk.embedding = embedding
                updated += 1

            if not dry_run and offset % 2000 == 0:
                db.flush()
            print(f"  {min(offset + batch_size, total)}/{total}: "
                  f"{updated} updated, {skipped} skipped, {failed} failed")

        if not dry_run and updated > 0:
            db.commit()
        print(f"\nDone: {updated} updated, {skipped} skipped, {failed} failed "
              f"({'DRY RUN' if dry_run else 'committed'})")

    finally:
        db.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="/app/data")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    inject(args.data_dir, dry_run=args.dry_run)
