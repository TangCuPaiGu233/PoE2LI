# 技术架构评估报告

**评估者**：远岫（技术架构师）
**评估时间**：项目时间 第 0 天 05:27 — 06:30
**状态**：初稿 / 待朝露审阅

---

## 一、评估范围

- CLAUDE.md（项目主说明文档）、CONTEXT.md（领域词汇表）
- `backend/app/` 全量代码结构（API 层 / Core 层 / 服务层 / Orchestrator 层 / Skills 层 / Tasks 层）
- `docs/adr/` 全部 3 份架构决策记录
- `assessments/data-ops-assessment.md`（现有数据运维评估）
- `backend/app/main.py`、`database.py` 等关键基础设施文件

---

## 二、架构总览评分

| 维度 | 评分 | 说明 |
|------|------|------|
| **分层清晰度** | ★★★★☆ | 三层 Agent 架构（Main Agent → Sub-Agent → Tool）职责明确 |
| **文档完备性** | ★★★★☆ | CLAUDE.md 是极好的单源 truth，ADR 覆盖关键决策 |
| **模块内聚** | ★★★★☆ | services/ 各模块边界清晰，单一职责 |
| **模块耦合** | ★★★☆☆ | 两个运行时并行维护有隐形成本 |
| **可测试性** | ★☆☆☆☆ | 未见测试基础设施，这是当前最大短板 |
| **可观测性** | ★★★☆☆ | Langfuse 覆盖 LLM 层面，但应用级监控缺失 |
| **部署成熟度** | ★★★☆☆ | Docker Compose 完整，但生产环境有配置盲区 |
| **数据管道** | ★★☆☆☆ | 全手动流程，多语言数据不完整 |

---

## 三、架构合理性分析

### 3.1 做得好的地方

**1. AI/Code 职责分离到位**
CLAUDE.md 反复强调的核心原则："AI handles routing, understanding, and synthesis — tools handle precise execution." 从代码看确实贯彻了。`chat_tools.py` 里的工具都是确定的、schema-validated 的代码逻辑，没有把智能推给 AI 去猜。这个设计决策保住了系统的下限。

**2. Entity Catalog 模式**
ADR-0003 描述的 Entity Catalog（materialized JSON + O(1) 运行时查找）是个好模式。把离线构建和在线查询分离，避免了每次请求都走 KB 查询。`entity_catalog_service.py` 加载一次 JSON 就能干活，没有 DB 依赖。这个思路值得在未来类似的"静态知识 + 动态查询"场景中复用。

**3. Trade 搜索的服务端缓存策略**
ADR-0002 设计的限流 + 5 分钟 Redis 缓存 + 远期迁移到浏览器插件的演进路径，务实且可操作。没有上来就搞复杂方案，"够用就好，但接口要留余地"。

**4. 游戏数据管线的完整设计**
从 GGPK → JSON → PostgreSQL → knowledge graph，整个数据管线虽然手动执行，但设计上是完整的。24 张游戏表 + 549K 关系边 + BFS 遍历，底层数据基建扎实。

**5. 双运行时设计保留扩展弹性**
Legacy ReAct 和 Orchestrator 两个运行时共享同一套 tool executors（`chat_tools.py`），这是正确的做法——业务逻辑不重复。Orchestrator 的 parallel dispatch + synthesis 为未来复杂场景留了空间。

**6. 中文 PoE2 领域的专业知识扎实**
从 `扭曲项链` vs `畸变项链` 的消歧、到国服译名、踩蘑菇技能名、poe2db 数据爬取——这个项目对中文 PoE2 社区的生态理解很深，数据资产的积累已经形成了护城河。

### 3.2 值得关注的问题

**1. 两个运行时并存 → 维护成本翻倍**
当前 `CHAT_RUNTIME=legacy` 是生产默认值，orchestrator 需要显式 opt-in。这意味着：
- 两条 code path 都需要测试、都需要维护
- 新功能要兼容两套流式响应格式（SSE events）
- 修复 bug 可能只修了一条路径

**建议**：如果 orchestrator 没有明确的 P0 需求，考虑在短期内统一到 legacy ReAct，或者反过来把 orchestrator 设为默认并 deprecate legacy。二选一，别背两座山。

**2. 测试基础设施缺失（P0 问题）**
整个代码仓库我没有看到 `tests/` 目录、pytest 配置、或者任何 CI 测试流程。对于一个已经有一定规模的 AI + 数据处理项目，没有测试是最高风险项——AI 输出是非确定性的，回归 bug 会悄无声息地进来。

**建议**：
- 至少为工具层（`chat_tools.py` 中的每个 tool）加单元测试
- 为 PoB decode 加 golden data 测试（用已知正确的 PoB code 验证解析结果）
- 为实体解析（`entity_resolver.py`）加别名映射测试
- API 层加端到端 smoke test

**3. Skills 模块与 Orchestrator 的关系模糊**
CLAUDE.md 说 skills 模块 "not the main dispatcher anymore"，但代码里 `skills/` 仍然存在，被 orchestrator 用于 synthesis system prompts。而 `skills/router.py` 的 `get_skill()` 函数实际上成了 prompt 片段提供者，不是路由器。

这不是 bug，但命名和实际职责已经脱节。新开发的同学会困惑。

**4. SQLite → PostgreSQL 的双轨开发模式**
`database.py` 里有 `SQLiteVector` 的 monkey-patch，把 pgvector 的 Vector 类型替换成 JSON 来在本地开发。这意味着：
- 涉及向量操作的代码在本地无法真正测试
- 生产才暴露的问题只能在部署后发现
- 开发环境和生产环境的行为不一致

