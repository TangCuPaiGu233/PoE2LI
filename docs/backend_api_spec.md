# PoE2LI Backend API Spec

> 供前端联调使用。Base URL：`http://localhost:8000`  
> 统一响应格式：成功时返回 JSON；失败时 FastAPI 返回标准 HTTP 错误码 + `{"detail": "..."}`。

---

## 1. 鉴权

| 范围 | 方式 |
|---|---|
| 公开接口 | 无需鉴权 |
| 需登录接口 | Header `Authorization: Bearer <JWT>` |

JWT 由 `/api/auth/callback/{provider}` 登录成功后下发。

---

## 2. Auth — OAuth 2.0

### 2.1 发起登录
```
GET /api/auth/login/{provider}
```
- `provider`: `google` | `github`
- 响应：
```json
{
  "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?..."
}
```

### 2.2 OAuth 回调
```
GET /api/auth/callback/{provider}?code=...&state=...
```
- 响应：
```json
{
  "access_token": "<JWT>",
  "token_type": "bearer",
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "display_name": "name",
    "avatar_url": "https://..."
  }
}
```

### 2.3 当前用户
```
GET /api/auth/me
Authorization: Bearer <JWT>
```
- 响应：
```json
{
  "id": "uuid",
  "email": "user@example.com",
  "display_name": "name",
  "avatar_url": "https://..."
}
```

### 2.4 登出
```
POST /api/auth/logout
Authorization: Bearer <JWT>
```
- 响应：
```json
{
  "message": "Logged out"
}
```

---

## 3. Pricing — 货币估价

> 无需鉴权。

### 3.1 获取汇率
```
GET /api/pricing/currency
```
- 响应：
```json
{
  "rates": {
    "chaos": 1.0,
    "divine": 150.0,
    "exalted": 10.0
  },
  "last_updated": "2025-01-01T00:00:00+00:00"
}
```

### 3.2 货币换算
```
POST /api/pricing/convert
```
- 请求体：
```json
{
  "currency": "divine",
  "amount": 2.5
}
```
- 响应：
```json
{
  "currency": "divine",
  "amount": 2.5,
  "chaos_equivalent": 375.0,
  "last_updated": "2025-01-01T00:00:00+00:00"
}
```

---

## 4. Chat — 多轮 SSE 问答

> 无需鉴权。

### 4.1 流式对话
```
POST /api/chat
```
- 请求体：
```json
{
  "messages": [
    {"role": "user", "content": "神圣石现在的市价如何？"}
  ],
  "stream": true
}
```
- 响应：`text/event-stream`
```
data: {"type":"text","content":"..."}

data: {"type":"done"}

: heartbeat
```
- `messages` 为多轮上下文数组，每项 `role` 支持 `user` / `assistant`。

---

## 5. Trade — 市集搜索

> 无需鉴权。

### 5.1 物品自动补全
```
GET /api/trade/items/suggest?q=项链&limit=15
```
- 响应：
```json
{
  "query": "项链",
  "limit": 15,
  "suggestions": ["金项链", "银项链", ...]
}
```

### 5.2 词缀自动补全
```
GET /api/trade/stats/suggest?q=召唤兽等级&limit=15
```
- 响应：
```json
{
  "query": "召唤兽等级",
  "limit": 15,
  "suggestions": ["+#% 召唤兽等级", ...]
}
```

### 5.3 自然语言搜索
```
POST /api/trade/search
```
- 请求体：
```json
{
  "query": "帮我找一条加2召唤兽等级的项链",
  "league": "Niko",
  "market": "cn"
}
```
- `market`: `cn` | `global`
- 响应：
```json
{
  "best_match": {
    "label": "+2 召唤兽等级 金项链",
    "url": "https://www.poewiki.net/...",
    "count": 12,
    "reason": "匹配到词缀：+#% 召唤兽等级"
  },
  "alternatives": [],
  "explanation": "已为你生成最优搜索条件。",
  "need_user_input": false
}
```

### 5.4 Admin: 词条入库
```
POST /api/trade/admin/ingest
```
- 后台任务，响应：
```json
{
  "status": "started",
  "message": "入库任务已启动（后台运行），预计 1-2 分钟完成",
  "json_path": "/app/data/trade_stats_condensed.json"
}
```

### 5.5 Admin: 入库状态
```
GET /api/trade/admin/ingest/status
```
- 响应：
```json
{
  "running": false,
  "result": {"ingested": 1234}
}
```

---

## 6. Filter — 智能过滤器

> 无需鉴权。

### 6.1 底材价格扫描（后台）
```
POST /api/filter/scan
```
- 请求体：
```json
{
  "market": "cn",
  "league": "Niko",
  "min_price_chaos": 50.0,
  "min_results": 3,
  "max_bases": null
}
```
- 响应：
```json
{
  "status": "started",
  "market": "cn",
  "league": "Niko"
}
```

