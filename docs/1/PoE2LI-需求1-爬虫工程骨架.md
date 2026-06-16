# PoE2LI 需求1 爬虫工程骨架（poe2db 全量实体+关系重建）

> 配套文档：`PoE2LI-解决思路-当前需求.md` 第 2 节
> 目标：给出可直接落地的目录结构、配置文件骨架、关键代码骨架，照此搭起 Discovery → Detail Parse → Edge Normalize → 灌库 的完整管线。
> 技术栈：Python 3.11 + aiohttp（异步爬取）+ BeautifulSoup/selectolax（解析）+ SQLAlchemy（灌库）+ PyYAML（配置）

---

## 1. 目录结构

```
poe2_crawler/
├── README.md
├── pyproject.toml                  # 依赖声明
├── config/
│   ├── entity_types.yaml           # 实体类型 → 索引页/URL前缀/parser 配置
│   ├── field_relation_map.yaml     # 字段名 → relation 映射（可增量补充）
│   ├── selectors/                  # 每类实体的 CSS/XPath 选择器配置
│   │   ├── skill.yaml
│   │   ├── ascendancy.yaml
│   │   ├── unique.yaml
│   │   ├── base_item.yaml
│   │   └── ...
│   └── settings.yaml               # 全局：并发数、限速、UA、缓存目录、DB连接
├── crawler/
│   ├── __init__.py
│   ├── fetcher.py                  # 异步抓取 + 缓存 + 限速 + 重试
│   ├── cache.py                    # 本地 html 缓存（url -> 文件）
│   └── ratelimit.py                # 令牌桶限速
├── discovery/
│   ├── __init__.py
│   └── discover.py                 # 阶段A：从索引页发现全部实体 URL
├── parser/
│   ├── __init__.py
│   ├── base_parser.py              # parser 基类（配置驱动）
│   ├── registry.py                 # entity_type -> parser 注册表
│   └── parsers/                    # 各类型专用 parser
│       ├── skill_parser.py
│       ├── ascendancy_parser.py
│       └── ...
├── normalize/
│   ├── __init__.py
│   ├── url_to_id.py                # URL → canonical entity_id 映射
│   └── edge_normalizer.py          # 阶段C：原始边 → kb_edges
├── loader/
│   ├── __init__.py
│   ├── models.py                   # SQLAlchemy ORM：kb_entities/kb_edges/aliases
│   ├── upsert.py                   # 幂等灌入（影子表）
│   └── switch.py                   # 影子表原子切换
├── pipeline/
│   ├── __init__.py
│   └── run.py                      # 主编排：A→B→C→灌库→校验
├── data/
│   ├── cache/                      # html 缓存
│   ├── entity_urls.jsonl           # 阶段A产物
│   ├── entities.jsonl              # 阶段B产物（实体）
│   ├── raw_edges.jsonl             # 阶段B产物（原始边）
│   └── unmapped_fields.log         # 未识别字段日志（反哺 field_relation_map）
└── tests/
    ├── fixtures/                   # 离线 html 样本
    └── test_parsers.py
```

---

## 2. 关键配置文件骨架

### 2.1 `config/entity_types.yaml`

```yaml
# 每个实体类型：索引入口 + URL 前缀 + 用哪个 parser
entity_types:
  ascendancy:
    index_urls:
      - "https://poe2db.tw/cn/Ascendancy_classes"
    url_prefix: "/cn/"          # 详情页 URL 特征
    parser: ascendancy_parser
  class:
    index_urls:
      - "https://poe2db.tw/cn/Classes"
    parser: class_parser
  skill:
    index_urls:
      - "https://poe2db.tw/cn/Skill_Gems"
    parser: skill_parser
  support:
    index_urls:
      - "https://poe2db.tw/cn/Support_Gems"
    parser: support_parser
  unique:
    index_urls:
      - "https://poe2db.tw/cn/Unique_items"
    parser: unique_parser
  base_item:
    index_urls:
      - "https://poe2db.tw/cn/Item"
    parser: base_item_parser
  mod:
    index_urls:
      - "https://poe2db.tw/cn/Modifiers"
    parser: mod_parser
  passive:
    index_urls:
      - "https://poe2db.tw/cn/Passive_Skill"
    parser: passive_parser
  currency:
    index_urls:
      - "https://poe2db.tw/cn/Currency"
    parser: generic_parser
  flask:
    index_urls:
      - "https://poe2db.tw/cn/Flask"
    parser: generic_parser
  monster:
    index_urls:
      - "https://poe2db.tw/cn/Monster"
    parser: generic_parser
  tag:
    index_urls:
      - "https://poe2db.tw/cn/Gem_Tags"
    parser: generic_parser
# 说明：index_urls 是“类型清单页”，Discovery 从这里抓出该类型下全部详情页链接。
# 真实 URL 以 poe2db 实际页面为准，跑通后回填校正。
```

