# Sprint 2 — Embedding + 知识图谱 预研方案

> 状态：预研 / 设计草案  
> 责任人：拾遗（数据工程师）  
> 关联 Sprint：Sprint 2  
> 依据：Sprint 1 预研分析、`backend/app/services/embedding_service.py`、`backend/app/services/knowledge_graph_service.py`

---

## 一、Embedding 现状

### 1.1 当前实现
- **模型**：BAAI/bge-m3（多语言，支持 TC/SC/EN）
- **接入方式**：SiliconFlow API 优先，local sentence-transformers 降级
- **缓存**：Redis 24h TTL，key = `emb:{dim}:{sha256(text[:32])}`
- **维度**：1024（`EMBEDDING_DIM` 环境变量控制）
- **调用点**：`knowledge_service.py`（chunking + query）、`chat_tools.py`（build search、game search）

### 1.2 已识别缺口
| 缺口 | 影响 | 严重度 |
|------|------|--------|
| 无批量回填 | 新增 chunk 或维度变更后，需逐条触发 embedding | P1 |
| 无维度漂移监控 | API 模型升级后可能返回不同维度，导致向量查询失效 | P1 |
| 失败无重试 | API 超时/限流时直接返回 None，上游降级为无结果 | P2 |
| 缓存失效策略 | 24h TTL 固定，无法按 league/game_version 隔离 | P2 |
| 本地 fallback 冷启动 | 首次加载 ~2.2GB，NAS 小内存容器可能 OOM | P2 |

### 1.3 Sprint 2 改进方案

**A. Batch backfill job**
- 新增 `scripts/backfill_embeddings.py`，批量扫描 `knowledge_chunks` 中 `embedding IS NULL` 的 chunk
- 分批提交（batch_size=100），每批 commit，失败跳过并记录
- 支持 `--force` 重跑已有 embedding（用于模型升级后全量刷新）
- 依赖：Celery beat 或手动 trigger

**B. Dimension drift guard**
- 在 `embedding_service.py` 中增加启动时自检：取 1 条固定文本生成 embedding，验证维度是否匹配 `EMBEDDING_DIM`
- 不匹配时告警日志 + 可选 fallback 到 local model
- 不改变现有调用点

**C. Retry + circuit breaker**
- API 调用增加 `tenacity` 或手写指数退避（max 3 次）
- 连续失败 N 次后切换到 local fallback（若可用），避免空转

**D. 缓存 key 增加隔离维度**
- 当前 key 只按 text，建议增加 `league:game_version` 后缀，避免不同赛季内容互相覆盖

---

## 二、知识图谱现状

### 2.1 当前实现
- **存储**：`kb_entities` + `kb_edges`（PostgreSQL）
- **构建**：`knowledge_graph_service.py` — chunk ingest 时自动 sync
- **回填**：`backfill_knowledge_graph.py` — 对现有 chunk 批量 sync
- **查询**：`expand_via_graph()` — BFS 1-2 hop，返回相关 chunk

### 2.2 已识别缺口
| 缺口 | 影响 | 严重度 |
|------|------|--------|
| Edge weight 固定启发式 | 无法区分"核心关系"和"偶然共现" | P2 |
| 无 created_at / 版本标记 | 无法按 league/game_version 隔离图谱 | P1 |
| Expand 相似度人工公式 | `0.7 + weight*0.1` 与向量距离脱节，结果排序不准 | P2 |
| 无数据质量校验 | `graph_available()` 只查表存在性，不校验实体/边数量 | P2 |
| 无增量更新策略 | 每次 backfill 全量重跑，chunk 量大时慢 | P2 |

### 2.3 Sprint 2 改进方案

**A. Schema 扩展**
- `kb_edges` 增加 `created_at TIMESTAMP`、`decay_weight FLOAT DEFAULT 1.0`
- `kb_entities` 增加 `last_seen_at TIMESTAMP`（用于冷实体清理）

**B. Graph expansion 相似度改进**
- 保留现有 BFS，但返回结果按 `1 - cosine_distance(query_embedding, chunk_embedding)` 重排
- 不再使用固定公式 `0.7 + weight*0.1`

**C. 增量 sync 策略**
- `sync_chunk_graph` 增加幂等标记：`chunk_id + relation` 唯一性约束
- 避免重复 ingest 时创建重复边

**D. 数据质量仪表盘**
- 新增 `scripts/graph_quality_report.py`：统计实体数、边数、平均度数、孤立实体比例
- 接入 CI/CD 或每日 cron

---

## 三、优先级与依赖

| 项目 | 优先级 | 依赖 | 预估工时 |
|------|--------|------|----------|
| Embedding batch backfill | P1 | Celery beat 可用 | ~0.5d |
| Dimension drift guard | P1 | 无 | ~0.25d |
| KB schema 扩展（created_at） | P1 | Alembic migration | ~0.25d |
| Cache key 隔离 | P2 | 无 | ~0.25d |
| Retry + circuit breaker | P2 | 无 | ~0.5d |
| Graph expansion 相似度改进 | P2 | 无 | ~0.5d |
| 增量 sync 幂等 | P2 | 无 | ~0.25d |
| 数据质量仪表盘 | P2 | 无 | ~0.5d |

**Sprint 2 建议聚焦**：P1 三项（batch backfill + dim drift + schema 扩展），其余排入后续迭代。

---

## 四、设计边界

- **不改动现有调用点**：`knowledge_service.py`、`chat_tools.py` 的 `get_embedding()` 调用保持现状
- **不引入新模型**：继续使用 BGE-M3，不评估替换方案
- **不重构 KG 存储**：继续用 PostgreSQL + pgvector，不迁移到图数据库
- **先出方案再评审**：Sprint 2 启动前由远岫 review，确认后再落地

---

*预研维护：拾遗 | 创建时间：项目时间 第 4 天*
