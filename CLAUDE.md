# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**PoE2 智能工具站「流放漓」** — A Chinese-language intelligent tool site for Path of Exile 2 players. Backend uses "traditional code + background AI Agent" hybrid: code handles deterministic tasks (decoding, parsing, rate-limiting, caching), AI handles fuzzy tasks (understanding affixes, summarizing build logic, generating Chinese playbooks, Q&A).

**Primary spec**: `PoE2智能工具站-工程开发细节文档（2.0）.md` — the authoritative implementation spec. Read it before making any architectural decisions.

## Architecture

```
Frontend (Next.js + TypeScript + TailwindCSS)
    ↕ REST
API Gateway (FastAPI)
    ├── Business Services (Build, Chat, Trade)
    ├── AI Orchestrator (LangGraph or custom)
    ├── Trade Service (server-side Trade API proxy)
    └── Data Collectors
         ↕
Data Layer: PostgreSQL (+pgvector) + Redis + S3
         ↕  Celery async tasks
Background Agent Workers
    (PoB Parser, Homework Generator, Knowledge Ingester, etc.)
```

**Core design principle**: Anything code can do precisely, never hand to AI. AI only handles fuzzy/inferential tasks. All AI outputs must be structured data with schema validation + cross-checking + retry.

**Trade search**: 服务端直接调 PoE2 Trade API 获取搜索 ID，拼接 URL 返回前端。初期用户量可控，后期视情况迁移到浏览器插件。详见 [ADR-0002](docs/adr/0002-trade-search-architecture.md)。

## Tech Stack

- **Frontend**: Next.js (React) + TypeScript + TailwindCSS
- **Backend API**: Python FastAPI
- **Async Tasks**: Celery + Redis
- **Database**: PostgreSQL (JSONB for flexible build data) + pgvector extension
- **Cache**: Redis (official data cache + rate-limit token bucket + Celery broker)
- **Object Storage**: S3-compatible (MinIO / cloud OSS)
- **AI Models**: mimo-v2.5（LLM，默认）· DeepSeek V4 Flash（备用）· BGE-M3（Embedding，SiliconFlow）
- **Deployment**: Docker + docker-compose. Ops runbook: [docs/ops/deployment.md](docs/ops/deployment.md).

## P0 Core Loop (v1.0 — the only target for initial release)

```
User pastes PoB Code
  → Backend decodes (base64 + zlib → XML)
  → Parses into structured BuildData (items/talents/skills/stats)
  → AI Agent generates Chinese playbook (why this setup / core items / budget alternatives / talent highlights / strength review)
  → Store in DB + display on frontend
```

## PoB Code Decoding — Verified Facts

These are empirically validated (2026-06-05) — code MUST follow these:

1. **PoB Code starts with `eN`** (eNp, eNr, eJx all valid). Use `code[:2] == "eN"` for quick validation, not a stricter prefix.
2. **Standard PoB exports use zlib-wrapped format** — `zlib.decompress(raw)` succeeds directly. Raw deflate fallback (`-zlib.MAX_WBITS`) is for rare variants only.
3. **URL-safe base64 requires padding** — `code += "=" * (-len(code) % 4)` is mandatory, PoB share codes often lack trailing `=`.
4. **`xml.etree.ElementTree` is sufficient** — no need for lxml in MVP. Standard library can parse Build/Skills/Items/Tree nodes.
5. **Skill gems use `nameSpec` (human-readable) with `skillId` fallback** — parse as `nameSpec or skillId` or you'll miss entries.
6. **Item text is raw multi-line text** (first line: `Rarity: RARE/UNIQUE/MAGIC`) — affixes are unstructured; AI handles summarization, code only chunks.
7. **Multiple tree Specs per build** (leveling/endgame) — present ALL, not just the first.
8. **55KB XML encodes to ~16KB** — storage is not a concern.

## Database Schema (Key Tables)

