# 数据与运维现状评估报告

**评估者**：守夜（数据与运维组经理）
**评估时间**：项目时间 第 0 天 07:00 — 16:00
**状态**：初稿 / 待方向对齐会审议

---

## 一、数据管道总览

### 1.1 数据分类矩阵

| 数据类别 | 位置 | 规模 | 更新频率 | 更新机制 |
|----------|------|------|----------|----------|
| **GGPK 游戏数据（EN）** | `backend/data/poe2_data/en/` | 356 文件 / ~199 MB | 随游戏版本更新（2-4 周） | 手动：GGPK 导出 → JSON |
| **GGPK 游戏数据（SC）** | `backend/data/poe2_data/sc/` | 356 文件 / ~199 MB | 同上 | 手动：GGPK 导出 → JSON |
| **GGPK 游戏数据（TC）** | `backend/data/poe2_data/tc/` | **102 文件 / ~81 MB** | 同上 | **严重不完整** |
| **知识图谱边数据** | `backend/data/game_relations.json` | **不存在（预期 ~84.6 MB）** | 随 game data 更新 | 由 `resolve_relations.py` 运行时生成 |
| **交易物品双语映射** | `backend/data/trade_items_bilingual.json` | 782 KB | 按需 | `fetch_trade_items_bilingual.py` |
| **交易词缀双语映射** | `backend/data/trade_stats_bilingual.json` | 1.8 MB | 按需 | `fetch_trade_stats_bilingual.py` |
| **实体图标目录** | `backend/data/entity_icons.json` | 空（2 B） | — | 爬虫 |
| **过滤器配置** | `backend/data/filter_config.json` | 346 B | 手动 | — |
| **数据库（运行态）** | 本地 SQLite / 生产 PostgreSQL + pgvector | — | 事务性 | SQLAlchemy ORM + Alembic 迁移 |

### 1.2 数据更新流水线

```
游戏客户端 GGPK (.dat 文件)
    │
    ├─ export_en_tc.py  ──→ en/ + tc/ JSON（从 PyPoE 读取英文+繁体数据）
    └─ extract_sc.py    ──→ sc/ JSON（从简体中文客户端提取）
        │
        ▼
    import_game_data.py ──→ PostgreSQL (game_data 表)
        │
        ▼
    resolve_relations.py ──→ game_relations.json（FK 解析）
        │
        ▼
    知识图谱入库 ──→ KB entities + edges
```

**所有步骤目前均为手动执行，无自动化编排。**

---

## 二、多语言数据一致性分析

### 2.1 文件数量对比

| 目录 | 文件数 | 总大小 | 与 EN 差异 |
|------|--------|--------|-----------|
| en/ | 356 | 199.22 MB | —（基准） |
| sc/ | 356 | 199.06 MB | ✅ 数量一致，大小略有差异（翻译文本不同） |
| tc/ | **102** | **80.69 MB** | ❌ 少 254 个文件 |

### 2.2 TC 缺失的关键数据文件

TC 目录严重不完整，以下是缺失的最关键文件：

| 缺失文件 | 说明 | 影响 |
|----------|------|------|
| `Mods.json` (32.6 MB) | 所有词缀/词条定义 | AI 问答在繁体场景下无法回答词缀问题 |
| `GrantedEffects.json` (8 MB) | 技能效果定义 | 技能查询在繁体下失效 |
| `GrantedEffectsPerLevel.json` (19 MB) | 技能等级效果 | 等级数据缺失 |
| `ItemVisualIdentity.json` (39.4 MB) | 物品图标映射 | 物品展示异常 |
| `Stats.json` (13.3 MB) | 属性/状态定义 | 属性检索失效 |
| `PassiveSkills.json` (16.5 MB) | 天赋树数据 | 天赋查询失效 |
| `ActiveSkills.json` (1.8 MB) | 主动技能 | 技能百科失效 |
| `BaseItemTypes.json` (5 MB) | 基础物品类型 | 物品类型识别失效 |
| `Chests.json` | 宝箱 | — |
| `CurrencyItems.json` | 通货 | — |
| `Words.json` | 多语言词汇 | — |
| `WorldAreas.json` | 地区 | — |
| … 等 240+ 文件 | — | — |

### 2.3 根本原因推测

GGPK 导出流程中，TC 的 `export_en_tc.py` 与 SC 的 `extract_sc.py` 是**两个独立的导出脚本**。SC 有单独从简体中文客户端提取数据的完整流程，而 TC 导出（与 EN 共用 `export_en_tc.py`）可能只配置了部分表，或者导出版本落后。

需要检查 `export_en_tc.py` 的配置，确认是否所有表都已映射到繁体翻译字段。

---

## 三、Celery 异步任务体系

### 3.1 配置总览