### 2.2 `config/field_relation_map.yaml`

```yaml
# 页面字段名（或区块标题）→ 标准 relation
# 未命中的字段一律落 related_to 并写 unmapped_fields.log，定期人工归类升级
field_relation_map:
  "Supported By":    supports
  "辅助":            supports
  "Weapon":          requires_weapon
  "需要武器":        requires_weapon
  "Base Item":       based_on
  "基底物品":        based_on
  "Class":           belongs_to
  "职业":            belongs_to
  "Implicit":        has_implicit
  "固定属性":        has_implicit
  "Tags":            has_tag
  "标签":            has_tag
  "Drops From":      drops_from
  "掉落来源":        drops_from
  "Grants":          grants
default_relation: related_to     # 保底，绝不丢边
```

### 2.3 `config/selectors/skill.yaml`（示例：选择器配置驱动）

```yaml
# 解析规则集中在配置，poe2db 改版只改这里，不动代码
entity_type: skill
fields:
  name_cn:   { css: "h1.itemName .lc",  attr: text }
  name_en:   { css: "h1.itemName",      attr: "data-en" }
  tags:      { css: ".gem-tags a",      attr: text, multi: true }
  level_req: { css: ".requirements .level", attr: text }
# 页面内指向其他实体的链接区块（产出 raw_edges）
link_blocks:
  - field_name: "Supported By"
    css: ".supported-by a"
    dst_attr: href
  - field_name: "Weapon"
    css: ".weapon-restriction a"
    dst_attr: href
  - field_name: "Tags"
    css: ".gem-tags a"
    dst_attr: href
```

### 2.4 `config/settings.yaml`

```yaml
crawl:
  concurrency: 8            # 并发协程数
  rate_per_sec: 5          # 每秒最多请求（礼貌爬取）
  timeout_sec: 20
  max_retries: 3
  user_agent: "PoE2LI-crawler/1.0 (contact: your-email)"
  cache_dir: "data/cache"
db:
  url: "sqlite:///poe2_kb.db"   # 生产换成实际连接串
  shadow_suffix: "_new"         # 影子表后缀
```

---

## 3. 关键代码骨架

### 3.1 `crawler/fetcher.py` — 异步抓取 + 缓存 + 限速 + 重试

```python
import asyncio, aiohttp, hashlib, os
from .ratelimit import RateLimiter
from .cache import HtmlCache

class Fetcher:
    def __init__(self, settings):
        self.sem = asyncio.Semaphore(settings["concurrency"])
        self.limiter = RateLimiter(settings["rate_per_sec"])
        self.cache = HtmlCache(settings["cache_dir"])
        self.timeout = aiohttp.ClientTimeout(total=settings["timeout_sec"])
        self.headers = {"User-Agent": settings["user_agent"]}
        self.max_retries = settings["max_retries"]

    async def fetch(self, session, url):
        # 1) 命中缓存直接返回（重跑只解析不重爬）
        cached = self.cache.get(url)
        if cached is not None:
            return cached
        # 2) 限速 + 并发控制 + 重试
        async with self.sem:
            for attempt in range(self.max_retries):
                await self.limiter.acquire()
                try:
                    async with session.get(url, headers=self.headers,
                                           timeout=self.timeout) as resp:
                        resp.raise_for_status()
                        html = await resp.text()
                        self.cache.put(url, html)
                        return html
                except Exception as e:
                    if attempt == self.max_retries - 1:
                        print(f"[FAIL] {url}: {e}")
                        return None
                    await asyncio.sleep(2 ** attempt)  # 指数退避

    async def fetch_all(self, urls):
        async with aiohttp.ClientSession() as session:
            tasks = [self.fetch(session, u) for u in urls]
            return await asyncio.gather(*tasks)
```

