"""inject_cn_ascendancy.py — 给所有 asc_nodes 的 search_text 注入国服中文名，重做 embedding。

运行一次即修复全部 22 个升华的跨语言检索，不再逐一手工修。
"""
import json
import os
import sys
import requests

_proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _proj_root)
from app.core.database import SessionLocal
from app.models.build import KnowledgeChunk

# EN ascendancy name → CN name (from Tencent official)
ASC_EN_TO_CN: dict[str, str] = {
    "Infernalist": "驱炎使",
    "Blood Mage": "命源法师",
    "Lich": "巫妖",
    "Stormweaver": "风暴编织者",
    "Chronomancer": "塑时术师",
    "Disciple of Varashta": "瓦拉煞的门徒",
    "Titan": "泰坦",
    "Warbringer": "战争使者",
    "Smith of Kitava": "奇塔弗匠师",
    "Deadeye": "锐眼",
    "Pathfinder": "追猎者",
    "Invoker": "祈求者",
    "Spirit Walker": "灵魂行者",
    "Acolyte of Chayula": "夏乌拉追随者",
    "Witchhunter": "猎巫人",
    "Gemling Legionnaire": "古灵使徒斗士",
    "Tactician": "战术家",
    "Amazon": "亚马逊",
    "Ritualist": "仪祭师",
    "Oracle": "神谕者",
    "Shaman": "萨满",
    # Martial Artist is not an official ascendancy (duplicate?)
    "Martial Artist": "武艺家",
}

EMBEDDING_URL = os.getenv("EMBEDDING_API_URL", "https://api.siliconflow.cn/v1/embeddings")
EMBEDDING_KEY = os.getenv("EMBEDDING_API_KEY", "")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")


def get_embedding(text: str) -> list[float] | None:
    """Generate embedding via BGE-M3 API."""
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
        print(f"Embedding API error: {resp.status_code} {resp.text[:200]}")
        return None
    except Exception as e:
        print(f"Embedding API exception: {e}")
        return None


def inject():
    db = SessionLocal()
    try:
        chunks = db.query(KnowledgeChunk).filter(
            KnowledgeChunk.chunk_type == "asc_nodes"
        ).all()

        updated, skipped, failed = 0, 0, 0
        for chunk in chunks:
            try:
                data = json.loads(chunk.content)
            except (json.JSONDecodeError, TypeError):
                failed += 1
                continue

            en_name = data.get("name", "")
            cn_name = ASC_EN_TO_CN.get(en_name)
            if not cn_name:
                print(f"  SKIP: no CN mapping for '{en_name}'")
                skipped += 1
                continue

            old_search_text = data.get("search_text", "")
            # Prepend CN name and EN name for cross-lingual embedding
            new_search_text = f"{cn_name} ({en_name})\n{old_search_text}"

            # Check if already has CN (idempotent)
            if old_search_text.startswith(cn_name):
                print(f"  SKIP: {cn_name} ({en_name}) already has CN prefix")
                skipped += 1
                continue

            # Re-embed
            embedding = get_embedding(new_search_text)
            if not embedding:
                failed += 1
                continue

            data["search_text"] = new_search_text
            chunk.content = json.dumps(data, ensure_ascii=False)
            chunk.embedding = embedding

            print(f"  OK: {cn_name} ({en_name})")
            updated += 1

        if updated > 0:
            db.commit()
        print(f"\nDone: {updated} updated, {skipped} skipped, {failed} failed")

    finally:
        db.close()


if __name__ == "__main__":
    inject()
