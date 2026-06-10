"""extract_game_aliases.py — 从 knowledge_chunks 向量库抽取 CN↔EN 游戏实体名映射。

从 poe2db / PoB / poe2wiki 的 chunk 中提取：
  - 技能宝石 (skill/gem)：CN name / EN name
  - 装备/暗金 (item/unique)：CN name / EN name
  - 词缀 (mod)：CN text / EN text
  - 天赋节点 (passive/asc_nodes)：CN name / EN name

输出 game_aliases.json，作为检索层精确匹配的 O(1) 查表字典。
"""
import json
import re
import os
import sys

# Allow running from /app or from local
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.database import SessionLocal
from app.models import KnowledgeChunk


def extract_name_pairs(chunk_content: str, content_type: str) -> list[dict]:
    """从 chunk 的 content JSON 中提取 CN-EN 名称对。"""
    pairs = []
    try:
        data = json.loads(chunk_content) if isinstance(chunk_content, str) else chunk_content
    except (json.JSONDecodeError, TypeError):
        return pairs

    search_text = data.get("search_text", "")
    title_cn = data.get("title_cn", "") or data.get("name_cn", "") or data.get("name", "")
    title_en = data.get("title_en", "") or data.get("name_en", "")

    # poe2db format: has title_cn/title_en directly
    if title_cn and title_en and title_cn != title_en:
        pairs.append({
            "cn": title_cn.strip(),
            "en": title_en.strip(),
            "type": content_type,
            "source": "poe2db",
        })
        return pairs

    # PoB format: search_text may contain "CN name / EN name" or just EN
    # Try to extract from search_text patterns
    # e.g. "Fireball" or "火球术 / Fireball"
    if search_text:
        # Check for "CN / EN" pattern
        slash_parts = search_text.split(" / ")
        if len(slash_parts) >= 2:
            cn_candidate = slash_parts[-2].strip()
            en_candidate = slash_parts[-1].strip()
            if _has_cjk(cn_candidate) and not _has_cjk(en_candidate):
                pairs.append({
                    "cn": cn_candidate,
                    "en": en_candidate,
                    "type": content_type,
                    "source": "pob",
                })

    return pairs


def _has_cjk(text: str) -> bool:
    """Check if text contains CJK characters."""
    return bool(re.search(r'[一-鿿㐀-䶿]', text))


def extract_all(output_path: str = "game_aliases.json"):
    """Scan all knowledge_chunks and extract CN-EN name pairs."""
    db = SessionLocal()
    try:
        # Process in batches to avoid loading everything into memory
        total = db.query(KnowledgeChunk).count()
        print(f"Total chunks: {total}")

        aliases: dict[str, dict] = {}  # cn_name → {en, type, source}
        batch_size = 1000
        seen_cn = set()

        for offset in range(0, total, batch_size):
            chunks = (
                db.query(KnowledgeChunk)
                .filter(KnowledgeChunk.content.isnot(None))
                .offset(offset)
                .limit(batch_size)
                .all()
            )

            for chunk in chunks:
                pairs = extract_name_pairs(chunk.content, chunk.chunk_type)
                for pair in pairs:
                    cn = pair["cn"]
                    if cn in seen_cn or len(cn) < 2 or len(cn) > 80:
                        continue
                    seen_cn.add(cn)
                    aliases[cn] = {
                        "en": pair["en"],
                        "type": pair["type"],
                        "source": pair["source"],
                    }

            print(f"  Processed {min(offset + batch_size, total)}/{total}, "
                  f"found {len(aliases)} unique CN names")

        # Also build reverse index: en → cn
        en_aliases: dict[str, dict] = {}
        for cn, info in aliases.items():
            en = info["en"].lower()
            if en not in en_aliases:
                en_aliases[en] = {"cn": cn, "type": info["type"], "source": info["source"]}

        output = {
            "cn_to_en": aliases,
            "en_to_cn": en_aliases,
            "total_cn": len(aliases),
            "total_en": len(en_aliases),
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"\nSaved {len(aliases)} CN entries + {len(en_aliases)} EN entries to {output_path}")

    finally:
        db.close()


if __name__ == "__main__":
    output = sys.argv[1] if len(sys.argv) > 1 else "/app/data/game_aliases.json"
    extract_all(output)