### 3.2 `discovery/discover.py` — 阶段A：发现全部实体 URL

```python
import json, yaml
from bs4 import BeautifulSoup

async def discover(fetcher, entity_types_cfg, out_path="data/entity_urls.jsonl"):
    """从每个类型的索引页抓出该类型下全部详情页 URL。"""
    with open(out_path, "w", encoding="utf-8") as fout:
        for etype, cfg in entity_types_cfg["entity_types"].items():
            for index_url in cfg["index_urls"]:
                html = await fetcher.fetch_one(index_url)
                if not html:
                    continue
                soup = BeautifulSoup(html, "html.parser")
                # 索引页里的详情链接（按 url_prefix 过滤，去重）
                seen = set()
                for a in soup.select("a[href]"):
                    href = a["href"]
                    if cfg.get("url_prefix", "/cn/") in href and href not in seen:
                        seen.add(href)
                        fout.write(json.dumps({
                            "entity_type": etype,
                            "url": _abs(href),
                            "name_cn": a.get_text(strip=True),
                        }, ensure_ascii=False) + "\n")
    # 产物：entity_urls.jsonl —— 全量清单，替代旧 NLP 词典
```

### 3.3 `parser/base_parser.py` — 配置驱动解析

```python
from bs4 import BeautifulSoup

class BaseParser:
    """根据 selectors/<type>.yaml 配置解析详情页，输出 (entity, raw_edges)。"""
    def __init__(self, selector_cfg):
        self.cfg = selector_cfg

    def parse(self, html, url, entity_type):
        soup = BeautifulSoup(html, "html.parser")
        # 1) 解析实体自身字段
        entity = {"url": url, "entity_type": entity_type, "attributes": {}}
        for fname, rule in self.cfg.get("fields", {}).items():
            val = self._extract(soup, rule)
            if fname in ("name_cn", "name_en"):
                entity[fname] = val
            else:
                entity["attributes"][fname] = val
        # 2) 解析指向其它实体的链接 → 原始边
        raw_edges = []
        for block in self.cfg.get("link_blocks", []):
            for el in soup.select(block["css"]):
                dst = el.get(block["dst_attr"])
                if dst:
                    raw_edges.append({
                        "src_url": url,
                        "dst_url": _abs(dst),
                        "field_name": block["field_name"],
                    })
        return entity, raw_edges

    def _extract(self, soup, rule):
        els = soup.select(rule["css"])
        if not els:
            return None
        if rule.get("multi"):
            return [self._val(e, rule) for e in els]
        return self._val(els[0], rule)

    def _val(self, el, rule):
        return el.get_text(strip=True) if rule["attr"] == "text" else el.get(rule["attr"])
```

### 3.4 `normalize/edge_normalizer.py` — 阶段C：原始边归一

```python
import yaml, json

class EdgeNormalizer:
    def __init__(self, field_map_path, url_to_id):
        cfg = yaml.safe_load(open(field_map_path, encoding="utf-8"))
        self.field_map = cfg["field_relation_map"]
        self.default = cfg["default_relation"]
        self.url_to_id = url_to_id            # dict: url -> entity_id
        self.unmapped_log = open("data/unmapped_fields.log", "a", encoding="utf-8")

    def normalize(self, raw_edge):
        src = self.url_to_id.get(raw_edge["src_url"])
        dst = self.url_to_id.get(raw_edge["dst_url"])
        if not src or not dst:
            return None                        # 跨页未解析到实体，跳过
        relation = self.field_map.get(raw_edge["field_name"])
        if relation is None:
            relation = self.default            # 保底 related_to
            self.unmapped_log.write(raw_edge["field_name"] + "\n")  # 反哺
        return {
            "src_id": src, "dst_id": dst, "relation": relation,
            "evidence_type": "official", "weight": 1.0,
            "source": "poe2db",
        }
```

### 3.5 `normalize/url_to_id.py` — canonical id 规则

```python
import re

def make_entity_id(entity_type, name_en):
    slug = re.sub(r"[^a-z0-9]+", "_", (name_en or "").lower()).strip("_")
    return f"{entity_type}:{slug}"

def build_url_to_id(entities):
    """entities: 阶段B产出的实体列表，建立 url -> entity_id 映射。"""
    mapping = {}
    for e in entities:
        eid = make_entity_id(e["entity_type"], e.get("name_en") or e.get("name_cn"))
        e["entity_id"] = eid
        mapping[e["url"]] = eid
    return mapping
```

