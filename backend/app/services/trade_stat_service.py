"""Trade stat vector search service.

Stores PoE2 trade stat dictionary entries with embeddings in the `trade_stats` table,
provides semantic search: Chinese user description → vector similarity → stat_id.

Uses BGE-M3 (multilingual) for cross-lingual matching:
  - User types "火抗" or "火焰抗性" → matches "+#% to Fire Resistance" → explicit.stat_3372524247

Ingestion is a one-time operation (re-run when stat dictionary updates with game patches).
Batch embedding: 100 texts per API call → 7200 stats in ~80 seconds.
"""

import json
import os
import logging
import time
from sqlalchemy.orm import Session

from app.models.build import TradeStat
from app.services.embedding_service import get_embedding
from app.services.trade_stats_index import resolve_stat_query, stat_id_to_cn, _load_full_index

logger = logging.getLogger(__name__)

# ── Embedding API config (for batch calls) ──
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "https://api.siliconflow.cn/v1")
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", os.getenv("LLM_API_KEY", ""))
EMBEDDING_API_MODEL = os.getenv("EMBEDDING_API_MODEL", "BAAI/bge-m3")


# ──────────────────────────────────────────────
#  Batch Embedding — fast bulk processing
# ──────────────────────────────────────────────

def _batch_embed(texts: list[str], batch_size: int = 100) -> list[list[float] | None]:
    """Generate embeddings for multiple texts using batch API calls.

    Each API call handles up to `batch_size` texts. Much faster than single calls.
    Falls back to single-text get_embedding() if batch API fails.

    Returns a list of embeddings (or None for failures), same order as input.
    """
    import requests as req

    results: list[list[float] | None] = [None] * len(texts)

    for i in range(0, len(texts), batch_size):
        chunk = texts[i:i + batch_size]
        chunk_indices = list(range(i, i + len(chunk)))

        try:
            resp = req.post(
                f"{EMBEDDING_BASE_URL}/embeddings",
                headers={
                    "Authorization": f"Bearer {EMBEDDING_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={"model": EMBEDDING_API_MODEL, "input": chunk},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()

            # API returns embeddings sorted by index
            for item in data.get("data", []):
                idx = item.get("index", 0)
                actual_idx = chunk_indices[idx] if idx < len(chunk_indices) else None
                if actual_idx is not None:
                    results[actual_idx] = item["embedding"]

        except Exception as e:
            logger.warning(f"Batch embedding failed for chunk {i}-{i+len(chunk)}, falling back: {e}")
            # Fallback: embed one by one
            for j, text in enumerate(chunk):
                try:
                    results[chunk_indices[j]] = get_embedding(text)
                except Exception:
                    pass

    return results


# ──────────────────────────────────────────────
#  Ingestion — full dictionary
# ──────────────────────────────────────────────



def _bilingual_json_path(condensed_path: str) -> str:
    base = os.path.dirname(condensed_path)
    return os.path.join(base, "trade_stats_bilingual.json")


def _load_bilingual_records(json_path: str) -> dict[str, dict]:
    bi_path = _bilingual_json_path(json_path)
    if not os.path.exists(bi_path):
        logger.warning(f"Bilingual stats not found at {bi_path}")
        return {}
    with open(bi_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    stats = payload.get("stats") or {}
    out: dict[str, dict] = {}
    for key, row in stats.items():
        sid = (row.get("id") if isinstance(row, dict) else None) or key
        if isinstance(row, dict):
            out[sid] = row
    return out

def ingest_trade_stats(db: Session, json_path: str, batch_size: int = 100) -> dict:
    """Load condensed stat dictionary, batch-generate embeddings, and store ALL entries.

    No filtering — stores every stat in the dictionary (explicit, implicit, pseudo, etc.).
    With batch embedding: ~7200 stats in ~80 seconds.

    Args:
        db: Database session
        json_path: Path to trade_stats_condensed.json
        batch_size: Number of texts per batch embedding API call

    Returns:
        Summary dict with counts and timing
    """
    t_start = time.time()

    with open(json_path, "r", encoding="utf-8") as f:
        full_dict = json.load(f)

    logger.info(f"Loading {len(full_dict)} stats from {json_path}")

    # Check what's already ingested
    existing_ids = set(
        row[0] for row in db.query(TradeStat.stat_id).all()
    )

    new_stats = []
    skipped = 0

    bilingual = _load_bilingual_records(json_path)

    for stat_id, ref_text in full_dict.items():
        if stat_id in existing_ids:
            skipped += 1
            continue

        stat_type = stat_id.split(".")[0] if "." in stat_id else "unknown"
        bi = bilingual.get(stat_id) or {}
        text_zh = (bi.get("text_cn") or stat_id_to_cn(stat_id) or "").strip()
        if text_zh:
            embed_text = f"[{stat_type}] {ref_text} | {text_zh}"
        else:
            embed_text = f"[{stat_type}] {ref_text}"
        new_stats.append({
            "stat_id": stat_id,
            "ref_text": ref_text,
            "ref_text_zh": text_zh or None,
            "stat_type": stat_type,
            "embed_text": embed_text,
        })

    logger.info(f"New stats to ingest: {len(new_stats)}, already existing: {skipped}")

    if not new_stats:
        return {
            "ingested": 0,
            "failed": 0,
            "skipped": skipped,
            "total_in_db": db.query(TradeStat).count(),
            "elapsed_seconds": 0,
        }

    # Batch generate all embeddings using enriched text
    all_texts = [s["embed_text"] for s in new_stats]
    logger.info(f"Generating {len(all_texts)} embeddings in batches of {batch_size}...")
    t_embed = time.time()

    embeddings = _batch_embed(all_texts, batch_size=batch_size)

    embed_time = time.time() - t_embed
    logger.info(f"Embedding complete in {embed_time:.1f}s")

    # Insert all into DB
    ingested = 0
    failed = 0

    for stat_info, embedding in zip(new_stats, embeddings):
        if embedding is None:
            failed += 1
            continue

        ts = TradeStat(
            stat_id=stat_info["stat_id"],
            ref_text=stat_info["ref_text"],
            ref_text_zh=stat_info.get("ref_text_zh"),
            stat_type=stat_info["stat_type"],
            embedding=embedding,
        )
        db.add(ts)
        ingested += 1

        # Commit every 500 rows to avoid huge transactions
        if ingested % 500 == 0:
            db.commit()

    db.commit()

    total_time = time.time() - t_start
    total_in_db = db.query(TradeStat).count()

    logger.info(
        f"Ingestion complete: {ingested} added, {failed} failed, "
        f"{skipped} skipped, {total_in_db} total in DB, "
        f"{total_time:.1f}s elapsed"
    )

    return {
        "ingested": ingested,
        "failed": failed,
        "skipped": skipped,
        "total_in_db": total_in_db,
        "elapsed_seconds": round(total_time, 1),
    }


def backfill_embeddings(db: Session) -> int:
    """Generate embeddings for any trade_stats rows that are missing them."""
    rows = db.query(TradeStat).filter(TradeStat.embedding == None).all()  # noqa: E711
    if not rows:
        return 0

    texts = [row.ref_text for row in rows]
    embeddings = _batch_embed(texts)

    count = 0
    for row, emb in zip(rows, embeddings):
        if emb:
            row.embedding = emb
            count += 1

    db.commit()
    logger.info(f"Backfilled {count}/{len(rows)} missing embeddings")
    return count


# ──────────────────────────────────────────────
#  Vector Search
# ──────────────────────────────────────────────



def backfill_ref_text_zh(db: Session, json_path: str | None = None) -> int:
    if not json_path:
        json_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "trade_stats_condensed.json")
        if not os.path.exists(json_path):
            json_path = "/app/data/trade_stats_condensed.json"
    bilingual = _load_bilingual_records(json_path)
    if not bilingual:
        return 0
    updated = 0
    for row in db.query(TradeStat).all():
        bi = bilingual.get(row.stat_id) or {}
        text_zh = (bi.get("text_cn") or stat_id_to_cn(row.stat_id) or "").strip()
        if text_zh and row.ref_text_zh != text_zh:
            row.ref_text_zh = text_zh
            updated += 1
    db.commit()
    logger.info(f"backfill_ref_text_zh: updated {updated} rows")
    return updated

def search_stats(
    db: Session,
    query: str,
    top_k: int = 3,
    stat_type: str | None = None,
    min_similarity: float = 0.35,
) -> list[dict]:
    """Find trade stat IDs matching a natural language description.

    Args:
        db: Database session
        query: Chinese or English description (e.g. "火焰抗性" or "Fire Resistance")
        top_k: Max number of results
        stat_type: Optional filter (explicit, pseudo, etc.)
        min_similarity: Minimum cosine similarity threshold (0-1)

    Returns:
        List of {"stat_id": str, "ref_text": str, "similarity": float}
    """
    exact_id = resolve_stat_query(query)
    if exact_id:
        row = db.query(TradeStat).filter(TradeStat.stat_id == exact_id).first()
        ref_text = row.ref_text if row else ""
        if not ref_text:
            _load_full_index()
            from app.services.trade_stats_index import _full_stat_dict as _fsd
            ref_text = _fsd.get(exact_id, "") if _fsd else ""
        stype = exact_id.split(".")[0] if "." in exact_id else (row.stat_type if row else "explicit")
        return [{
            "stat_id": exact_id,
            "ref_text": ref_text,
            "stat_type": stype,
            "similarity": 1.0,
        }]

    query_embedding = get_embedding(query)
    if not query_embedding:
        logger.warning(f"Failed to generate embedding for query: '{query}'")
        return []

    db_url = str(db.get_bind().url)
    is_sqlite = db_url.startswith("sqlite")

    if is_sqlite:
        return _search_sqlite(db, query_embedding, top_k, stat_type, min_similarity)
    else:
        return _search_postgres(db, query_embedding, top_k, stat_type, min_similarity)


def _search_postgres(
    db: Session,
    query_embedding: list[float],
    top_k: int,
    stat_type: str | None,
    min_similarity: float,
) -> list[dict]:
    """pgvector cosine distance search."""
    distance_col = TradeStat.embedding.cosine_distance(query_embedding).label("distance")

    q = db.query(TradeStat, distance_col).filter(
        TradeStat.embedding != None,  # noqa: E711
    )

    if stat_type:
        q = q.filter(TradeStat.stat_type == stat_type)

    q = q.order_by(distance_col).limit(top_k * 2)

    results = []
    for stat, distance in q.all():
        similarity = round(1.0 - distance, 4) if distance is not None else 0
        if similarity >= min_similarity:
            results.append({
                "stat_id": stat.stat_id,
                "ref_text": stat.ref_text,
                "stat_type": stat.stat_type,
                "similarity": similarity,
            })

    return results[:top_k]


def _search_sqlite(
    db: Session,
    query_embedding: list[float],
    top_k: int,
    stat_type: str | None,
    min_similarity: float,
) -> list[dict]:
    """In-memory cosine similarity search (dev/test fallback)."""
    q = db.query(TradeStat).filter(TradeStat.embedding != None)  # noqa: E711
    if stat_type:
        q = q.filter(TradeStat.stat_type == stat_type)

    stats = q.all()
    scored = []

    for stat in stats:
        if stat.embedding:
            emb = stat.embedding
            if isinstance(emb, str):
                emb = json.loads(emb)
            sim = _cosine_similarity(query_embedding, emb)
            if sim >= min_similarity:
                scored.append({
                    "stat_id": stat.stat_id,
                    "ref_text": stat.ref_text,
                    "stat_type": stat.stat_type,
                    "similarity": round(sim, 4),
                })

    scored.sort(key=lambda x: x["similarity"], reverse=True)
    return scored[:top_k]


# ──────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────

def get_ingest_stats(db: Session) -> dict:
    """Get trade stats table statistics."""
    total = db.query(TradeStat).count()
    with_emb = db.query(TradeStat).filter(TradeStat.embedding != None).count()  # noqa: E711
    without_emb = total - with_emb

    from sqlalchemy import func
    type_counts = dict(
        db.query(TradeStat.stat_type, func.count(TradeStat.id))
        .group_by(TradeStat.stat_type)
        .all()
    )

    return {
        "total": total,
        "with_embedding": with_emb,
        "without_embedding": without_emb,
        "by_type": type_counts,
    }


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if not a or not b:
        return 0.0
    try:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
    except Exception:
        return 0.0


def clear_trade_stats(db: Session) -> int:
    """Delete all trade stats from the database (for re-ingestion)."""
    count = db.query(TradeStat).delete()
    db.commit()
    logger.info(f"Cleared {count} trade stats from database")
    return count
