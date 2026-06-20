# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**PoE2 智能工具站「流放漓」** — A Chinese-language intelligent tool site for Path of Exile 2 players. The backend is built on a **three-layer Agent architecture**: a main Agent (ReAct or LLM Planner) routes user intent, dispatches to sub-Agents (encyclopedia, trade_search, build_design, etc.), which in turn call deterministic tools (Trade API, pgvector, PoB decode, entity lookup). AI handles routing, understanding, and synthesis; tools handle precise execution.

**Primary spec**: `PoE2智能工具站-工程开发细节文档（2.0）.md` — authoritative for product scope. **Domain glossary**: `CONTEXT.md`. **Architecture decisions**: `docs/adr/`.

**Core design principle**: AI Agents handle routing, intent understanding, and result synthesis — they decide what to do. Tools (code) handle precise execution — they do it correctly. Don't push deterministic work into the Agent's reasoning; keep it in the tool layer. All AI outputs for programmatic use must be schema-validated + cross-checked + retried.

## System Architecture

```
Frontend (Next.js + TypeScript + TailwindCSS)
    ↕ REST / SSE
API Gateway (FastAPI)
    ├── Builds API        — PoB decode, homework, CRUD
    ├── Chat API          — POST /api/chat (SSE, multi-turn)
    ├── Trade API         — server-side Trade API proxy
    ├── Filter API        — loot filter generation, base scanning, download
    ├── Knowledge API     — /api/knowledge/ask, /recommend
    ├── Entities API      — mentions, tooltip, icon-image
    └── Admin / collectors
         ↕
Data Layer: PostgreSQL (+pgvector) + Redis + S3-compatible storage
         ↕  Celery (async homework, ingest jobs)
Background Workers — PoB parser, homework generator, KB ingesters, scrapers
```

**Trade search**: Server calls PoE2 Trade API → search ID → URL to frontend. See [ADR-0002](docs/adr/0002-trade-search-architecture.md).

**KB data flow**: Scrapers + ingest + embedding run **on NAS only**; Tencent Cloud is read-only consumer. See [docs/ops/deployment.md](docs/ops/deployment.md).

## Agent & Chat Orchestration

Chat is the most complex subsystem. There are **two runtimes** (env `CHAT_RUNTIME`, default `legacy`):

| Runtime | Entry | When to use |
|---------|-------|-------------|
| **`legacy`** (default) | `chat_agent.stream_chat_agent` | Production default — single ReAct loop; LLM chooses tools turn-by-turn |
| **`orchestrator`** | `chat_orchestrator.stream_chat_orchestrator` | Parallel sub-agents + synthesis LLM; set `CHAT_RUNTIME=orchestrator` |

Both share the same **tool executors** in `chat_tools.py` — no duplicate business logic.

### End-to-end flow (`POST /api/chat`)

```
messages[]  →  chat_orchestrator.stream_chat()     # runtime switch
                    │
    ┌───────────────┴────────────────┐
    │ CHAT_RUNTIME=legacy            │ CHAT_RUNTIME=orchestrator
    ▼                                ▼
stream_chat_agent()              stream_chat_orchestrator()
ReAct loop (≤8 rounds)           plan → parallel dispatch → synthesize
    │                                │
    └──────── chat_tools.execute_tool ┘
                    │
         entity_resolve / rag_search / trade_search /
         decode_pob / recommend / resolve_trade_stat /
         search_game
                    │
         retrieval_pipeline, trade_agent, pob_service, …
```

**Design intent (2026-06)**:
- **Fuzzy routing → AI** (planner or ReAct agent reads full conversation).
- **Deterministic execution → code** (tools, Trade API filters, PoB decode, entity tables).
- **No per-entity routing patches** in application code — official names from Trade API index.

### Legacy runtime — ReAct agent

| File | Role |
|------|------|
| `backend/app/services/chat_agent.py` | System prompt (`AGENT_SYSTEM` rules 0–36), ReAct loop, streaming |
| `backend/app/services/chat_tools.py` | Tool definitions + `execute_tool()` + `detect_input_signals()` |
| `backend/app/orchestrator/session_context.py` | `build_session_context()` — prior turns, trade anchors, PoB detection |