- **`builds`**: Main table. `pob_code`, `build_data` (JSONB), `homework` (JSONB), `league`, `game_version`, `status` (pending/parsed/done/failed). All data MUST carry `league` + `game_version` — stale data from old seasons must not leak into AI retrieval.
- **`mod_translations`**: English→Chinese affix mapping. Lookup-first, AI-fallback with writeback (self-learning dictionary).
- **`knowledge_chunks`**: RAG vector store (pgvector). Filter by `league` + `game_version` on all queries.
- **`jobs`**: Async task tracking with retries.

## Compliance Rules (Non-negotiable)

**Tier A (NEVER violate)**:
- Never reverse-engineer game client resources
- Read `X-Rate-Limit-*` headers from every official API response; exponential backoff on 429
- All official API data goes through a centralized cache layer (Redis/PG) — no user request may directly hit official APIs
- OAuth applications must be written by a human (LLM-generated = instant rejection)

**Tier B (Grey area, early OK with isolation)**:
- poe.ninja scraping isolated in `collectors/grey/`, low-frequency, humanized UA, respect robots.txt
- Must have a one-click switch to compliant alternative sources
- pobb.in (AGPL-3.0) — reference its data structures only, never copy source into commercial service. Its public API `GET /:id/raw` is safe to call (API usage ≠ code license传染).

## Code vs AI Responsibility Split

| Task | Owner | Why |
|------|-------|-----|
| base64/zlib decode | Code | Deterministic |
| XML parsing | Code | Structured, precise |
| Official API + caching | Code | Rate-limit/compliance must be controlled |
| Affix translation | Code (lookup table) → AI fallback | Priority: table first |
| "What's the core idea of this build" | AI | Fuzzy reasoning |
| "Budget alternative suggestions" | AI | Requires experience + reasoning |
| Strength review | AI + code-provided DPS/EHP | AI interprets, code provides numbers |
| Player Q&A | AI (RAG) | Language understanding |

## AI Output Requirements

- All AI outputs use **fixed JSON schema** — no free-form text for programmatic consumption
- Inject full structured BuildData + relevant poe2db entries + version info into prompts
- Strong constraint: "only summarize given data, never fabricate items/stats"
- Post-output: schema validation → retry on failure → cross-check with source data → flag anomalies for human review
- Maintain versioned prompt templates, support A/B testing
- Tone: "matter-of-fact, clear and accurate" — no persona switching between newbie/veteran

## Milestones

| Phase | Goal | Status |
|-------|------|--------|
| M0 Tech PoC | PoB decoder works on real builds across major classes | ✅ |
| M1 Core Loop | PoB → async playbook generation → frontend display | ✅ |
| M2 Quality + Cold Start | Human review scores pass; operator imports N popular builds | ⚠️ CRUD exists, no import/score |
| M3 Info DB / Affixes | poe2db base integrated, affix Chinese coverage target met | ✅ v2 ingested (1249 chunks), v3 scraping |
| M4 Q&A RAG | Version-filtered RAG answers, hallucination rate controlled | ✅ POST /api/knowledge/ask, Redis cached |
| M5 Trade Search | Server-side Trade API: intent → stat ID → search URL | ✅ Agent + TradeConcept dict + multi-plan |
| M6 AI Chat Trade | AI-driven trade intent detection in chat | ✅ |
| M7 Pricing / OAuth | Official API integration, currency exchange | ❌ |
| M8 Browser Extension | Trade overlay, pobb.in import, hotkey launch | ❌ |

### M3 Details (Knowledge Base)
- **poe2db scraper**: v2 (index pages) complete, v3 (detail pages) running background
- **Data**: 1249 tri-language chunks (EN/CN/TW), 1238 with BGE-M3 embeddings
- **QA Endpoint**: `POST /api/knowledge/ask` — vector search + LLM RAG
- **Caching**: Redis cache for repeated questions (1h TTL)
- **Pre-filter**: Keyword classifier narrows search by content type

### M5 Details (Trade Search)
- **Agent**: `trade_agent.py` — parse_intent → resolve_concepts → build_plans → execute → inspect
- **Concepts**: 60 curated TradeConcept entries with CN aliases, item slot allowlists, known IDs
- **Plans**: Core/Full/Relaxed search tiers with AND+COUNT stat groups
- **Budget/Sort**: Supports price filter and pdps/edps sorting
- **Inspection**: Fetches actual items to verify mods match intent
- **Frontend**: `/trade` page shows best match + alternatives + explanation