| 项 | 值 |
|----|-----|
| Broker | Redis（DB 1） |
| Result Backend | Redis（DB 2） |
| 序列化 | JSON |
| 时区 | Asia/Shanghai |
| 任务包含 | `app.tasks.worker` |
| 定时调度 | `crontab(hour=6, minute=0)` 每日价格扫描 |

### 3.2 注册任务

| 任务名 | 功能 | 重试策略 | 备注 |
|--------|------|----------|------|
| `generate_homework_task` | AI 生成 Build 攻略 → DB 保存 → 知识库入库 | 最多 3 次，60s 间隔 | 用户提交 Build 后触发 |
| `scan_base_prices_task` | 扫描装备底价 → 写 DB → 自动生成过滤器 | 最多 1 次，300s 间隔 | 定时每天 06:00 + 可手动触发 |

### 3.3 评估

- ✅ 基础设施完整（Celery + Redis + Beat）
- ✅ 任务定义清晰，异常处理到位（retry + 日志 + 非致命错误降级）
- ⚠️ 只有 2 个任务，体系很轻量，随着业务扩展可能需要更多异步处理
- ✅ 知识库入库兼容在任务中（generate_homework_task 内联调用 ingest_build）

---

## 四、Docker 部署方案评估

### 4.1 服务架构

```
docker-compose.yml — 7 个服务
├── postgres (pgvector/pg15) — 数据库 + 向量扩展
├── redis (7-alpine) — 缓存 + Celery broker/backend
├── backend (FastAPI) — API 服务
├── celery_worker — 异步任务执行
├── celery_beat — 定时任务调度
├── frontend (Next.js) — 前端
├── langfuse (v3) — LLM 可观测性
└── langfuse-clickhouse — Langfuse 分析引擎
```

### 4.2 组件详情

| 组件 | 镜像/基础 | 端口 | 健康检查 | 资源限制（生产） |
|------|-----------|------|----------|----------------|
| postgres | pgvector/pg15 | 5433 → 5432，生产关闭外部端口 | pg_isready, 5s | 512M |
| redis | 7-alpine | 6379:6379，生产关闭 | redis-cli ping, 5s | 128M |
| backend | python:3.10-slim | 8000:8000 | /health endpoint, 30s | 1.5G |
| celery_worker | 同 backend | — | — | — |
| celery_beat | 同 backend | — | — | — |
| frontend | node:20-alpine | 3000:3000 | — | 384M |
| langfuse | langfuse/langfuse:3 | 3001:3000 | — | — |
| clickhouse | clickhouse/clickhouse-server:24 | — | clickhouse-client, 5s | — |

### 4.3 关键发现

**✅ 正面**
- docker-compose 完整，含 Celery + Langfuse 全套
- `docker-compose.tencent.yml` 作为生产覆盖存在（关闭端口暴露、移除代理、添加资源限制）
- entrypoint 自动跑 Alembic 迁移
- 健康检查完善
- Volume 持久化数据

**⚠️ 风险点**

1. **celery_beat 生产环境默认不启用**
   - `docker-compose.tencent.yml` 中 `celery_worker` 标记了 `profiles: ["celery"]`，但 `celery_beat` 没有显式处理
   - 每日 06:00 的 `scan_base_prices_task` 定时任务在 **生产部署中可能不会运行**
   - 后果：价格数据逐渐过时，过滤器不再自动更新

2. **缺少监控告警**
   - 有 Langfuse（LLM 可观测性），但缺少常规的 Prometheus/Grafana/告警通知
   - 容器 healthcheck 存在但无故障通知机制

3. **环境变量管理**
   - `.env.example` 存在但需要人工复制配置
   - 生产密钥管理依赖 docker compose 的 env_file 机制，无密钥管理服务

---

## 五、数据库与迁移

| 项 | 内容 |
|------|------|
| ORM | SQLAlchemy 2.0 |
| 迁移工具 | Alembic |
| 迁移版本 | 9 个（`09304a65...` ~ `f9a2c7e8...`） |
| 本地 DB | SQLite（开发） |
| 生产 DB | PostgreSQL 15 + pgvector |
| 扩展 | pgvector（向量嵌入搜索） |

**迁移覆盖的表**：
- KB entities + edges（知识图谱）
- KnowledgeChunks + RAG 列（RAG 检索）
- GameData（游戏数据）
- TradeStats（交易统计）
- Chat history（对话历史）

迁移体系完整 ✅，9 个版本渐进演化，无断裂风险。

---

## 六、关键风险与问题汇总