The agent calls OpenAI-compatible tools (`entity_resolve`, `rag_search`, `trade_search`, `decode_pob`, `recommend`, `resolve_trade_stat`, `search_game`). Rules in `AGENT_SYSTEM` cover multi-turn price follow-ups, 百科 vs 市集, 扭曲项链/畸变项链 disambiguation, WeGame panels, etc.

`detect_input_signals()` injects **hints** (not hard routes), e.g. `bare_item_name:use_rag`, `trade_base_type:扭曲项链=Distorted Amulet`.

### Orchestrator runtime — plan → parallel → synthesize

| File | Role |
|------|------|
| `backend/app/services/chat_orchestrator.py` | SSE events, synthesis prompt, `stream_chat()` entry |
| `backend/app/orchestrator/llm_planner.py` | LLM reads conversation → JSON `{tasks: [{agent, query, …}]}` |
| `backend/app/orchestrator/planner.py` | Thin wrapper → `llm_plan_dispatch(messages)` |
| `backend/app/orchestrator/session_context.py` | `SessionContext` — anchors, `effective_user_msg()`, `trade_search_query()` |
| `backend/app/orchestrator/dispatcher.py` | `dispatch_parallel()` — semaphore + per-task timeout |
| `backend/app/orchestrator/runners.py` | Maps each `TaskSpec` → `execute_tool()` |
| `backend/app/orchestrator/schemas.py` | `TaskSpec`, `SkillAgentResult`, `DispatchPlan` |

**Sub-agents** (parallel, stateless — each gets `effective_user_msg` in payload):

| Agent | Tool(s) | Purpose |
|-------|---------|---------|
| `decode_pob` | `decode_pob` | PoB code / pobb.in / poe.ninja / WeGame link |
| `trade_search` | `trade_search` | Market search + listing inspection |
| `encyclopedia` | `rag_search` | Mechanics, skills, items, mods |
| `build_design` | `rag_search` | BD / 配装 / 如何搭配 |
| `recommend` | `recommend` | Explicit multi-item comparison only |

**Deterministic merge**: If `session_context` detects PoB input, `decode_pob` task is **always** injected even if LLM planner omits it (`_merge_pob_task`).

**Synthesis**: Second LLM pass combines `SkillAgentResult.to_synthesis_block()` outputs; skill-specific system prompts from `backend/app/skills/*.py` via `get_skill()`.

**SSE event types**: `thinking`, `reasoning`, `answer`, `trade_result`, `recommend_result`, `sources`, `sub_agent_done`, `follow_ups`, `done`.

### Skills module (prompt templates, not primary router)

`backend/app/skills/` — `TradeSearchSkill`, `EncyclopediaSkill`, `BuildDesignSkill`, `RecommendSkill`.

- **Not** the main `/api/chat` dispatcher anymore (no keyword `route()` in chat path).
- Used by orchestrator **synthesis** for per-agent system prompt fragments.
- `POST /api/knowledge/ask` uses retrieval pipeline directly (not skill router).

### Shared tool layer (`chat_tools.py`)

| Tool | Owner logic |
|------|-------------|
| `entity_resolve` | `entity_resolver.py` |
| `rag_search` | `retrieval_pipeline.py` — vector + structured lookup + concept expansion |
| `trade_search` | `trade_agent.py` — intent → stat IDs → multi-plan → inspect |
| `decode_pob` | `pob_service.py` + WeGame/ninja fetchers |
| `recommend` | multi-hop item comparison |
| `resolve_trade_stat` | `trade_stat_service.py` — vector match stat IDs |
| `search_game` | `game_graph_service.py` — GGPK knowledge graph BFS search |

Env knobs: `CHAT_TRADE_SEARCH_MAX` (default 8), `ORCHESTRATOR_MAX_PARALLEL` (default 12).

### Retrieval pipeline (RAG)

`retrieval_pipeline.py` — unified path for chat tools and `/api/knowledge/ask`:

1. Entity resolution + alias keyword injection
2. Structured entity lookup (ascendancy/item/skill) **before** vector search
3. pgvector search (BGE-M3, filter `league` + `game_version`)
4. Concept expansion via `knowledge_chunks.links` (max 4 chunks)
5. Knowledge graph (`kb_entities` + `kb_edges`) for multi-hop

### Entity resolution & official CN names

**Single source of truth for item base CN↔EN**: `backend/data/trade_items_en_cn.json` (~2876 entries), loaded in `entity_resolver._load_aliases()` at confidence 99, source `trade_api`.

`entity_dict.ITEM_CN_ALIASES` — **colloquial only** (e.g. `沉默之雷`→Mjölner, `扭曲护身符`→Twisted Amulet). Do **not** add official base names one-by-one; refresh Trade index via `scripts/fetch_trade_items_bilingual.py`.

**Critical国服译名** (Trade API):
- **扭曲项链** = `Distorted Amulet` (normal amulet affix pool)
- **畸变项链** = `Twisted Amulet` (Delirium / Instilled anointing base)
- Community slang `扭曲护身符` → Twisted Amulet (colloquial alias)

`trade_items_index.match_base_type_in_text()` — longest-match base detection for Trade `type` filter.

### Entity chips (chat UI)

Backend: `entity_tooltip.find_mentions()` → `POST /api/entities/mentions`.

Frontend: `ChatMarkdown.tsx` inserts `⟦poe:label|en|type⟧` markers → `PoeEntityChip.tsx`.

Rules (2026-06): skip metadata lines (`英文名：`, `基底类型：`), skip `NAME（alias）` disambiguation spans, cap 2 chips per label, CJK embedding allowed, trade bases show **基底** not 暗金 in tooltip.

## Tech Stack

- **Frontend**: Next.js (React) + TypeScript + TailwindCSS
- **Backend API**: Python FastAPI
- **Async Tasks**: Celery + Redis
- **Database**: PostgreSQL (JSONB) + pgvector
- **Cache**: Redis (API cache, rate-limit, Celery broker)
- **Object Storage**: S3-compatible (MinIO / cloud OSS)
- **AI**: mimo-v2.5 (LLM default) · DeepSeek V4 Flash (fallback) · BGE-M3 embeddings (SiliconFlow)
- **Deployment**: Docker Compose — [docs/ops/deployment.md](docs/ops/deployment.md)

## P0 Core Loop

```
User pastes PoB Code
  → decode (base64 + zlib → XML)
  → parse → BuildData JSON
  → AI generates Chinese homework (playbook)
  → store in DB + display
```

## PoB Code Decoding — Verified Facts

Empirically validated (2026-06-05):

1. PoB code starts with `eN` (`eNp`, `eNr`, `eJx` valid). Quick check: `code[:2] == "eN"`.
2. Standard exports: `zlib.decompress(raw)` first; raw deflate (`-zlib.MAX_WBITS`) fallback only.
3. URL-safe base64 needs padding: `code += "=" * (-len(code) % 4)`.
4. `xml.etree.ElementTree` is sufficient for MVP.
5. Gems: `nameSpec or skillId`.
6. Item text is raw multi-line; affixes unstructured — AI summarizes.
7. Multiple tree Specs per build — present all.
8. ~55KB XML → ~16KB encoded — storage not a concern.

## Database Schema (Key Tables)

- **`builds`**: `pob_code`, `build_data` (JSONB), `homework` (JSONB), `league`, `game_version`, `status`
- **`mod_translations`**: EN→CN affix lookup-first, AI fallback + writeback
- **`knowledge_chunks`**: RAG vectors; always filter `league` + `game_version`
- **`kb_entities` / `kb_edges`**: Knowledge graph
- **`game_data`**: Raw GGPK game data, 24 tables × 3 languages (EN/TC/SC), 242K+ rows
- **`base_price_snapshots`**: White base Trade API scan results (857 bases per batch, `scan_batch`, `cheapest_price_chaos`, `median_price_chaos`, `is_high_value`)
- **`item_price_snapshots`**: Multi-category price scan results (currency, uniques, gems, etc.)
- **`jobs`**: Async task tracking