### 3.6 `loader/models.py` — ORM（影子表友好）

```python
from sqlalchemy import Column, String, Float, Integer, JSON, UniqueConstraint
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class KbEntity(Base):
    __tablename__ = "kb_entities"
    entity_id = Column(String, primary_key=True)
    name_en = Column(String); name_cn = Column(String); name_tw = Column(String)
    entity_type = Column(String, index=True)
    attributes = Column(JSON)
    league = Column(String); game_version = Column(String)

class KbEdge(Base):
    __tablename__ = "kb_edges"
    id = Column(Integer, primary_key=True, autoincrement=True)
    src_id = Column(String, index=True)
    dst_id = Column(String, index=True)
    relation = Column(String)
    evidence_type = Column(String)   # official / experience
    weight = Column(Float, default=1.0)
    source = Column(String); season = Column(String)
    __table_args__ = (UniqueConstraint("src_id", "relation", "dst_id"),)

class KbEntityAlias(Base):
    __tablename__ = "kb_entity_aliases"
    id = Column(Integer, primary_key=True, autoincrement=True)
    alias = Column(String); entity_id = Column(String, index=True)
    lang = Column(String); source = Column(String); priority = Column(Integer)
    __table_args__ = (UniqueConstraint("alias", "lang"),)
```

### 3.7 `pipeline/run.py` — 主编排

```python
import asyncio, json, yaml

async def main():
    settings = yaml.safe_load(open("config/settings.yaml"))
    etypes   = yaml.safe_load(open("config/entity_types.yaml"))
    fetcher  = Fetcher(settings["crawl"])

    # 阶段A：发现全部实体 URL
    await discover(fetcher, etypes)

    # 阶段B：逐 URL 解析 → 实体 + 原始边
    urls = [json.loads(l) for l in open("data/entity_urls.jsonl", encoding="utf-8")]
    entities, raw_edges = [], []
    htmls = await fetcher.fetch_all([u["url"] for u in urls])
    for meta, html in zip(urls, htmls):
        if not html: continue
        parser = get_parser(meta["entity_type"])     # registry 按类型取
        ent, edges = parser.parse(html, meta["url"], meta["entity_type"])
        entities.append(ent); raw_edges.extend(edges)

    # 阶段C：建立 url->id，归一边
    url_to_id = build_url_to_id(entities)
    normalizer = EdgeNormalizer("config/field_relation_map.yaml", url_to_id)
    edges = [e for e in (normalizer.normalize(r) for r in raw_edges) if e]

    # 灌入影子表 → 校验 → 原子切换
    upsert_to_shadow(entities, edges, settings["db"])
    if validate_shadow(settings["db"]):           # 实体数/边数/抽样/eval基线
        atomic_switch(settings["db"])
    else:
        print("[ABORT] 校验未通过，保留旧表")

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 4. 落地检查清单（搭起来后逐项验证）

- [ ] `entity_types.yaml` 里每个类型的 index_urls 真实可达（先手动开一个页面确认）
- [ ] Discovery 跑完 `entity_urls.jsonl` 行数 ≈ 游戏内该类型数量（如 ascendancy 应 ≈ 36）
- [ ] 抽 3 个详情页人工核对 parser 解析字段正确
- [ ] `unmapped_fields.log` 定期 review，把高频字段升级进 `field_relation_map.yaml`
- [ ] 影子表校验脚本：实体数、边数、关键实体存在性（女猎手/行者/猎巫人）、跑一遍 eval 对比基线
- [ ] 缓存生效：第二次跑只解析不重爬（看日志无网络请求）

---

## 5. 与解决思路文档的对应关系

| 本骨架模块 | 解决思路文档章节 |
|------------|------------------|
| discovery/ | 2.2 阶段A 实体清单发现 |
| parser/    | 2.2 阶段B 实体详情解析 |
| normalize/ | 2.2 阶段C 关系归一 + 2.3 工程要点 |
| loader/switch.py | 2.3 影子表原子切换 + 6.2 迁移顺序 |
| field_relation_map + unmapped_fields.log | 2.2 related_to 保底 + 评审 Q4 |
