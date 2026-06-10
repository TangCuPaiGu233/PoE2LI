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
- **AI Models**: DeepSeek V4 Flash or mimo-v2.5 (cost-first, performance sufficient)
- **Deployment**: Docker + docker-compose (initial) → K8s (scale). See [nas-deploy-guide.md](nas-deploy-guide.md) for NAS deployment instructions.

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

## NAS Connection & Deployment

Detailed instructions: [nas-deploy-guide.md](nas-deploy-guide.md)

| Target | Detail |
|------|------|
| **SSH** | `ssh -p 2212 skc@192.168.110.26` |
| **Path** | `/volume1/docker/PoE2LI` |
| **Sync** | `git fetch origin && git reset --hard origin/main` |

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

## Knowledge Base (as of 2026-06-10)

**21,010 chunks, 82MB** across 4 sources:

| Source | Types | Count | Content |
|--------|-------|-------|---------|
| **PoB** (jsDelivr CDN) | passive/item/mod/gem/asc_nodes | ~18K | 4912天赋节点+3588物品+1828词缀+1260宝石+22升华详情 |
| **poe2db** (cloudscraper) | skill/item/mod/quest | 2,733 | 技能详情+528传奇完整词缀+273词缀+93任务（三语EN/CN/TW） |
| **poe2wiki** (cloudscraper) | wiki | 183 | 机制百科：Aura/Buff/Herald/Huntress等29关键页+53通用页 |
| **homework** (PoB解码) | BD攻略 | 72 | 从用户PoB code解码生成的AI分析文本 |

### Key Data Files
- `backend/data/trade_stats_condensed.json` — 7816 PoE2 trade stat IDs (live API dump)
- `backend/app/services/poe2db_uniques.json` — 446传奇完整数据
- `backend/app/services/poe2db_ascendancies.json` — 82升华职业
- `backend/data/poe2db_chunks_v3.jsonl` — 978 skill detail pages (CDN scrape)
- `backend/data/pob_data.jsonl` — 10253 PoB structured data chunks

### Ingestion Gotchas
- **Ascendancy nodes**: embedding text MUST be short (`"Spirit Walker ascendancy: Node1, Node2..."`) — long search_text (3000 chars) dilutes similarity
- **Context truncation**: asc_nodes type gets 3000 chars, others 800 (was 600 — cut 18-node lists to 3, causing hallucination)
- **Cross-lingual retrieval**: always include user's original Chinese query alongside LLM's English keywords
- **Dedup**: use exact chunk_id match via `league` field, NOT `content.like('%id%')` (matches "tree_4"→"tree_40")

## Chat System

### Endpoints
- `POST /api/chat` — SSE streaming, multi-turn, DeepSeek thinking mode
- `POST /api/knowledge/ask` — single-turn RAG QA (Redis cached, 1h TTL)
- `POST /api/knowledge/recommend` — multi-hop item comparison (auto-routes to RAG for encyclopedia)

### Flow
1. LLM thinks → outputs search keywords (non-stream, fast)
2. Code retrieves from all 4 sources using user's Chinese + LLM's English keywords
3. LLM thinks about results → streams reasoning (🧠) + answer

### Intent Routing (`_classify_intent`)
- `build_design`: "BD/构建/配装/开荒/天赋怎么点" → multi-source + structured BD output
- `recommend`: "推荐/哪个好/对比" → item comparison
- `encyclopedia`: default → all-source RAG

### Frontend Pages
- `/` — PoB decoder (paste code → stats + homework + link to /chat)
- `/trade` — natural language trade search (Agent + multi-plan)
- `/chat` — multi-turn AI chat with thinking display (collapsible 🧠 思考过程)

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

## Agent skills

### Issue tracker
Issues live in this repo's GitHub Issues. See `docs/agents/issue-tracker.md`.

### Triage labels
Default vocabulary — all five canonical labels used verbatim. See `docs/agents/triage-labels.md`.

### Domain docs
Single-context — `CONTEXT.md` + `docs/adr/` at repo root. See `docs/agents/domain.md`.