### 6.2 扫描状态
```
GET /api/filter/scan/status
```
- 响应：
```json
{
  "running": false,
  "report": {
    "market": "cn",
    "league": "Niko",
    "high_value_count": 42,
    "bases": [...]
  },
  "error": null
}
```

### 6.3 查看底材列表
```
GET /api/filter/bases?market=cn&league=Niko&high_value_only=true
```
- 响应：
```json
{
  "batch_id": "2025-01-01T00:00:00",
  "scanned_at": "2025-01-01T00:00:00+00:00",
  "total": 42,
  "bases": [
    {
      "name_en": "Astral Plate",
      "name_cn": "星空板甲",
      "category": " armour.chest",
      "group_id": 1,
      "total_results": 15,
      "cheapest_chaos": 120.0,
      "median_chaos": 150.0,
      "is_high_value": true
    }
  ]
}
```

### 6.4 生成过滤器文件
```
POST /api/filter/generate
```
- 请求体：
```json
{
  "market": "cn",
  "league": "Niko",
  "item_level_min": 82
}
```
- 响应：
```json
{
  "status": "generated",
  "file_path": "/app/data/user_filters/流放漓_...filter",
  "message": "成功生成 1 个过滤器文件"
}
```

### 6.5 下载过滤器
```
GET /api/filter/download
```
- 响应：`application/octet-stream`，返回最新生成的 `.filter` 文件。

### 6.6 多品类价格扫描
```
POST /api/filter/price-scan
```
- 请求体：
```json
{
  "market": "cn",
  "league": "Niko",
  "categories": ["currency", "unique", "gem", "white_base"],
  "max_per_category": 50
}
```
- 响应：
```json
{
  "status": "started",
  "market": "cn",
  "league": "Niko"
}
```

### 6.7 价格扫描状态
```
GET /api/filter/price-scan/status
```

### 6.8 查看价格列表
```
GET /api/filter/prices?market=cn&league=Niko&category=unique&min_price=10
```

### 6.9 基于价格生成过滤器
```
POST /api/filter/generate-with-prices
```
- 请求体：
```json
{
  "market": "cn",
  "league": "Niko",
  "hide_threshold_chaos": 5.0,
  "item_level_min": 82
}
```

### 6.10 下载价格过滤器
```
GET /api/filter/download-price
```

### 6.11 过滤器配置
```
GET /api/filter/config
```
```json
{
  "min_price_chaos": 50.0,
  "min_results": 3,
  "item_level_min": 82,
  "market": "cn",
  "deprecated_uniques": []
}
```

```
POST /api/filter/config
```
- 请求体：
```json
{
  "min_price_chaos": 80.0,
  "min_results": 5
}
```

### 6.12 模板列表
```
GET /api/filter/templates
```
- 响应：
```json
{
  "templates": [
    {"name": "AI高价值底材.filter", "path": "/app/data/filters/..."},
    {"name": "AI价格过滤器.filter", "path": "/app/data/filters/..."}
  ]
}
```

---

## 7. Builds — 配装管理

> 无需鉴权。

### 7.1 提交配装
```
POST /api/builds
```
- 请求体：
```json
{
  "pob_code": "eNrtXF1...",
  "league": "Niko",
  "game_version": "0.2"
}
```
- 响应：
```json
{
  "id": 1,
  "status": "pending",
  "league": "Niko",
  "game_version": "0.2",
  "build": {
    "className": "Witch",
    "ascendClassName": "Lich",
    "level": 100
  }
}
```

### 7.2 配装列表
```
GET /api/builds
```
- 响应：
```json
[
  {
    "id": 1,
    "status": "done",
    "league": "Niko",
    "game_version": "0.2",
    "build": { ... }
  }
]
```

### 7.3 配装详情
```
GET /api/builds/{build_id}
```
- 响应：
```json
{
  "id": 1,
  "status": "done",
  "league": "Niko",
  "game_version": "0.2",
  "build": { ... },
  "treeSpecs": [...],
  "skillSets": [...],
  "items": [...],
  "playerStats": {...},
  "homework": {
    "core_idea": "...",
    "core_items": [...],
    "budget_alternatives": [...],
    "talent_highlights": [...],
    "strength_review": "..."
  },
  "created_at": "2025-01-01T00:00:00+00:00"
}
```

### 7.4 配装问答
```
POST /api/builds/{build_id}/chat
```
- 请求体：
```json
{
  "question": "这个build的毕业装备是什么？"
}
```
- 响应：
```json
{
  "answer": "根据配装分析，毕业装备包括...",
  "context_used": ["Build Data", "Homework", "RAG Knowledge"]
}
```

