"""extract_game_aliases.py — 从 knowledge_chunks 向量库抽取 CN↔EN 游戏实体名映射。

数据来源：
  - poe2db items (528): cn_data 为 JSON 字符串，含 CN name
  - poe2db mods (273): cn_data 含 CN 词缀文本
  - poe2db skills (1830): 暂无 cn_data（v3 详情页未入库），需从 caimogu 另补

输出 game_aliases.json，作为检索层精确匹配的 O(1) 查表字典。
"""
import json
import re
import os
import sys

_proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _proj_root)
from app.core.database import SessionLocal
from app.models.build import KnowledgeChunk
from app.services.name_validation import validate_name_en


def extract_poe2db_item(content_json: dict) -> dict | None:
    """extract CN↔EN from poe2db item chunk."""
    name_en = content_json.get("name_en", "")
    cn_data_raw = content_json.get("cn_data", "")
    if not name_en or not cn_data_raw:
        return None
    try:
        cn_data = json.loads(cn_data_raw) if isinstance(cn_data_raw, str) else cn_data_raw
        name_cn = cn_data.get("name", "")
        if name_cn and _has_cjk(name_cn):
            ok, clean_en = validate_name_en(name_en.strip(), name_en.strip())
            if not ok:
                return None
            return {"cn": name_cn.strip(), "en": clean_en}
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def extract_poe2db_mod(content_json: dict) -> list[dict]:
    """extract CN↔EN mod pairs from poe2db mod chunk."""
    pairs = []
    cn_data_raw = content_json.get("cn_data", "")
    en_data_raw = content_json.get("en_data", "")
    if not cn_data_raw or not en_data_raw:
        return pairs
    try:
        cn_data = json.loads(cn_data_raw) if isinstance(cn_data_raw, str) else cn_data_raw
        en_data = json.loads(en_data_raw) if isinstance(en_data_raw, str) else en_data_raw
        cn_mods = cn_data.get("explicit_mods", []) + cn_data.get("implicit_mods", [])
        en_mods = en_data.get("explicit_mods", []) + en_data.get("implicit_mods", [])
        # Heuristic: pair by position (poe2db preserves order)
        for i, cn_text in enumerate(cn_mods):
            en_text = en_mods[i] if i < len(en_mods) else ""
            if _has_cjk(cn_text) and en_text and len(cn_text) > 2:
                pairs.append({"cn": cn_text.strip(), "en": en_text.strip()})
    except (json.JSONDecodeError, TypeError):
        pass
    return pairs


def extract_poe2db_skill(content_json: dict) -> dict | None:
    """extract CN↔EN from poe2db skill chunk (v3 detail).
    Skills currently lack cn_data — stub for future ingestion.
    """
    cn_data_raw = content_json.get("cn_data", "")
    name_en = content_json.get("name_en", "")
    if not cn_data_raw or not name_en:
        # Fallback: extract EN name from search_text
        st = content_json.get("search_text", "")
        en_match = re.search(r'"name":\s*"([^"]+)"', st)
        if en_match:
            name_en = en_match.group(1)
        return None  # No CN data yet
    try:
        cn_data = json.loads(cn_data_raw) if isinstance(cn_data_raw, str) else cn_data_raw
        name_cn = cn_data.get("name", "")
        if name_cn and _has_cjk(name_cn):
            return {"cn": name_cn.strip(), "en": name_en.strip()}
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def _has_cjk(text: str) -> bool:
    return bool(re.search(r'[一-鿿㐀-䶿]', text))


def extract_all(output_path: str = "game_aliases.json"):
    db = SessionLocal()
    try:
        total = db.query(KnowledgeChunk).count()
        print(f"Total chunks: {total}")

        aliases: dict[str, dict] = {}
        seen_cn: set[str] = set()
        batch_size = 1000

        for offset in range(0, total, batch_size):
            chunks = (
                db.query(KnowledgeChunk)
                .filter(KnowledgeChunk.content.isnot(None))
                .offset(offset).limit(batch_size).all()
            )

            for chunk in chunks:
                ctype = chunk.chunk_type
                if chunk.source != "poe2db":
                    continue  # Only poe2db has CN data
                try:
                    data = json.loads(chunk.content)
                except (json.JSONDecodeError, TypeError):
                    continue

                if ctype == "item":
                    pair = extract_poe2db_item(data)
                    if pair:
                        _add_alias(aliases, seen_cn, pair, ctype)
                elif ctype == "mod":
                    for pair in extract_poe2db_mod(data):
                        _add_alias(aliases, seen_cn, pair, ctype)
                elif ctype == "skill":
                    pair = extract_poe2db_skill(data)
                    if pair:
                        _add_alias(aliases, seen_cn, pair, ctype)

            print(f"  {min(offset + batch_size, total)}/{total}, "
                  f"{len(aliases)} unique CN names")

        # Reverse index
        en_aliases: dict[str, dict] = {}
        for cn, info in aliases.items():
            en_lower = info["en"].lower()
            if en_lower not in en_aliases:
                en_aliases[en_lower] = {"cn": cn, "type": info["type"], "source": info["source"]}

        output = {
            "cn_to_en": {k: v for k, v in sorted(aliases.items())},
            "en_to_cn": {k: v for k, v in sorted(en_aliases.items())},
            "total_cn": len(aliases),
            "total_en": len(en_aliases),
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"\nSaved {len(aliases)} CN + {len(en_aliases)} EN entries → {output_path}")

    finally:
        db.close()


def _add_alias(aliases: dict, seen: set, pair: dict, ctype: str):
    cn = pair["cn"]
    if cn in seen or len(cn) < 2 or len(cn) > 120:
        return
    seen.add(cn)
    aliases[cn] = {"en": pair["en"], "type": ctype, "source": "poe2db"}


if __name__ == "__main__":
    output = sys.argv[1] if len(sys.argv) > 1 else "/app/data/game_aliases.json"
    extract_all(output)
