# Phase 2 TC→KG 接口协议

> 状态：草案  
> 作者：松烟（后端开发）  
> 日期：2026-06-26  
> 范围：TC JSON 数据 → 知识图谱入库的输入格式与 fallback 策略

---

## 1. 数据流总览

```
TC JSON 文件（守夜提供）
    │
    ▼
import_game_data.py ──→ game_data 表（PostgreSQL）
    │                      ├── table_name
    │                      ├── row_key
    │                      ├── name_en / name_tc / name_sc
    │                      └── data: {"en": {...}, "tc": {...}, "sc": {...}}
    │
    ▼
resolve_relations.py ──→ game_relations.json
    │                       ├── meta: {total_edges, fk_fields, tables}
    │                       └── edges: [{src_table, src_key, dst_table, dst_key, relation}, ...]
    │
    ▼
backfill_game_data_relations.py ──→ kb_entities / kb_edges（PostgreSQL）
```

**核心结论**：知识图谱入库的直接输入是 `game_relations.json`，不是 TC JSON 文件本身。TC JSON 的作用是：
1. 提供 `name_tc` / `name_sc` 显示名（经 `import_game_data.py` 写入 `game_data`）
2. 作为 `resolve_relations.py` 的 EN 基础数据源

---

## 2. TC JSON 文件中知识图谱入库关注的字段

### 2.1 必用字段

| 字段 | 来源 | 用途 |
|------|------|------|
| `Id` / `Name` / key field | TC JSON 行数据 | 成为 `GameDatum.row_key` 和 `game_relations.json` 的 `src_key`/`dst_key` |
| `Name` / `DisplayedName` / `Description` | TC JSON 行数据 | 成为 `GameDatum.name_tc` |
| 整行 JSON | TC JSON 文件 | 存入 `GameDatum.data.tc`，供后续 enrich 使用 |

### 2.2 字段优先级

`import_game_data.py` 的 `get_display_name()` 按以下顺序提取显示名：

1. Locale-specific override（如 `Words` 表的 `Text2`）
2. Config 指定的 name field（如 `Mods.Name`、`BaseItemTypes.Name`）
3. Fallback chain：`Name` → `DisplayedName` → `Id` → `Text` → `Description`

---

## 3. `backfill_game_data_relations.py` 输入格式

### 3.1 `game_relations.json` 结构

```json
{
  "meta": {
    "total_edges": 549882,
    "fk_fields": 891,
    "tables": ["ActiveSkills", "Mods", "Stats", ...]
  },
  "edges": [
    {
      "src_table": "AchievementItems",
      "src_key": "PerandusCatchFishMoeanu",
      "dst_table": "Achievements",
      "dst_key": "PerandusCatchFish",
      "relation": "AchievementsKey"
    },
    ...
  ]
}
```

### 3.2 必需字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `src_table` | string | 源表名，如 `Mods` |
| `src_key` | string | 源行 key，通常是 `Id` 字段值 |
| `dst_table` | string | 目标表名 |
| `dst_key` | string | 目标行 key |
| `relation` | string | 关系类型，如 `grants`、`provided_by`、`scales_with` |

### 3.3 输出映射

| 输入 | `kb_entities` 字段 | 说明 |
|------|-------------------|------|
| `{src_table}:{src_key}` | `entity_key` | 形如 `Mods:Strength1` |
| `src_table` | `entity_type` | 通过 `infer_entity_type()` 映射：`Mods→mod`、`Stats→stat`、`ActiveSkills→skill` 等 |
| `src_key` | `name_en` | 默认值，后续可从 `game_data.name_sc` enrich |
| `game_version` | `game_version` | 通过 `--game-version` 传入 |
| `relation` | `KbEdge.relation` | 缺失时 fallback 到 `"related"` |

---

## 4. Fallback 策略

| 场景 | Fallback 行为 |
|------|--------------|
| TC JSON 文件缺失 | 继续用 EN 数据，`name_tc`/`name_sc` 为 NULL |
| TC JSON 行数少于 EN | 只导入存在的 TC 行，缺失行 `name_tc` 为 NULL |
| `game_relations.json` 缺失 | `graph-import` step 跳过，报错但不中断 pipeline |
| 关系类型缺失 | `KbEdge.relation = "related"` |
| 实体类型未知 | `entity_type = "entity"` |
| `name_cn` 缺失 | `KbEntity.name_cn = NULL`，Phase 2 Week 2 可从 `game_data.name_sc` enrich |
| `game_version` 未传入 | `KbEntity.game_version = NULL`，仍可入库但不利于版本过滤 |
| `KbEntity`/`KbEdge` 表不存在 | `backfill_game_data_relations.py` 报错退出，需先运行 `alembic upgrade head` |

---

## 5. 守夜需要保证的 TC 数据格式

### 5.1 目录结构

```
data/poe2_data/
├── en/
│   ├── Mods.json
│   ├── Stats.json
│   └── ...
├── tc/
│   ├── Mods.json
│   ├── Stats.json
│   └── ...
└── sc/
    ├── Mods.json
    ├── Stats.json
    └── ...
```

### 5.2 JSON 行格式要求

- 每个文件必须是 **JSON 数组**，每个元素是一行记录
- 每行必须包含 **key field**（如 `Id`、`Name`），用于 `row_key` 生成
- TC 行中的 `Name`/`DisplayedName`/`Description` 字段将被提取为 `name_tc`

### 5.3 与 EN 的对齐要求

- `row_key` 必须与 EN 版本一致（由 key field 决定）
- TC 文件中的 key field 值缺失或变更会导致该行被跳过或错位

---

## 6. 松烟 `graph-import` 脚本要求

### 6.1 输入

- `game_relations.json`：由 `resolve_relations.py` 生成，或由守夜按上述格式提供
- `--game-version`：版本标签，如 `0.2.0`

### 6.2 输出

- `kb_entities` 表：实体节点
- `kb_edges` 表：关系边

### 6.3 幂等性

- 同一 `game_version` 重新运行会先删除旧实体，再插入新实体
- 不同 `game_version` 并行存在，互不干扰

---

## 7. 待确认事项

| # | 问题 | 建议 |
|---|------|------|
| 1 | `game_relations.json` 的 `relation` 字段是否需要 TC 本地化？ | 建议保持英文关系名，`KbEdge.relation` 作为内部标识，展示层再本地化 |
| 2 | TC `name_cn` 何时 enrich 到 `KbEntity`？ | Phase 2 Week 2，通过 `game_data.name_sc` 批量回填 |
| 3 | 若 TC 行缺少 key field，是否整表跳过？ | 建议仅跳过缺失行，不中断整表处理 |

---

*本文档为接口协议草案，供守夜/松烟对齐使用。*