## Compliance (Non-negotiable)

**Tier A**: No client reverse-engineering · Read `X-Rate-Limit-*` on every official API response · All official API via centralized cache — no user-request → live API · OAuth apps human-written only.

**Tier B**: poe.ninja in `collectors/grey/` · pobb.in AGPL — reference data structures only, never copy source.

## Agent vs Tool Responsibility

The system has three layers, each with a distinct role:

| Layer | Runs on | Responsibility |
|-------|---------|----------------|
| **Main Agent** | AI (LLM Planner / ReAct) | Understand user intent, decide which sub-agents to dispatch, synthesize results |
| **Sub-Agent** | AI (per-domain prompt) | Execute domain reasoning with tool results, produce structured answer blocks |
| **Tool** | Code | Deterministic execution — Trade API queries, pgvector search, PoB decode, entity lookup, stat ID resolution |

### Per-task ownership

| Task | Owner |
|------|-------|
| Chat routing (which sub-agent to call) | Main Agent (AI) |
| Build reasoning, playbooks, Q&A language | Sub-Agent (AI) |
| Affix translation | Table lookup → AI fallback |
| base64/zlib/XML parse, Trade API, caching, entity tables | Tool (Code) |
| Tool execution, stat ID resolve, PoB decode | Tool (Code) |

## Milestones

| Phase | Goal | Status |
|-------|------|--------|
| M0 PoB decoder | Real builds across classes | ✅ |
| M1 Core loop | PoB → homework → frontend | ✅ |
| M2 Quality + cold start | Review scores, popular build import | ⚠️ CRUD only |
| M3 Knowledge base | poe2db + PoB + wiki ingested | ✅ ~22K chunks |
| M4 RAG Q&A | Version-filtered answers | ✅ |
| M5 Trade search | Intent → stat ID → URL | ✅ |
| M6 Chat + trade | Trade intent in chat | ✅ |
| M7 Pricing / OAuth | Official pricing API | ❌ |
| M8 Browser extension | Trade overlay | ❌ |

**Chat architecture evolution**: Keyword skill router → **ReAct agent (default)** + optional **orchestrator** parallel mode. Do not reintroduce keyword-only routing for `/api/chat`.

## Deployment (概要)

| 环境 | 角色 | 访问 |
|------|------|------|
| **NAS** | 开发/测试/KB写入 | `ssh -p 2212 skc@192.168.110.26` · `python deploy_nas.py` |
| **腾讯云** | 公网生产 | `TENCENT_BRANCH=main python scripts/deploy_tencent.py` |

**Docker caveat**: Only `/app/data` volume-mounted. Code changes need `docker compose build` or `docker cp` / `scripts/nas/hotfix_*.py`.

**腾讯云注意**: backend `mem_limit: 1228m`（GameGraph 加载 566MB poe2_data 需 ~1.1GB，768m 会 OOM）。poe2_data 不在 git 里，须从 NAS 手动传（tar → SFTP → 解压到 `/opt/PoE2LI/data/poe2_data/`）。trade 数据 JSON 也须手动同步。

Chat test URLs: NAS `http://192.168.110.26:3000/chat` · Filter `http://192.168.110.26:3000/filter` · API `http://192.168.110.26:8000/health`.

## Knowledge Base (2026-06)

**~23K chunks** across PoB (~18K EN), poe2db (~3.4K tri-lang), poe2wiki, homework, craftofexile aliases.

**Entity catalog**: `backend/data/entity_catalog.json` (~1.4K entities) — O(1) chip icon + tooltip when present.

**Alias layers**:

| Source | Count | Use |
|--------|-------|-----|
| `trade_items_en_cn.json` | ~2876 | Official item CN↔EN (confidence 99) |
| `caimogu_skills.json` | 846 | CN skill names |
| `game_aliases.json` | 515 | Uniques/mods from poe2db |
| `coe_cn_aliases.json` | 258 | Mod CN fallback |
| `entity_dict` colloquial | few | Slang not in Trade API |

NAS data path: `/volume1/docker/PoE2LI/data/` → container `/app/data/`.

