"""Knowledge graph: entity/edge extraction and multi-hop expansion for RAG."""

from __future__ import annotations

import json
import logging
import re

from sqlalchemy.orm import Session

from app.models.build import KnowledgeChunk
from app.models.knowledge_graph import KbEdge, KbEntity

logger = logging.getLogger(__name__)

RELATION_MENTIONS = "mentions"
RELATION_PROVIDED_BY = "provided_by"
RELATION_IS_A = "is_a"

# Priority for graph traversal (higher first)
RELATION_PRIORITY = {
    RELATION_MENTIONS: 3,
    RELATION_IS_A: 2,
    RELATION_PROVIDED_BY: 1,
}


def _safe_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _parse_chunk_content(chunk: KnowledgeChunk) -> tuple[dict, str]:
    try:
        data = json.loads(chunk.content)
        if isinstance(data, dict):
            return data, data.get("search_text", chunk.content or "")
    except (json.JSONDecodeError, TypeError):
        pass
    return {}, chunk.content or ""


def _entity_key_for_chunk(chunk: KnowledgeChunk, data: dict) -> str:
    ctype = chunk.chunk_type or data.get("content_type", "unknown")
    name = (
        data.get("name_en")
        or data.get("chunk_id")
        or data.get("name")
        or f"chunk_{chunk.id}"
    )
    safe = re.sub(r"[^\w\-]+", "_", str(name))[:120]
    return f"{ctype}:{safe}"


def upsert_entity(
    db: Session,
    entity_key: str,
    entity_type: str,
    *,
    name_en: str | None = None,
    name_cn: str | None = None,
    aliases: list[str] | None = None,
    chunk_id: int | None = None,
    league: str | None = None,
    game_version: str | None = None,
) -> KbEntity:
    row = db.query(KbEntity).filter(KbEntity.entity_key == entity_key).first()
    alias_json = json.dumps(list(dict.fromkeys(aliases or [])), ensure_ascii=False) if aliases else None

    if row is None:
        row = KbEntity(
            entity_key=entity_key,
            entity_type=entity_type,
            name_en=name_en,
            name_cn=name_cn,
            aliases=alias_json,
            chunk_id=chunk_id,
            league=league,
            game_version=game_version,
        )
        db.add(row)
        db.flush()
        return row

    if name_en and not row.name_en:
        row.name_en = name_en
    if name_cn and not row.name_cn:
        row.name_cn = name_cn
    if chunk_id and not row.chunk_id:
        row.chunk_id = chunk_id
    if aliases:
        merged = list(dict.fromkeys(_safe_json_list(row.aliases) + aliases))
        row.aliases = json.dumps(merged, ensure_ascii=False)
    return row


def upsert_edge(
    db: Session,
    src_id: int,
    dst_id: int,
    relation: str,
    *,
    weight: float = 1.0,
    source_chunk_id: int | None = None,
) -> None:
    if src_id == dst_id:
        return
    existing = (
        db.query(KbEdge)
        .filter(
            KbEdge.src_entity_id == src_id,
            KbEdge.dst_entity_id == dst_id,
            KbEdge.relation == relation,
        )
        .first()
    )
    if existing:
        existing.weight = max(existing.weight, weight)
        return
    db.add(KbEdge(
        src_entity_id=src_id,
        dst_entity_id=dst_id,
        relation=relation,
        weight=weight,
        source_chunk_id=source_chunk_id,
    ))