### Ongoing Work
- **v3 Scraper**: ~978 detail pages being scraped (est. 4 hours), will add full skill/item descriptions
- **Multi-hop QA**: Not yet supported — v1 is single-hop encyclopedia lookup
- **M2 Content**: No build import system or pre-seeded popular builds

## Key Gotchas (from spec Appendix A)

1. Never re-calculate PoB's DPS/EHP — take pre-computed values from XML
2. PoB decompression must try zlib wrapper first, raw deflate as fallback
3. base64 is URL-safe variant: `-_` must be restored to `+/`
4. All data MUST carry version fields (league + game_version)
5. AI outputs MUST be schema-validated + cross-validated with source data
6. Official API always through cache layer — never user-request → official API
7. Read rate-limit response headers dynamically — never hardcode timing
8. Affix translation: table lookup first, AI only for unknowns, writeback to dictionary
9. PoE2 is rapidly iterating — parsers/KB must handle format changes with graceful degradation
10. Don't copy AGPL source (pobb.in) — reference data structures, rewrite in Python

## Deployment (概要)

**NAS 开发测试 → 大版本推腾讯云**。运维细节见 **[docs/ops/deployment.md](docs/ops/deployment.md)**。

| 环境 | 角色 | 访问 | 部署 |
|------|------|------|------|
| **NAS** | 开发 / 测试 / **知识库写入与爬虫** | `192.168.110.26:2212` | `python deploy_nas.py` |
| **腾讯云** | 公网生产（大版本 + KB 同步） | http://liufangli.xyz/chat | `python scripts/deploy_tencent.py` |

相关：[nas-deploy-guide.md](nas-deploy-guide.md) · [NAS-Docker-服务清单.md](docs/NAS-Docker-服务清单.md)

## Trade Search & AI Chat — Implementation Notes

- **Trade Search (M5)**: Fully implemented. See [docs/HANDOVER.md](docs/HANDOVER.md) for architecture.
- **AI Chat Trade (M6)**: AI now automatically detects trade/item search intent in build chat and provides search links.

**Critical PoE2 API differences from PoE1**:
- `weapon_filters` / `armour_filters` do NOT exist — use `equipment_filters` instead
- `ilvl` and `quality` belong in `type_filters` (not `misc_filters`)
- Level requirement `lvl` belongs in `req_filters`
- Trade API only accepts `explicit.*` stat IDs — vector search results must be normalized
- LLM may return `"stat_groups": null` — always use `parsed.get("key") or []` pattern
- Weighted sum type is `"weight2"` (not `"weighted_sum"`) and requires authentication

**Docker deployment caveat**: Only `/app/data` is volume-mounted. Code changes require `docker cp` into the running container or a full `docker compose up -d --build`.

## Knowledge Base (as of 2026-06-11)

**数据流**：爬虫/灌库/embedding **只在 NAS**；大版本用 `SYNC_NAS_DATA=1` 推到腾讯云。详见 [docs/ops/deployment.md](docs/ops/deployment.md)。

**21,977 chunks** across 5 sources:

| Source | Types | Count | CN? | Content |
|--------|-------|-------|-----|---------|
| **PoB** (jsDelivr CDN) | passive/item/mod/gem/asc_nodes | ~18K | N | 纯英文：天赋节点+物品+词缀+宝石+22升华 |
| **poe2db** (cloudscraper) | skill/item/mod/quest | ~3.4K | Y | 三语(EN/CN/TW)：技能+528暗金+273词缀+93任务 |
| **poe2wiki** (crawler) | wiki/item | 552 | N | 全站爬取：Delirium/Breach/Ritual/Omen/Spirit/Aura等 |
| **homework** (PoB解码) | BD攻略 | 72 | Y | AI生成中文BD分析 |
| **craftofexile** | mod aliases | 258 | Y | 词缀中英对照(回退层) |

