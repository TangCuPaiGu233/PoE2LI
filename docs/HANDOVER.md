## PoE2LI 开发交接文档

> **⚠️ 历史快照 — 2026-06-08**
> 本文档是 2026-06-08 的开发交接记录，部分内容可能已过时。
> **当前项目状态以 [`/CLAUDE.md`](/CLAUDE.md) 为准**，矛盾时 CLAUDE.md 优先。
> 详见 [B4 文档对账报告](/docs/B4-文档对账报告.md)。

最后更新: 2026-06-08（B4 文档对账后本文件标记为历史快照）

---

### 一、项目状态总览

| 模块 | 状态 | 说明 |
|------|------|------|
| PoB 解码器 | 已完成 | base64+zlib 解码、XML 解析、BuildData 结构化 |
| AI 作业生成 | 已完成 | LLM 生成中文攻略、预算替代方案 |
| 知识库 RAG | 已完成 | pgvector 向量检索、版本过滤 |
| **交易搜索 (Trade)** | **已完成** | **LLM 意图解析 → 向量匹配 → Trade API → URL** |
| **Trade 集成到聊天** | **已实现 (Agent层) 🔄** | **Chat Agent 通过 `trade_search` 工具可执行交易搜索。后端✅ 前端独立Trade页面❌（见 Sprint 2）** |
| 前端 | 基础完成 | Next.js + TailwindCSS |
| Docker 部署 | 已完成 | NAS Docker Compose 运行中 |

### 二、交易搜索系统 — 核心架构

```
用户中文输入 (如 "稀有戒指 生命80以上 火抗30以上 不要诅咒")
    ↓
[parse_intent_ai] LLM (DeepSeek V4 Flash) 解析为结构化 JSON
    ├── item_type / rarity / price / item_level / quality / ...
    └── stat_groups: [{type:"and", stats:[...]}, {type:"not", stats:[...]}]
    ↓
[_resolve_stat] 向量搜索 (BGE-M3, 1024维) 匹配 Trade API stat_id
    ├── 优先匹配 explicit 类型 (Trade API 只接受 explicit.*)
    └── 自动归一化: crafted.*/implicit.* → explicit.*
    ↓
[build_trade_query] 构建 Trade API 请求体
    ├── type_filters: category + rarity + ilvl + quality
    ├── req_filters: lvl (需求等级)
    ├── equipment_filters: 武器/护甲面板属性 (PoE2 统一)
    ├── misc_filters: corrupted, gem_level 等
    └── trade_filters: price (chaos/divine/exalted)
    ↓
[search_trade] POST → Trade API → 返回搜索 URL
```

**关键文件:**

| 文件 | 用途 |
|------|------|
| `backend/app/services/trade_service.py` | 核心: LLM prompt、意图解析、查询构建、API 调用 |
| `backend/app/services/trade_stat_service.py` | 向量搜索: 7204 条 stats 的 ingest/embed/query |
| `backend/app/api/trade.py` | REST 端点: `/trade/search`, `/trade/admin/*` |
| `backend/app/models/build.py` | TradeStat ORM 模型 (pgvector Vector(1024)) |
| `backend/data/trade_stats_condensed.json` | 7204 条 stats 的原始数据 (ingest 用) |

### 三、Stat Groups 支持的查询类型

| 类型 | API 值 | 用途 | LLM prompt 示例 |
|------|--------|------|-----------------|
| AND | `"and"` | 全部匹配 (最常用) | "火抗和生命" |
| NOT | `"not"` | 排除 | "不要诅咒" |
| Count | `"count"` | 至少 N 条匹配 | "至少有2条抗性" |
| Weighted Sum | `"weight2"` | 加权评分 | "生命比抗性重要" |

Count 和 Weighted Sum 的 group 级别需要 `value: {min: N}` 字段。

### 四、PoE2 Trade API 踩坑记录

以下是实测验证的关键差异 (对比 PoE1)，避免重复踩坑:

**1. 过滤器分类不同**
- `ilvl` 和 `quality` → 在 PoE2 中属于 `type_filters` (PoE1 在 misc_filters)
- `lvl` (需求等级) → 正确位置是 `req_filters` (放 misc_filters 也能工作)
- `weapon_filters` / `armour_filters` → **PoE2 不存在**，统一用 `equipment_filters`
- `corrupted`, `gem_level` → `misc_filters`

**2. Stat ID 类型**
- Trade API **只接受** `explicit.*` 类型的 stat_id
- 向量搜索可能匹配到 `crafted.*`, `implicit.*`, `enchant.*`，必须归一化

**3. LLM 返回 null 问题**
- LLM 可能返回 `"stat_groups": null` 而非 `"stat_groups": []`
- `dict.get("key", default)` 在 key 存在但值为 None 时返回 None，不返回 default
- 必须用 `parsed.get("stat_groups") or []` 模式

