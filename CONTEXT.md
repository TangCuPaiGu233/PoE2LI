# CONTEXT.md — Project Glossary

## PoB (Path of Building)

| Term | Meaning |
|------|---------|
| **PoB** | Path of Building — the de facto build planner for PoE/PoE2 |
| **PoB Code / Share Code** | A base64+zlib encoded string representing a full build. Starts with `eN`. URL-safe variant uses `-_` instead of `+/` |
| **PoB XML** | The decoded XML inside a share code. Root element: `<PathOfBuilding2>` |
| **BuildData** | Our internal structured JSON parsed from PoB XML — the canonical representation we store and pass to AI |
| **Spec** | A passive tree specification (one build can have multiple: leveling, endgame, etc.) |
| **SkillSet** | A collection of gem setups. One build can switch between multiple SkillSets |
| **Skill** | A single socket group (e.g. a 6-link body armour). Contains multiple Gems |
| **Gem** | A skill gem or support gem. Key fields: `nameSpec` (display name), `skillId` (internal ID), `level`, `quality` |
| **Item** | Equipment text block. First line is `Rarity: RARE/UNIQUE/MAGIC`, followed by name, base type, and affixes |
| **ItemSet** | A collection of equipped items. References Items by ID and maps them to Slots |
| **Slot** | An equipment position (Weapon 1, Body Armour, Gloves, etc.) |
| **PlayerStat** | Pre-computed stats from PoB (DPS, Life, Resistances). We NEVER recalculate these — always take PoB's values |

## PoE2 Game Terms

| Term | Meaning |
|------|---------|
| **Class** | Base character class (Marauder, Ranger, Witch, etc.) |
| **Ascendancy** | Specialization within a class (e.g. Juggernaut under Marauder) |
| **Passive Tree / Talent Tree** | The skill tree where players allocate nodes for stats and abilities |
| **Node** | A single point on the passive tree, identified by numeric ID |
| **Affix** | A modifier on an item. Prefixes and suffixes. In raw item text, these are unstructured lines |
| **DPS** | Damage Per Second — the key damage metric |
| **EHP** | Effective Hit Pool — how much damage a character can take before dying |
| **Resistance** | Fire/Cold/Lightning/Chaos resistance. Cap is 75% by default |
| **Link / 6-link** | Gems socketed in connected slots on equipment. A "6-link" means 1 active + 5 supports |

## Project-Specific Terms

| Term | Meaning |
|------|---------|
| **Homework** | The AI-generated Chinese playbook for a build (our core output product) |
| **Playbook / 攻略** | Chinese-language build guide: why this setup, core items, budget alternatives, talent highlights, strength review |
| **P0 Core Loop** | PoB decode → parse → AI generate homework → store → display. The only target for v1.0 |
| **Mod Translation** | English→Chinese affix mapping. Table lookup first, AI fallback for unknowns |
| **Knowledge Chunks** | RAG vector store entries (pgvector). Always filtered by `league` + `game_version` |

## API Terms

| Term | Meaning |
|------|---------|
| **Decode** | `POST /api/builds/decode` — PoB code → BuildData JSON (no storage) |
| **Homework** | `POST /api/builds/homework` — PoB code → decode + AI playbook (no storage) |
| **Save** | `POST /api/builds` — PoB code → decode + AI + store in DB |
| **Retrieve** | `GET /api/builds/{id}` — get stored build + homework |

## Database Terms

| Term | Meaning |
|------|---------|
| **builds table** | Main table: `id`, `pob_code`, `build_data` (JSON), `homework` (JSON), `league`, `game_version`, `status` |
| **status** | `pending` → `parsed` → `done` (or `failed`). `done` means homework is generated |
| **SQLite** | Dev/test database. Production will use PostgreSQL |

## Architecture Decisions

| Decision | Reasoning |
|----------|-----------|
| **Code decodes, AI interprets** | Anything deterministic (base64, zlib, XML parse) is code. Anything fuzzy (affix meaning, build logic) is AI |
| **Never recalculate PoB stats** | PoB's computed values are the source of truth. Recalculating introduces errors |
| **PoB XML uses attributes, not children** | Tree nodes are in `nodes` attribute (comma-separated), gem data in element attributes. NOT child elements |
| **Two PoB export formats** | Full (items+skills+tree) and minimal (tree+stats only). Parser must handle both gracefully |
