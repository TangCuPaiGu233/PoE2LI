# ADR-0003: Entity Catalog for Chip UI

## Status

Accepted (2026-06-13)

## Context

Chat entity chips need **icon + Chinese tooltip** for skills, uniques, and ascendancies. The initial implementation split this across:

- `entity_resolver` — CN→EN alias lookup
- `entity_icon_service` — wiki index → disk probe → poe2db fetch → Redis (runtime chain)
- `entity_tooltip` — KB chunk ILIKE + scoring (runtime, per request)
- `retrieval_pipeline.structured_entity_lookup` — duplicate chunk selection for RAG vs UI

Each new data source (wiki scrape, poe2db v3, PoB, caimogu) required another fallback branch. Fixes were reactive: one entity name at a time.

## Decision

Introduce an **Entity Catalog** — a materialized JSON file (`data/entity_catalog.json`) built offline, consumed at runtime with O(1) alias lookup.

### Architecture

```
Alias tables (caimogu, game_aliases, …)
        ↓
build_entity_catalog.py  ←── KB chunks + wiki icons + poe2db paths
        ↓
entity_catalog.json  (canonical EntityProfile per entity_key)
        ↓
entity_catalog_service.py  (runtime: resolve name → profile)
        ↓
/api/entities/tooltip | /icon-image
        ↓
PoeEntityChip (frontend)
```

### EntityProfile schema

One record per `(type, name_en)`:

| Field | Purpose |
|-------|---------|
| `entity_key` | `skill:Fireball` — stable ID |
| `name_en`, `name_cn`, `aliases` | All lookup keys |
| `description_cn`, `description_en` | Pre-extracted at build time |
| `icon_local`, `icon_url` | Pre-resolved icon paths |
| `poe2db_url`, `rarity`, `kb_chunk_id` | Metadata |

### Build vs runtime

| Phase | Responsibility |
|-------|----------------|
| **Build** (`build_entity_catalog.py`) | Merge aliases + best KB chunk + icon resolution. Run after KB ingest or wiki scrape. |
| **Runtime** (`entity_catalog_service`) | Load JSON once; resolve alias → profile. No DB query on hot path. |
| **Fallback** | If catalog miss or stale, legacy `entity_tooltip` / `entity_icon_service` paths remain. |

### Shared extraction

`entity_profile.py` holds chunk parsing and description extraction used **only by the builder** (and legacy fallback). Scoring rules live in one place instead of duplicated in tooltip + retrieval.

## Consequences

**Positive**

- Chip UI reads one file; predictable latency
- New data sources update the builder, not three services
- Alias coverage is explicit in catalog stats (`/api/entities/catalog-status`)
- Rebuild is idempotent and diffable

**Negative**

- Catalog must be rebuilt when KB/icons/aliases change (add to deploy pipeline)
- Disk size ~1–2 MB for ~1500 entities (acceptable on NAS volume)

## Rebuild triggers

Run on NAS after:

```bash
docker exec poe2li-backend python /app/scripts/build_entity_catalog.py --data-dir /app/data
```

Trigger when: poe2db ingest, wiki icon scrape, alias JSON updates, or league rollover.