### 7.5 纯解码（不存库）
```
POST /api/builds/decode
```
- 请求体：
```json
{
  "pob_code": "eNrtXF1..."
}
```
- 响应同 DecodeResponse。

### 7.6 生成作业
```
POST /api/builds/homework
```
- 请求体：
```json
{
  "pob_code": "eNrtXF1..."
}
```
- 响应：
```json
{
  "core_idea": "...",
  "core_items": [...],
  "budget_alternatives": [...],
  "talent_highlights": [...],
  "strength_review": "..."
}
```

### 7.7 Admin: 批量导入
```
POST /api/admin/import
Authorization: Bearer <JWT>
```
- 请求体：
```json
{
  "codes": ["eNrt...", "eNrt..."],
  "league": "Niko",
  "game_version": "0.2"
}
```
- 响应：
```json
[
  {
    "id": 1,
    "status": "pending",
    "league": "Niko",
    "game_version": "0.2",
    "build": { ... }
  }
]
```

---

## 8. Knowledge / QA — 知识库问答

> 无需鉴权。

### 8.1 百科问答
```
POST /api/knowledge/ask
```
- 请求体：
```json
{
  "question": "神圣石的作用是什么？",
  "top_k": 5,
  "league": "Niko",
  "game_version": "0.2"
}
```
- 响应：
```json
{
  "answer": "神圣石是...",
  "sources": [
    {
      "type": "item",
      "similarity": 0.92,
      "preview": "神圣石是一种通货..."
    }
  ]
}
```

### 8.2 推荐问答
```
POST /api/knowledge/recommend
```
- 请求体：
```json
{
  "question": "召唤师用什么武器好？",
  "pob_code": "eNrt...",
  "candidates": ["魔棒", "法杖", "匕首"],
  "league": "Niko"
}
```
- 响应：
```json
{
  "intent": "recommend",
  "resolved": {"entities": ["魔棒", "法杖"]},
  "ranking": [
    {
      "name": "魔棒",
      "fit_score": 95,
      "pros": ["高法术伤害", "适合召唤师"],
      "cons": ["攻速慢"],
      "synergy": "与召唤兽技能完美配合",
      "verdict": "首选",
      "sources": []
    }
  ],
  "best_pick": "魔棒",
  "summary": "综合来看，魔棒最适合...",
  "disclaimer": "基于 poe2db 当前赛季数据。",
  "cached": false
}
```

---

## 9. Entities — 实体与图标

> 无需鉴权。

### 9.1 实体识别
```
POST /api/entities/mentions
```
- 请求体：
```json
{
  "text": "我想用神圣石换一个魔棒"
}
```
- 响应：
```json
{
  "mentions": [
    {"name": "神圣石", "type": "currency", "start": 3, "end": 6},
    {"name": "魔棒", "type": "item", "start": 10, "end": 12}
  ]
}
```

### 9.2 图标 URL
```
GET /api/entities/icon?name=神圣石
```
- 响应：
```json
{
  "name_en": "Divine Orb",
  "type": "currency",
  "icon_url": "https://.../Divine Orb.png"
}
```

### 9.3 图标图片
```
GET /api/entities/icon-image?name=神圣石
```
- 响应：`image/png` 或 `image/webp`，带 `Cache-Control: public, max-age=604800`。

### 9.4 Tooltip
```
GET /api/entities/tooltip?name=神圣石&lang=cn
```
- 响应：
```json
{
  "name": "神圣石",
  "name_en": "Divine Orb",
  "type": "currency",
  "description": "重铸一个稀有物品，...",
  "icon_url": "https://..."
}
```

### 9.5 目录状态
```
GET /api/entities/catalog-status
```
- 响应：
```json
{
  "total_entities": 1234,
  "with_icon": 1200,
  "last_updated": "2025-01-01T00:00:00+00:00"
}
```

---

## 10. 通用错误码

| HTTP 状态码 | 含义 |
|---|---|
| 400 | 参数错误 / PoB 解码失败 |
| 401 | 未登录或 Token 失效 |
| 404 | 资源不存在 |
| 500 | 服务端异常 |

---

## 11. 环境变量（后端需配置）

| 变量 | 说明 |
|---|---|
| `LLM_BASE_URL` | LLM API 地址 |
| `LLM_API_KEY` | LLM API Key |
| `LLM_MODEL` | 模型名，默认 `deepseek-ai/DeepSeek-V4-Flash` |
| `SECRET_KEY` | JWT 签名密钥 |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Google OAuth |
| `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` | GitHub OAuth |
| `REDIS_URL` | Redis 连接串 |
| `CELERY_BROKER_URL` | Celery Broker |
| `CELERY_RESULT_BACKEND` | Celery 结果后端 |