## GGPK Game Data Pipeline (2026-06)

Raw game data extracted from PoE2 Content.ggpk (international client) and CN WeGame client. Provides 242K+ structured records across 24 core game tables, with 549K+ resolved relationship edges forming a traversable knowledge graph.

### Pipeline overview

```
Content.ggpk (international)  ──→  en/ + tc/ JSON     ─┐
CN WeGame Bundles2             ──→  sc/ JSON            ├─→ import_game_data.py ──→ PostgreSQL game_data
                                                         │
                                        resolve_relations.py ──→ game_relations.json (212K edges)
                                                         │
                                              game_graph.py ──→ BFS traversal query
```

### Step 1: Export from GGPK (re-run when game updates)

```bash
# EN + TC from international client (requires PoE2 installed)
cd backend/scripts/ggpk
python export_en_tc.py --ggpk "C:\...\Content.ggpk" --output ../../data/poe2_data

# SC from CN WeGame client (requires CN client installed)
python extract_sc.py --bundles "D:\WeGameApps\...\Bundles2" --output ../../data/poe2_data
```

**Data source structure inside GGPK**:
- `data/balance/*.datc64` — English base data
- `data/balance/traditional chinese/*.datc64` — TC override (only tables with translated text)
- `data/balance/french/`, `german/`, etc. — other languages (excluded)
- CN WeGame client root bundles = Simplified Chinese (no language subdirectories)

**Technical details**: PyPoE loads `_.index.bin` → walks BundleRecords/FileRecords/DirectoryRecords → extracts `.datc64` blobs → parses via `DatFile(name, specification=spec).read(BytesIO(data), x64=True)` → serializes to JSON.

### Step 2: Import to PostgreSQL

```bash
# Inside Docker container (NAS):
python scripts/import_game_data.py --data-dir /app/data/poe2_data --game-version 0.2.0

# Dry run first:
python scripts/import_game_data.py --data-dir /app/data/poe2_data --dry-run
```

Merges EN/TC/SC by `row_key` (Id field), upserts into `game_data` table. Each row stores `name_en`, `name_tc`, `name_sc` + full JSON `data` column with `{"en":{...}, "tc":{...}, "sc":{...}}`.

**24 tables**: ActiveSkills, SkillGems, GemTags, ActiveSkillType, GrantedEffects, GrantedEffectsPerLevel, BaseItemTypes, ItemClasses, Tags, Mods, PassiveSkills, Ascendancy, AlternatePassiveSkills, AlternatePassiveAdditions, Stats, MonsterVarieties, MonsterResistances, MonsterArmours, ItemExperiencePerLevel, CharacterStartStates, WorldAreas, MapPins, Words, QuestFlags.

### Step 3: Resolve FK relationships (requires PyPoE locally)

```bash
# Extract FK definitions from PyPoE spec, resolve row indices to row_keys
python scripts/resolve_relations.py --data-dir backend/data/poe2_data/en --output backend/data/poe2_data/game_relations.json

# Supplement string-based FK references
python scripts/resolve_string_fks.py
```

Produces `game_relations.json` (~88 MB): 93 FK field definitions across 19 tables, 549K+ resolved edges. Each edge: `{src_table, src_key, dst_table, dst_key, relation}`.

**Key relationship hubs**: Stats (38K incoming edges — most referenced table), Tags (80K), GrantedEffects (50K), ActiveSkillType (12K).

### Step 4: Graph traversal query

```bash
# CLI query (local or inside container)
python scripts/query_graph.py "ground_slam" --table ActiveSkills --hops 2
python scripts/query_graph.py "Strength1" --table Mods --hops 1 --json
python scripts/query_graph.py "Blacksmith" --search   # search only, no expansion
```

**Python API** (for LLM Agent integration):
```python
from scripts.game_graph import GameGraph
g = GameGraph("data/poe2_data/game_relations.json", "data/poe2_data")
results = g.find_entity("ground_slam", table_filter="ActiveSkills")
tree = g.expand("ActiveSkills", "ground_slam", max_hops=2, max_nodes=200)
g.print_tree(tree)
```