### Alias Tables (entity_resolver)
| 数据源 | 条目 | 类型 |
|--------|------|------|
| caimogu_skills.json | 846 | 技能(国服译名) |
| game_aliases.json | 515 | 暗金/词缀(poe2db) |
| coe_cn_aliases.json | 258 | 词缀(craftofexile) |
| ASCENDANCY_CN_TO_EN | 22 | 升华 |
| CLASS_CN_TO_EN | 10 | 职业 |
| caimogu_items.json | 14 | 物品(几乎全挂) |
| **合计** | **~1,665** | |

### Key Data Files
- `backend/data/poe2db_chunks_v3.jsonl` — 890 skill detail pages (3-language)
- `backend/data/pob_data.jsonl` — 10253 PoB structured data chunks
- `backend/data/caimogu_skills.json` — 846 CN skill names (Tencent-aligned)
- `backend/data/coe_cn_aliases.json` — 258 CN mod translations (craftofexile)
- NAS: `/volume1/docker/PoE2LI/data/` — volume-mounted into container `/app/data/`

### CN Coverage Reality
- PoB 18K chunks are pure English — **BGE-M3 cross-lingual matching handles this** (tested: "火焰伤害"→"Fire Damage" sim=0.64)
- CN data exists for: poe2db items/skills (CN), homework (CN), asc_nodes (CN injected)
- Missing: special base types (Delirium Twisted Amulet etc.), user slang→official name mappings

### Ingestion Gotchas
- **Asc_nodes embedding**: MUST be short or similarity diluted. CN prefix injected: "灵魂行者 (Spirit Walker)"
- **Cross-lingual**: always include original CN query + LLM EN keywords
- **Encoding**: SSH garbles CJK display but DB storage is UTF-8. Scripts using `chr()` for CJK are fragile
- **FK constraints**: `kb_entities` references `knowledge_chunks` via FK — can't delete chunks without deleting entities first
- **docker cp**: Copying files to `/app/scripts/` often fails silently (use `docker compose build --no-cache` instead)

## Chat System

### Skill-based Architecture
```
User query → Skill Router (router.py)
  ├── TradeSearchSkill  [tools: trade_api, entity_resolve]
  ├── BuildDesignSkill  [tools: rag_search, entity_resolve, structured_lookup]
  ├── RecommendSkill    [tools: rag_search, entity_resolve]
  └── EncyclopediaSkill [tools: rag_search, entity_resolve]
```
Each Skill has its own `system_prompt()`, `keywords[]`, and `tools[]`. New skills added by creating a module in `backend/app/skills/` and registering in `router.py`.

### Retrieval Pipeline
- **Unified**: `retrieval_pipeline.py` (595 lines) consolidates vector search, intent routing, entity resolution, concept expansion
- **Structured Lookup**: resolved entities (ascendancy/item/skill) trigger direct DB fetch BEFORE vector search
- **Concept Expansion**: reads chunk `links` field, does secondary vector searches (max 4 chunks, 3 links)
- **Knowledge Graph**: `kb_entities` + `kb_edges` tables (3,395 entities, 15,401 edges) for multi-hop traversal

### Entity Resolution
- `entity_resolver.py`: 3-tier — exact substring → CJK bigram fuzzy → keyword correction
- CJK bigram: "扭曲项链" shares "扭曲" with "扭曲苍穹" → matches
- Fuzzy keyword correction: fixes LLM misspellings ("Moriigan"→"Morrigan")

### Endpoints
- `POST /api/chat` — SSE streaming, multi-turn, DeepSeek thinking mode
- `POST /api/knowledge/ask` — single-turn RAG QA (Redis cached, 1h TTL)
- `POST /api/knowledge/recommend` — multi-hop item comparison

### Flow
1. Skill Router dispatches → Entity resolution + alias injection
2. LLM generates search keywords → fuzzy-corrected against known entities
3. Vector search + structured lookup → concept expansion via links/knowledge graph
4. LLM streams reasoning + answer in markdown format