**短期建议**：本地开发也可以跑 PostgreSQL（docker-compose 里已经有 postgres 服务），把默认开发配置指向 pg 而不是 SQLite。

**5. CORS 全开**

```python
allow_origins=["*"]
```

生产环境应该限制具体域名。

**6. 数据管道全手动，多语言不完整**
data-ops-assessment.md 已经详细记录了：TC 数据缺失 70%+、game_relations.json 不存在。这不是架构问题，是数据运维的运营问题，但直接影响系统可用性——繁体中文用户进来 AI 问答基本不可用。

---

## 四、技术债清单

按优先级排列：

### P0 — 必须修复

| # | 项目 | 影响 | 建议 |
|---|------|------|------|
| T-01 | **无测试基础设施** | 每次改代码都是盲改，回归风险高 | 引入 pytest + golden data 测试 + smoke test |
| T-02 | **TC 数据缺失 70%+** | 繁体用户核心功能不可用 | 修复 `export_en_tc.py` 配置，补跑 TC 导出 |

### P1 — 短期（本轮冲刺）

| # | 项目 | 影响 | 建议 |
|---|------|------|------|
| T-03 | **双运行时维护成本** | 每个 chat 功能改动需兼顾两套 | 选定一个默认运行时，明确另一个的 deprecation 计划 |
| T-04 | **Skills/ 模块命名误导** | 新成员入职困惑 | 重命名为 `synthesis_prompts/` 或明确职责边界 |
| T-05 | **开发/生产数据库不一致** | 本地测试覆盖不到 pgvector 行为 | 本地开发默认使用 docker-compose 的 PostgreSQL |
| T-06 | **数据管道自动化** | 版本更新时人工操作易遗漏 | 编排为可重复工作流（Makefile / shell script） |
| T-07 | **Celery Beat 生产配置确认** | 定时价格扫描可能不运行 | 验证 `docker-compose.tencent.yml` 中 celery_beat 配置 |

### P2 — 中期改进

| # | 项目 | 影响 | 建议 |
|---|------|------|------|
| T-08 | **CORS 全开** | 安全风险 | 生产环境限制具体域名 |
| T-09 | **API 无版本前缀** | 无法平滑升级 API | 引入 `/api/v1/` 路由前缀 |
| T-10 | **Observability 仅覆盖 LLM** | 应用级问题无法追踪 | 补充应用指标（请求延迟、错误率、DB 连接池） |
| T-11 | **Entity Catalog 重建未自动化** | KB 更新后 UI 可能不同步 | 加入 deploy pipeline 或 webhook 触发 |

---

## 五、第一轮优先推动的技术改进

### 5.1 立即开始（基建）

**推进测试体系建设**（T-01）——这是我现在最关心的。

具体步骤：
1. 建立 `backend/tests/` 目录 + pytest 配置
2. 为 `pob_service.py` 写 golden data 测试（准备 2-3 个已知正确的 PoB code）
3. 为 `entity_resolver.py` 写别名映射测试
4. 为 `chat_tools.py` 中的核心 tool 写单元测试
5. 集成到 Docker Compose 或 CI

这套测试框架建起来后，后面的所有重构和新增功能才有安全网。

### 5.2 本周内（数据）

1. 修复 TC 数据导出（T-02）——和数据组对齐后协调资源
2. 确认 celery_beat 生产配置（T-07）
3. 如果 game_relations.json 确实不存在，需要排进数据恢复计划

### 5.3 排入下一轮

1. 双运行时统一决策（T-03）——需要和产品对齐路线图
2. Skills 模块重命名（T-04）——低成本高回报
3. 开发环境 PostgreSQL 化（T-05）

---

## 六、对 P0 核心闭环的技术评审

P0 核心闭环：**PoB 解码 → 解析 → AI 攻略生成 → 存储 → 展示**

从代码看，这条链路已经走通（M1 milestone ✅），但我发现了几个值得关注的点：

1. **PoB 解码**（`pob_service.py`）：标准库 XML 解析，无外部依赖，设计合理。但缺少针对畸形 PoB code 的错误恢复测试。
2. **AI 攻略生成**（`ai_service.py` → 29.1KB）：这是最大的单文件之一。AI 输出质量依赖 prompt 设计 + 知识库召回质量。需要评估 homework 生成的成功率和质量指标。
3. **BuildData 存储**（`builds` 表 JSONB）：Schema-flexible 设计合理，但缺乏对 BuildData 结构的版本管理——如果解析逻辑升级，旧数据怎么兼容？

**建议对 P0 线路增加质量仪表盘**：
- 解码成功率
- AI 攻略生成成功率
- 用户查看攻略后的后续操作（存为了？看了？分享了？）

---

## 七、架构路线图建议

```
Phase 1（当前）—— 稳基础
├── 建测试体系（T-01）
├── 修 TC 数据（T-02）
├── 确认部署配置（T-07）
└── 数据管道脚本化（T-06）

Phase 2（下一轮）—— 清债务
├── 统一运行时（T-03）
├── Skills 模块重构（T-04）
├── 开发环境 PostgreSQL 化（T-05）
└── API 版本化（T-09）

Phase 3（中期）—— 提质量
├── Observability 增强（T-10）
├── Entity Catalog 自动化（T-11）
├── 性能基准 + 压测
└── Browser Extension（M7/M8）
```

---

*报告结束。待朝露审阅后确定优先级和资源分配。*