**4. weight2 需要登录**
- 匿名请求使用 `weight2` 类型会返回 "Query is too complex"
- 需要认证后才能用加权评分功能

**5. 变量名冲突 (已修复)**
- `build_trade_query` 中外层 `filters = {}` 和循环内 `filters = []` 同名
- 已改为 `group_filters = []`

### 五、NAS 部署信息

| 项目 | 值 |
|------|------|
| NAS IP | 192.168.110.26 |
| SSH 端口 | 2212 |
| 用户 | skc |
| Docker 路径 | /usr/local/bin/docker |
| 项目路径 | /volume1/docker/PoE2LI |
| 容器名 | poe2li-backend |
| Git 仓库 | https://github.com/TangCuPaiGu233/PoE2LI.git |

**重要: 部署方式**

Docker 容器只挂载了 `/app/data` 卷 (读写)，代码 (`/app/app/`) 是烘焙在镜像里的。修改代码后不能只改 NAS 上的文件，必须:

```bash
# 1. 上传文件到 NAS
scp -P 2212 local_file.py skc@192.168.110.26:/volume1/docker/PoE2LI/...

# 2. docker cp 注入容器
/usr/local/bin/docker cp /volume1/docker/PoE2LI/backend/app/services/trade_service.py \
  poe2li-backend:/app/app/services/trade_service.py

# 3. 清除 pycache + 重启
/usr/local/bin/docker exec poe2li-backend find /app/app/services/__pycache__ -name "trade_service*" -delete
/usr/local/bin/docker restart poe2li-backend
```

或者重新构建镜像: `docker compose up -d --build`

**环境变量 (.env):**
- `LLM_BASE_URL` — SiliconFlow API (https://api.siliconflow.cn/v1)
- `LLM_API_KEY` — SiliconFlow API Key
- `LLM_MODEL` — **当前默认: mimo-v2.5**（此文档记录时为 deepseek-ai/DeepSeek-V4-Flash，后续已切换。以 CLAUDE.md Tech Stack 和运行环境为准）
- `HTTPS_PROXY` / `HTTP_PROXY` — NAS 代理 (http://192.168.110.26:7890)

### 六、向量搜索数据

- **总量**: 7204 条 Trade Stats (存储在 PostgreSQL pgvector 扩展中)
- **Embedding 模型**: BGE-M3 (1024维, SiliconFlow API)
- **匹配策略**: 英文查英文 (en→en)，相似度 0.94-0.96
- **最低阈值**: 0.50 (低于此不匹配)
- **Ingest 流程**: `trade_stats_condensed.json` → `ingest_trade_stats()` → pgvector

### 七、待完成事项

> **注**: 事项 #1（Trade 集成到聊天）**已在 Agent 层完成**。Chat Agent 的 ReAct/Orchestrator 运行时可通过 `trade_search` 工具执行交易搜索。以下为仍待完成的事项。

1. ~~**Trade 集成到 AI 聊天** — 已在 Agent 层实现。Chat Agent 可通过 `trade_search` 工具自动触发交易搜索，SSE 返回 `trade_result` 事件。~~ ✅
   - 后端 Agent 层 ✅（LLM 在 ReAct/Orchestrator 中自动调 trade_search）
   - 前端独立 Trade 搜索 UI 页 ❌（Sprint 2 待实现，见 `docs/Sprint-01-Backlog.md`）

2. **Docker 镜像重建** — 当前通过 docker cp 注入的代码修改在容器重建后会丢失。应在下次正式部署时 `docker compose up -d --build` 重建镜像。

3. **前端 Trade 搜索页面** — 目前 Trade 搜索只有 REST API (`/trade/search`)，前端还没有对应的搜索 UI 页面。

4. **weight2 (加权评分) 认证** — 需要 PoE2 OAuth 认证后才能使用加权评分功能。

5. **清理根目录 nul 文件** — Windows 特殊设备文件名 (0字节)，需要特殊方法删除。

### 八、测试验证状态

最后一次部署 (2026-06-08) 的全部 8 项测试通过:

| 测试 | 查询 | 结果 |
|------|------|------|
| 基础 AND | 加2召唤兽等级的项链 | 157 条 |
| AND + NOT | 稀有戒指+生命80+火抗30-不要诅咒 | 70 条 |
| 护甲面板 | 胸甲+护盾500+ | 155 条 |
| 武器面板 | 弓+物理DPS200+ | 119 条 |
| 多过滤器 | 项链+ilvl80+品质20+需求等级55以下 | 53 条 |
| 多词缀 AND | 稀有鞋+生命+火抗+移速 | 73 条 |
| AND + COUNT | 召唤+2+召唤加成项链+等级55以下 | 0 条 (市场无此物品) |
| Raw API | equipment_filters 验证 | 全部 200 OK |