BFS expansion from `ground_slam` (1 hop): 6 skill type tags (Attack, Area, Melee, Slam, Totemable, AttackInPlace) + 3 input stats + 3 output stats + 3 reverse references. 2 hops → 739 connected nodes.

### game_data database schema

```sql
game_data(
  id          SERIAL PRIMARY KEY,
  table_name  VARCHAR(64) NOT NULL,    -- e.g. "ActiveSkills", "Mods"
  row_key     TEXT NOT NULL,           -- Id field value (TEXT for long Mod IDs)
  name_en     TEXT,                    -- English display name
  name_tc     TEXT,                    -- Traditional Chinese name
  name_sc     TEXT,                    -- Simplified Chinese name
  data        JSON NOT NULL,           -- {"en":{full_row}, "tc":{...}, "sc":{...}}
  source      VARCHAR(16) DEFAULT 'ggpk',
  game_version VARCHAR(32),
  created_at  TIMESTAMP,
  UNIQUE(table_name, row_key)
)
```

Indexes: `ix_game_data_table_name` on `table_name`, `ix_game_data_table_key` unique on `(table_name, row_key)`.

### When to re-run the pipeline

1. **Game version update**: Re-export EN+TC+SC → re-import → re-resolve relations
2. **New table needed**: Add table name to `ALL_TABLES` in export scripts + `TABLE_CONFIG` in import script
3. **FK resolution update**: PyPoE spec must match the game version being exported

## Trade Search

Pipeline: `trade_agent.py` — `parse_intent` → `resolve_concepts` → `build_plans` → execute → inspect.

**PoE2 API differences from PoE1**:
- Use `equipment_filters` (no `weapon_filters`/`armour_filters`)
- `ilvl`, `quality` in `type_filters`; `lvl` in `req_filters`
- Trade API accepts `explicit.*` stat IDs only
- `parsed.get("stat_groups") or []` — LLM may return `null`
- Weighted sum type is `"weight2"` (auth required)

`trade_concepts.py` — curated CN→stat_id mappings. `trade_items_index` — base `type` filter from CN name in query.

## Loot Filter (AI 智能筛选器)

Admin-triggered pipeline that generates a PoE2 `.filter` file combining Trade API base prices, poe.ninja live currency data, and the asmco template.

### Data flow

```
Admin triggers scan (POST /api/filter/scan)
  → base_scanner.scan_all_bases() — 857 white bases via Trade API
  → base_price_snapshots table (latest batch)

Admin triggers generation (POST /api/filter/generate)
  → get_latest_high_value_bases()    — is_high_value=True (≥3 listings, ≥50c)
  → get_priced_bases_above_threshold(≥8E ≈ 0.35c) — all priced bases
  → merge + dedup by name_en
  → generate_filter_with_prices()
       → generate_tier_based_white_rules()   ← AI rules injected before template
       → _generate_cheap_currency_hide()     ← poe.ninja live fetch (14 categories)
       → template (asmco_4_endgame.filter)   ← existing rules preserved
  → write to /app/data/generated_filters/

Users download (GET /api/filter/download)
  → returns the latest pre-generated .filter file (no regeneration)
```

### Filter rule layers (first-match-wins)

| Priority | Rule | Condition | Style |
|----------|------|-----------|-------|
| 1 | High-value bases | BaseType match (≥8E scanned) | Gold border, red star, alert sound |
| 2 | Tier 5+ white | `UnidentifiedItemTier >= 5`, `Rarity = Normal` | Green text, cyan border, sound + beam |
| 3 | Special bases | `BaseType "Heavy Belt"` etc. | Yellow border, yellow circle (ilvl-independent) |
| 4 | ilvl≥82 white | `ItemLevel >= 82`, `Rarity = Normal` | White border (subtle) |
| 5 | Low-tier white | `UnidentifiedItemTier < 5`, `Rarity = Normal` | Hide |
| 6 | Cheap currency | BaseType (poe.ninja < 1c, 14 categories) | Hide |
| — | Template rules | Tier 5 Rare/Magic, identified mods, etc. | Template's own styles |