| # | 严重度 | 问题 | 影响 |
|---|--------|------|------|
| 🔴 P0 | **严重** | TC 数据缺失 70%+（254 个文件） | 繁体中文用户 AI 问答 / 交易系统基本不可用 |
| 🔴 P0 | **严重** | game_relations.json 不存在 | 知识图谱构建缺少基础输入，但可能是运行态生成 |
| 🟡 P1 | **高** | 数据更新全手动，无流水线编排 | 版本更新时人工操作易遗漏、容错低 |
| 🟡 P1 | **高** | celery_beat 生产环境默认不运行 | 定时任务（价格扫描/过滤器更新）可能永远不触发 |
| 🟡 P1 | **中** | 缺少数据变更校验机制（文件数/大小/关键字段） | 数据损坏或缺失可能上线后才发现 |
| 🟢 P2 | **中** | 无统一监控告警 | 服务异常无法第一时间感知 |
| 🟢 P2 | **低** | 爬虫脚本分散，多种爬取策略 | 数据源切换或失效时排查成本高 |

---

## 七、优先改进方向

### P0 — 补齐 TC 多语言数据（方向对齐会必讨论项）

**问题**：TC 目录只有 102 个 JSON 文件，缺失约 254 个关键文件。

**建议方案**：
1. 审查 `scripts/ggpk/export_en_tc.py` 的配置，确认 TC 字段映射是否完整
2. 补跑 TC 导出流程，或重新配置导出表列表
3. 建立**导出后自动校验脚本**，对比三语文件数量和大小
4. 考虑在 CI/CD 中加入数据一致性检查

**验收标准**：tc/ 目录文件数达到 356 个，关键数据文件（Mods.json、GrantedEffects.json、Stats.json 等）完整

---

### P1 — 数据更新流水线自动化

**问题**：从 GGPK 导出到 DB 入库全手动，PoE2 每 2-4 周一次版本更新。

**建议方案**：
1. 将数据更新流程编排为可重复执行的工作流（Makefile / shell script 或 CI pipeline）
2. 加入自动化校验步骤（文件数对比、大小对比、关键字段抽样检查）
3. 建立数据版本标记（git tag 或数据库 version 字段）
4. 数据更新触发知识图谱重建的自动化衔接

**验收标准**：一条命令 / 一次 CI 触发即可完成完整数据更新流程

---

### P1 — Docker 生产运维完善

**问题**：celery_beat 定时任务可能不运行，缺少监控。

**建议方案**：
1. 确认 `celery_beat` 在生产 compose 中的 profile 配置，确保定时任务生效
2. 如果当前无 Celery Beat 需求，考虑移除未被调度的定时任务配置，避免误导
3. 短期：增加容器级监控（容器重启通知）
4. 长期：引入 Prometheus + 告警通知（飞书/钉钉 webhook）

---

### P2 — 文档与流程规范化

**建议方案**：
1. 将数据导出、导入、知识图谱构建等操作写成标准化操作手册（SOP）
2. 建立数据管道故障恢复文档
3. 爬虫脚本统一管理（如统一 BaseScraper 类）

---

## 附录 A：脚本目录功能索引

| 脚本 | 功能 | 类别 |
|------|------|------|
| `ggpk/export_en_tc.py` | GGPK → EN+TC JSON 导出 | 数据导出 |
| `ggpk/extract_sc.py` | GGPK → SC JSON 导出 | 数据导出 |
| `import_game_data.py` | JSON → 数据库导入 | 数据导入 |
| `resolve_relations.py` | FK 解析 → game_relations | 知识图谱 |
| `fetch_trade_items_bilingual.py` | Trade API → 双语映射 | 双语数据 |
| `fetch_trade_stats_bilingual.py` | Trade API → 词缀映射 | 双语数据 |
| `daily_filter_update.py` | 价格扫描+过滤器生成 | 运维 |
| `build_entity_catalog.py` | 实体目录生成 | 知识图谱 |
| `scrape_poe2db*.py` | poe2db 数据爬取 | 爬虫 |
| `scrape_poe2wiki*.py` | poe2wiki 数据爬取 | 爬虫 |
| `scrape_caimogu_*.py` | 踩蘑菇数据爬取 | 爬虫 |
| `backfill_knowledge_graph.py` | 知识图谱回填 | 知识图谱 |
| `game_graph.py` | 知识图谱查询 | 知识图谱 |

## 附录 B：Alembic 迁移版本列表

```
09304a65a604_add_knowledgechunk_table.py
51f150c4c1ae_init_db_schema.py
a1b2c3d4e5f6_add_game_data_table.py
a3c7e2f81b45_add_rag_columns_to_knowledgechunks.py
b4d8e3f12c56_add_trade_stats_table.py
c5f2a8d91e03_add_links_to_knowledge_chunks.py
d7e1b4c92f58_add_kb_entities_edges.py
e8f3a1b02c47_add_ref_text_zh_to_trade_stats.py
f9a2c7e83d61_add_reasoning_to_chat_history.py
```

---

*报告结束。待方向对齐会审议后确定冲刺任务优先级。*