def extract_edges_from_text(
    db: Session,
    src_entity: KbEntity,
    search_text: str,
    chunk_id: int,
) -> int:
    """Rule-based edge extraction from chunk text. Returns edge count created."""
    from app.services.concept_links import CONCEPT_HOOKS
    from app.services.entity_resolver import resolve_all_entities
    from app.services.retrieval_pipeline import find_concepts_in_query

    created = 0
    text_lower = search_text.lower()

    # Named entities mentioned in text
    for en_name, cn_name, etype in resolve_all_entities(search_text):
        dst = upsert_entity(
            db,
            f"{etype}:{en_name}",
            etype,
            name_en=en_name,
            name_cn=cn_name,
            aliases=[cn_name] if cn_name else None,
        )
        upsert_edge(db, src_entity.id, dst.id, RELATION_MENTIONS, source_chunk_id=chunk_id)
        created += 1

    # Mechanism concept hooks
    for keyword, (ctype, _) in CONCEPT_HOOKS.items():
        if keyword.lower() in text_lower:
            dst = upsert_entity(
                db,
                f"concept:{keyword}",
                "mechanic" if ctype == "wiki" else ctype,
                name_cn=keyword if any("\u4e00" <= c <= "\u9fff" for c in keyword) else None,
                name_en=keyword if keyword.isascii() else None,
            )
            upsert_edge(db, src_entity.id, dst.id, RELATION_MENTIONS, weight=1.2, source_chunk_id=chunk_id)
            created += 1

    # Trade effect concepts (item/mod provides effect)
    if src_entity.entity_type in ("item", "mod", "gem"):
        for concept_name, entry in find_concepts_in_query(search_text):
            label = entry.get("aliases", [concept_name])[0]
            dst = upsert_entity(
                db,
                f"effect:{concept_name}",
                "keyword",
                name_en=concept_name,
                name_cn=label,
            )
            upsert_edge(db, dst.id, src_entity.id, RELATION_PROVIDED_BY, source_chunk_id=chunk_id)
            created += 1

    return created


def sync_chunk_graph(db: Session, chunk: KnowledgeChunk) -> KbEntity | None:
    """Create/update entity and edges for a single knowledge chunk."""
    if not chunk.id:
        db.flush()

    data, search_text = _parse_chunk_content(chunk)
    if not search_text.strip():
        return None

    entity_key = _entity_key_for_chunk(chunk, data)
    name_en = data.get("name_en") or data.get("name")
    name_cn = data.get("name_cn") or data.get("cn_name")

    src = upsert_entity(
        db,
        entity_key,
        chunk.chunk_type or data.get("content_type", "unknown"),
        name_en=name_en,
        name_cn=name_cn,
        chunk_id=chunk.id,
        league=chunk.league,
        game_version=chunk.game_version,
    )
    extract_edges_from_text(db, src, search_text, chunk.id)
    return src


def expand_via_graph(
    db: Session,
    chunk_ids: list[int],
    *,
    max_hops: int = 1,
    max_results: int = 6,
) -> list[dict]:
    """Traverse kb_edges from seed chunks and return related knowledge chunk dicts."""
    if not chunk_ids:
        return []

    seed_entities = (
        db.query(KbEntity)
        .filter(KbEntity.chunk_id.in_(chunk_ids))
        .all()
    )
    if not seed_entities:
        return []

    seen_entity_ids = {e.id for e in seed_entities}
    seen_chunk_previews: set[str] = set()
    results: list[dict] = []

    frontier = list(seed_entities)
    for _hop in range(max_hops):
        if not frontier or len(results) >= max_results:
            break
        next_frontier: list[KbEntity] = []

        for src in frontier:
            edges = (
                db.query(KbEdge, KbEntity)
                .join(KbEntity, KbEdge.dst_entity_id == KbEntity.id)
                .filter(KbEdge.src_entity_id == src.id)
                .all()
            )
            edges.sort(key=lambda row: RELATION_PRIORITY.get(row[0].relation, 0), reverse=True)

            for edge, dst in edges[:8]:
                if dst.id in seen_entity_ids:
                    continue
                seen_entity_ids.add(dst.id)

                if not dst.chunk_id:
                    next_frontier.append(dst)
                    continue

                kc = db.query(KnowledgeChunk).filter(
                    KnowledgeChunk.id == dst.chunk_id,
                    KnowledgeChunk.stale == False,  # noqa: E712
                ).first()
                if not kc:
                    continue

                preview = (kc.content or "")[:100]
                if preview in seen_chunk_previews:
                    continue
                seen_chunk_previews.add(preview)

                results.append({
                    "id": kc.id,
                    "content": kc.content,
                    "chunk_type": kc.chunk_type,
                    "source": kc.source,
                    "links": kc.links,
                    "similarity": round(0.7 + edge.weight * 0.1, 3),
                    "via_graph": f"{edge.relation}:{dst.entity_key}",
                })
                if len(results) >= max_results:
                    return results

        frontier = next_frontier

    return results


def graph_available(db: Session) -> bool:
    """Check if kb_entities table exists (graceful degradation)."""
    try:
        db.query(KbEntity).limit(1).all()
        return True
    except Exception:
        return False