### Key design decisions

- **Admin-only generation**: Users only download; no per-user regeneration. Scan → generate → download are separate steps.
- **Heavy Belt / chance-crafting bases**: Value is independent of ilvl (e.g. Heavy Belt → Orb of Chance → Hunter belt). These get a dedicated always-Show rule.
- **8E threshold**: PoE2 economy: 1E ≈ 0.04c, 1D ≈ 10c. 8E ≈ 0.34c catches ~43 bases including single-listing outliers.
- **poe.ninja live data**: `_generate_cheap_currency_hide()` calls `fetch_all_economy_prices()` at generation time (14 economy types). `_NEVER_HIDE_CURRENCIES` protects Chaos Orb, Exalted Orb, GCP, Vaal Orb, Mirror, Hinekora's Lock.
- **Scanner limitation**: `base_scanner.py` doesn't filter by `item_level`, so prices are averaged across all ilvls (low-ilvl junk drags down median). Future improvement: add `ilvl >= 82` to Trade API query.
- **Template**: `asmco_4_endgame.filter` (四后期). AI rules injected before template's first Show rule. Template's tier 5 Rare (yellow border) and Magic (blue border) rules are preserved.

### Frontend

`/filter` page (`frontend/src/app/filter/page.tsx`) — rule descriptions, download button, usage tutorial. No generation triggered by users.

## Concept Links

`concept_links.py` at ingest: entity names, ~60 concept hooks, chunk_type self-links. Stored in `knowledge_chunks.links`. Expansion during retrieval via `expand_concepts()`.

## Known Issues & Gotchas

1. **Encoding**: Container scripts must be UTF-8; avoid fragile `chr()` CJK escapes.
2. **SSH inline Python**: Multi-layer quoting breaks — write scripts to files.
3. **docker exec -d**: Dies on SSH disconnect — use sync exec with long timeout.
4. **Docker cache**: `docker compose up --build` may cache — `--no-cache` or hotfix scripts.
5. **Concept expansion noise**: Irrelevant links add retrieval noise.
6. **Frontend Turbopack**: See `frontend/AGENTS.md`; rebuild with `--no-cache` when needed.
7. **CHAT_RUNTIME**: Default is `legacy` ReAct; orchestrator is opt-in via env.
8. **Bare item name**: `扭曲项链` alone = encyclopedia (RAG), not trade search — agent must not return 10K generic amulet hits.
9. **Entity chips**: Never chip inside `英文名：` value columns or `NAME（alias）` parentheses.
10. **Filter template path**: Must be in `data/filter_templates/` (volume mount), not `backend/data/filter_templates/`. Container only sees `/app/data/`.
11. **Filter Chinese filenames**: `docker cp` garbles CJK filenames — use ASCII names for generated filters (e.g. `AI_tier.filter`).
12. **Base scanner ilvl**: `base_scanner.py` doesn't add `item_level` to Trade queries, so Heavy Belt price (0.41c) is dragged down by low-ilvl junk.
13. **Celery Beat override**: Automated daily scan (06:00) creates a newer batch that overrides manual scan data (`get_latest_high_value_bases()` uses `scanned_at DESC`).
14. **PoE2 filter limits**: Cannot display custom text on items — only colors, borders, icons, sounds, beams.

## Key Files Reference

### Chat & orchestration
| File | Purpose |
|------|---------|
| `backend/app/api/knowledge.py` | `/api/chat` SSE, `/api/knowledge/ask` |
| `backend/app/services/chat_orchestrator.py` | Runtime switch + orchestrator stream |
| `backend/app/services/chat_agent.py` | Legacy ReAct agent + `AGENT_SYSTEM` |
| `backend/app/services/chat_tools.py` | Tool registry + `execute_tool` |
| `backend/app/services/game_graph_service.py` | LLM-callable GGPK search (auto-fallback, expand, community synonyms) |
| `backend/app/services/chat_response_guard.py` | Post-hoc price fabrication guard (`strip_ungrounded_price_claims`) |
| `backend/app/orchestrator/llm_planner.py` | LLM task planner |
| `backend/app/orchestrator/session_context.py` | Multi-turn context contract |
| `backend/app/orchestrator/dispatcher.py` | Parallel sub-agent dispatch |
| `backend/app/orchestrator/runners.py` | Agent → tool mapping |

