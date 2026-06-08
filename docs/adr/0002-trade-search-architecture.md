# ADR-0002: Trade 智能搜索 — 服务端方案

## Status

Accepted (2026-06-08)

## Context

### 需求

用户在 AI 聊天中用自然语言描述装备需求（如"帮我找一条加2召唤兽等级的项链"），AI 解析后生成 PoE2 官方 Trade 搜索链接，用户点击直接看到搜索结果。

### Trade 搜索机制（已验证）

PoE2 Trade 站（`pathofexile.com/trade2`）的工作流程：

1. **POST** 搜索条件 JSON 到 Trade API → 服务端生成搜索 ID（如 `ve58Z9EDTE`）
2. 用 ID 拼 URL → `https://www.pathofexile.com/trade2/search/poe2/{league}/{id}`
3. 搜索 ID 是**服务端生成的随机标识符**（非编码过的查询参数），有过期时间
4. `?q=` 参数方式 **已验证不可行** — Trade 站不接受客户端编码的查询

### 方案选型

| 方案 | 优势 | 劣势 | 结论 |
|------|------|------|------|
| **服务端直接调 API** | 用户体验好（点击直达），实现简单 | 单 IP 集中请求，Cloudflare 风险 | **采用（当前）** |
| `?q=` URL 参数 | 无需 API 调用 | 已验证不可行 | ❌ 排除 |
| 浏览器插件 | IP 分散 + 页面增强 | 需用户安装，开发周期长 | 远期方案 |

## Decision

### 服务端直接调 Trade API

后端直接 POST 到 Trade API 获取搜索 ID，拼 URL 返回给前端。

```
用户聊天输入 "帮我找个加2召唤兽等级的项链"
  → AI 解析意图 → 结构化查询参数
  → 查询 stat ID 字典 → 匹配 Trade 词缀 ID
  → 后端 POST 到 Trade API → 拿到 search_id
  → 拼 URL 返回前端 → 用户点击直达搜索结果
```

**Cloudflare 应对**：初期用户量小时，服务端 HTTP 请求配合合理的频率控制即可。若被拦截，可升级到 Playwright 无头浏览器（真实 Chromium 环境可过 Cloudflare）。

**IP 集中风险管控**：
- 服务端限流（每用户每分钟 ≤3 次搜索）
- 搜索缓存（相同条件 5 分钟内复用 search_id）
- 用户量增长后迁移到浏览器插件方案

## 技术实现

### API 设计

```
# 前端调用：AI 解析意图 + 获取 Trade URL
POST /api/trade/search
  Body: { "query": "加2召唤兽等级的项链", "league": "Standard" }
  Response: {
    "trade_url": "https://www.pathofexile.com/trade2/search/poe2/Standard/ve58Z9EDTE",
    "intent_summary": "项链 | +2 召唤兽技能等级(≥2) | 精魂(≥20)",
    "filters": {
      "type": "Amulet",
      "stats": [
        { "text": "+# to Level of all Minion Skill Gems", "min": 2 },
        { "text": "+# to Spirit", "min": 20 }
      ]
    },
    "expires_at": "2026-06-08T12:30:00Z"
  }
```

### 后端流程

```python
# backend/app/services/trade_service.py

class TradeService:
    """PoE2 Trade search integration."""

    TRADE_BASE = "https://www.pathofexile.com/trade2/search/poe2"
    TRADE_API = "https://www.pathofexile.com/api/trade2/search/poe2"

    async def search(self, query: str, league: str) -> TradeSearchResult:
        # 1. AI 解析自然语言 → 结构化查询（装备类型 + 词缀条件）
        structured = await self._parse_intent(query)

        # 2. 从 stat ID 字典查找匹配的词缀 ID
        trade_query = await self._build_trade_query(structured)

        # 3. 检查 Redis 缓存
        cache_key = f"trade:{league}:{hash(json.dumps(trade_query, sort_keys=True))}"
        cached = await redis.get(cache_key)
        if cached:
            return TradeSearchResult(url=cached, ...)

        # 4. POST 到 Trade API
        resp = await httpx.post(
            f"{self.TRADE_API}/{league}",
            json=trade_query,
            headers={"User-Agent": "...", "Accept": "application/json"},
        )
        search_id = resp.json()["id"]

        # 5. 拼 URL + 缓存
        url = f"{self.TRADE_BASE}/{league}/{search_id}"
        await redis.setex(cache_key, 300, url)  # 5 min TTL

        return TradeSearchResult(url=url, intent_summary=..., ...)
```

### Stat ID 字典

Trade API 的词缀 ID（如 `explicit.stat_1940865751` = "+# to maximum Life"）是动态的：

- **数据源**：`https://www.pathofexile.com/api/trade2/data/poe2/Standard`（Trade 站加载时请求的静态端点）
- **存储**：PostgreSQL `trade_stats` 表
- **更新策略**：Celery beat 每天拉取一次，增量更新
- **AI 使用**：AI 解析用户意图时，从数据库查询匹配的 stat ID，而非硬编码
- **版本感知**：stat ID 可能随赛季变化，需带 `league` + `game_version` 过滤

### 意图解析 Prompt

AI 接收用户自然语言，输出结构化 JSON：

```json
{
  "item_type": "Amulet",
  "required_stats": [
    { "stat_text": "+# to Level of all Minion Skill Gems", "min": 2 },
    { "stat_text": "+# to Spirit", "min": 20 }
  ],
  "optional_stats": [
    { "stat_text": "+#% to Fire Resistance", "min": 20 }
  ],
  "price_range": null
}
```

后端再用这个结构化结果去查 stat ID 字典，构造 Trade API 的 JSON body。

## Consequences

- **Positive**：无需浏览器插件，当前网站即可实现 Trade 搜索
- **Positive**：用户体验直接——AI 回复中嵌入可点击链接
- **Positive**：初期实现简单，快速验证需求
- **Negative**：Cloudflare 可能拦截服务端请求（需实测验证）
- **Negative**：单 IP 集中请求，用户量大后有封禁风险
- **Mitigation**：限流 + 缓存 + 远期迁移插件方案

## Future: 浏览器插件（M7）

当用户量增长到服务端方案不可持续时，推出浏览器插件：

- 插件用用户自己的浏览器和 IP 调 Trade API → 零封禁风险
- 同时带来 pobb.in 一键导入、Trade 站 Overlay、快捷呼出等增值功能
- 后端 API 不变，只是 Trade API 调用方从后端换到插件前端
