# Phase 2 数据管道方向确认纪要

> 日期：2026-06-26  
> 作者：松烟（后端开发）  
> 状态：待朝露/远岫/人间草木 review

---

## 方向 A — 知识图谱数据源

**现状**：`backend/data/game_relations.json` 当前不存在（预期 ~84.6MB），但生成脚本 `resolve_relations.py` 可用。

**结论**：
- 继续使用 `resolve_relations.py` **运行时生成**，不改为 build-time 产物。
- 原因：PyPoE 依赖较重，且 GGPK 更新频率低，运行时生成可接受。
- 纳入 `run_pipeline.py` 作为 `relations` step，成为可重复 pipeline 的一部分。
- 可选增强：生成后同时写入 PostgreSQL `kb_edges`/`kb_entities`，但 Phase 2 先保持 JSON 文件作为单一事实来源。

**待决**：是否需要 `game_relations.json` 与 PostgreSQL 双写？

---

## 方向 B — 与守夜分工边界

**已确认边界**：

| 角色 | 负责范围 |
|------|----------|
| **守夜（数据工程师）** | GGPK 导出 → SC/TC/EN JSON 文件 → 数据文件校验 |
| **松烟（后端开发）** | `import_game_data.py` 入库 → 知识图谱构建 → pipeline 编排 |

**知识图谱侧具体由松烟负责**：
- `game_relations.json` 生成与版本管理
- `game_data` → `knowledge_chunks` 桥接（Phase 2 Week 2-3）
- `GameGraph` / `kb_entities` / `kb_edges` 查询入口统一（Phase 2 Week 4）

**无重叠区**：守夜不负责知识图谱，松烟不负责 GGPK 导出。

---

## 方向 C — 技术栈选择

**结论**：当前 `GameGraph`（内存 + LRU cache + lazy loading）**无需升级**，Phase 2 保持文件层为主。

**理由**：
- 数据量可控：~549K edges，内存图查询性能足够
- 已有 LRU cache（max 16 tables）和 lazy loading，避免全量加载
- 若后续需要持久化，可降级到 PostgreSQL `kb_entities`/`kb_edges`，但 Phase 2 不急于引入图数据库

**可选增强**：
- Phase 2 Week 1：`game_relations.json` 版本检查（hash/timestamp）
- Phase 2 Week 4：DB 层 fallback，优先读 `kb_entities`，降级到 JSON

---

## 待决事项（需升级决策）

| # | 待决事项 | 建议 | 需决策人 |
|---|---------|------|---------|
| 1 | `game_relations.json` 是否双写 PostgreSQL？ | Phase 2 先保持 JSON，Week 4 评估 | 远岫 |
| 2 | `KbEntity` 是否需要 `game_version` 字段？ | 需要，支持多版本并存 | 远岫/来迟 |
| 3 | 路线 B（chunks-generate）是否依赖 TC 数据补齐？ | 不阻塞，EN fallback 即可启动 | 朝露 |
| 4 | embedding 服务 batch size / retry 策略？ | batch=32, max_retries=3, exponential backoff | 归鸿 |

---

## 下一步行动

1. **朝露** → 确认纪要后，分配 Phase 2 Week 1 任务（`graph-import` step）
2. **远岫** → 评估待决事项 1、2
3. **松烟** → 待确认后开始 Week 1 实现

---

*本文档为方向确认，不涉及生产代码修改。*