### GGPK data pipeline
| File | Purpose |
|------|---------|
| `backend/scripts/ggpk/export_en_tc.py` | Export EN + TC data from international Content.ggpk |
| `backend/scripts/ggpk/extract_sc.py` | Export SC data from CN WeGame client Bundles2 |
| `backend/scripts/import_game_data.py` | Import EN/TC/SC JSON into PostgreSQL `game_data` table |
| `backend/scripts/resolve_relations.py` | Resolve FK row indices → row_keys using PyPoE spec |
| `backend/scripts/resolve_string_fks.py` | Resolve string-based FK references (e.g. GrantedEffect) |
| `backend/scripts/game_graph.py` | In-memory knowledge graph with BFS traversal |
| `backend/scripts/query_graph.py` | CLI for graph traversal queries |
| `backend/data/poe2_data/en/` | 24 JSON files, English game data |
| `backend/data/poe2_data/tc/` | 14 JSON files, Traditional Chinese game data |
| `backend/data/poe2_data/sc/` | 24 JSON files, Simplified Chinese game data |
| `backend/data/poe2_data/game_relations.json` | 549K resolved relationship edges |

### Knowledge & entities
| File | Purpose |
|------|---------|
| `backend/app/services/retrieval_pipeline.py` | Unified RAG retrieval |
| `backend/app/services/entity_resolver.py` | CN→EN + Trade API aliases |
| `backend/app/services/entity_tooltip.py` | Mention detection + tooltips |
| `backend/app/services/entity_catalog_service.py` | Runtime entity catalog |
| `backend/app/services/concept_links.py` | Chunk link computation |
| `backend/app/data/trade_items_en_cn.json` | Official bilingual item index |

### Trade & builds
| File | Purpose |
|------|---------|
| `backend/app/services/trade_agent.py` | Chat + /trade search pipeline |
| `backend/app/services/trade_service.py` | Trade API client + query builder |
| `backend/app/services/trade_items_index.py` | Base type match + `type` filter |
| `backend/app/services/pob_service.py` | PoB decode + parse |

### Filter & base scanner
| File | Purpose |
|------|---------|
| `backend/app/api/filter.py` | `/api/filter/*` endpoints (scan, generate, download) |
| `backend/app/services/filter_generator.py` | Filter rule generation (tier-based, poe.ninja currency hide) |
| `backend/app/services/base_scanner.py` | 857 white base Trade API scanner |
| `backend/app/services/poe_ninja_service.py` | poe.ninja currency + economy price fetcher |
| `backend/data/filter_templates/asmco_4_endgame.filter` | Base filter template (四后期) |
| `frontend/src/app/filter/page.tsx` | Filter page UI (rules, download, tutorial) |

### Skills (prompts)
| File | Purpose |
|------|---------|
| `backend/app/skills/router.py` | `get_skill()` for orchestrator synthesis |
| `backend/app/skills/*.py` | Per-domain system prompt fragments |

### Frontend
| File | Purpose |
|------|---------|
| `frontend/src/app/page.tsx` | Home — PoB build analyzer |
| `frontend/src/app/chat/page.tsx` | Chat UI |
| `frontend/src/app/filter/page.tsx` | Filter page — rules, download, tutorial |
| `frontend/src/components/SiteNav.tsx` | Top nav — LINKS array for route tabs |
| `frontend/src/components/chat/ChatMarkdown.tsx` | Markdown + entity chips |
| `frontend/src/components/chat/PoeEntityChip.tsx` | Chip + tooltip hover |

### Ops
| File | Purpose |
|------|---------|
| `deploy_nas.py` | NAS deploy via SSH |
| `scripts/deploy_tencent.py` | Tencent production deploy |
| `scripts/nas/hotfix_*.py` | Quick single-file NAS backend patches |
| `docs/ops/deployment.md` | Full ops runbook |