### Frontend Pages
- `/` — PoB decoder (paste code → stats + homework + link to /chat)
- `/trade` — natural language trade search (Agent + multi-plan)
- `/chat` — Taste-skill redesigned: zinc palette, amber accent, markdown rendering, collapsible thinking

## Trade Search

### Key Files
- `backend/app/services/trade_agent.py` — main pipeline
- `backend/app/services/trade_concepts.py` — 60 curated CN→stat_id mappings with item_slot allowlists
- `backend/app/services/trade_stat_service.py` — vector search for stat IDs (pgvector)
- `backend/app/services/trade_service.py` — Trade API query builder + rate-limited HTTP client

### COUNT Group Semantics
- AND: all stats must match (core requirement)
- COUNT(min=N): at least N of the listed stats must match (flexible pool)
- AND + COUNT combined: core stat required, broad stats flexible

## Concept Links System

`concept_links.py`: 3-tier link computation at chunk ingest time:
1. **Entity names**: scan text with entity_resolver → `entity:灵魂行者:ascendancy:Spirit Walker`
2. **Concept hooks** (~60 keywords): "涂油"→wiki, "词缀"→mod, "delirium"→wiki, "minion"→minion
3. **Chunk_type self-link**: `type:item`

Links stored in `knowledge_chunks.links` (JSON array), computed by `backfill_links.py`.
Concept expansion during retrieval: reads links → secondary vector search → merges results.

## Known Issues & Gotchas

1. **Encoding**: Chinese text in container scripts must be proper UTF-8. Using `chr()` escapes works but is fragile
2. **Inline Python via SSH**: Multi-layer quoting (Python→bash→Python) breaks on `"` and `'` and `{}`. Always write scripts to files and deploy
3. **Twisted Amulet (id=24446)**: manually injected chunk. Had encoding issues with merged Instilled Notables text
4. **docker exec -d**: background processes die when SSH disconnects. Use synchronous `docker exec` with long timeout
5. **Docker cache**: `docker compose up -d --build` may use cached layers. Use `--no-cache` or `docker cp` for single-file changes
6. **Concept expansion noise**: when links are irrelevant (random items matching same concept), expansion adds noise not signal
7. **Frontend Next.js**: Turbopack version has breaking changes (see `frontend/AGENTS.md`). Use `docker compose build --no-cache frontend` for reliable rebuilds

## Key Files Reference

| File | Purpose |
|------|---------|
| `backend/app/api/knowledge.py` | Chat endpoint, streaming, skill dispatch |
| `backend/app/services/retrieval_pipeline.py` | Unified retrieval: vector search + intent + entity + expand |
| `backend/app/services/entity_resolver.py` | CN→EN entity resolution with bigram fuzzy match |
| `backend/app/services/concept_links.py` | Concept hooks + link computation |
| `backend/app/services/knowledge_graph_service.py` | KG edge creation and traversal |
| `backend/app/models/knowledge_graph.py` | KbEntity + KbEdge DB models |
| `backend/app/skills/router.py` | Skill dispatch by keyword matching |
| `backend/app/skills/encyclopedia.py` | Encyclopedia Q&A skill |
| `backend/app/skills/build_design.py` | BD design skill |
| `backend/app/skills/trade_search.py` | Trade search skill |
| `backend/app/skills/recommend.py` | Item recommend skill |
| `backend/scripts/backfill_links.py` | Compute links for existing chunks |
| `backend/scripts/backfill_knowledge_graph.py` | Populate KG entities/edges |
| `backend/scripts/crawl_poe2wiki.py` | Full wiki crawler (resumable, 1s/page) |
| `backend/scripts/scrape_caimogu_aliases.py` | Caimogu skill CN name scraper |
| `frontend/src/app/chat/page.tsx` | Chat UI (taste-skill redesign, markdown renderer) |
| `deploy_nas.py` | NAS deployment via paramiko SSH |
| `scripts/deploy_tencent.py` | Tencent Cloud VPS deployment via paramiko SSH |
| `docker-compose.tencent.yml` | Cloud compose override (no proxy, no public DB ports, celery profile) |
