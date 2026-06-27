# Chat 运行时统一方案 — 决策文档

**作者**：远岫（架构师）  
**交付时间**：项目时间 第 0 天 — 第 4 天  
**状态**：定稿，可直接用于排期和实施

---

## Part 1 — 运行时选型结论（D0-1 已交付）

### 结论

**选 Orchestrator 作为唯一运行时，废弃 Legacy ReAct。**

### 对比维度

| 维度 | Legacy ReAct | Orchestrator | 结论 |
|------|-------------|-------------|------|
| **架构意图** | AI 做路由+执行，揉在一起 | AI 做路由，代码做执行（Planner→Dispatch→Synthesis 三层） | 🏆 Orchestrator |
| **代码量** | ~400 行（chat_agent.py）含 90 行可抽公共函数 | ~500 行（chat_orchestrator.py）+ ~200 行 planner | 大体相当 |
| **规则维护** | 36 条规则耦合在一条 system prompt，修改涉及全局 | 规则分散在 planner prompt + skill prompt + synthesis prompt，互不影响 | 🏆 Orchestrator |
| **并行能力** | 串行 tool call，一轮一步 | 多子任务并行 dispatch，独立结果 | 🏆 Orchestrator |
| **错误隔离** | 单点失败整轮崩溃 | 单子任务失败不影响其他，合成时优雅降级 | 🏆 Orchestrator |
| **完成度** | ✅ 生产级成熟（默认运行时） | ⚠️ 4 个可修缺口（Planner schema 验证、Fallback 粗糙、超时、重试） | 过渡期需补 |
| **可观测性** | ❌ 中间状态不可见 | ✅ 结构化 SkillAgentResult，每步可追踪 | 🏆 Orchestrator |
| **扩展性** | 新增能力域需改 ReAct 循环 | 新增能力域 = 新 Skill + 新 tool，planner 自动路由 | 🏆 Orchestrator |
| **依赖关系** | 依赖 orchestrator.session_context ← 循环依赖 | 依赖 legacy._emit_streamed_answer → 循环依赖 | 等解耦 |

### 关键决策理由

1. **架构匹配度**：产品已有多个能力域（交易搜索、百科问答、BD 配装、PoB 解析、物品推荐），Orchestrator 的分层架构天然匹配多域路由，Legacy 的单一 ReAct 循环随域增多会急剧膨胀。
2. **规则漂移风险**：Legacy 36 条规则在同一条 system prompt 中竞争注意力，Orchestrator 每层（planner / skill / synthesis）只关注自己的 prompt 片段，规则冲突概率低一个数量级。
3. **长期维护成本**：Legacy 每加一个能力需要改 ReAct 循环 + system prompt，Orchestrator 只需加 Skill 文件。
4. **决策依据**：这不是"哪个更完善"的选择，而是"哪个架构方向对"的选择。Orchestrator 的缺口是代码深度问题，不是架构问题，花时间补齐即可。

---

## Part 2 — 废弃方案设计

### 2.1 迁移路线总览

```
Step 0 (D0-D1)  解耦循环依赖           ← 已完成
Step 1 (D1-D4)  修 Orchestrator 缺口    ← 进行中（Step 1A）
Step 2 (D4-D7)  切换默认运行时
Step 3 (D7-D10) 规则迁移（36 条规则分层）
Step 4 (D10+)   Legacy 清理
```

### 2.2 Step 0 — 解耦循环依赖（已完成 ✅）

| 操作 | 文件 | 状态 |
|------|------|------|
| 移动 session_context.py | `orchestrator/session_context.py` → `services/session_context.py` | ✅ 已合入 main (004f3a9) |
| 更新 import | 4 处：chat_agent.py / chat_orchestrator.py / llm_planner.py / planner.py | ✅ 已合入 |
| 更新 __init__.py | orchestrator/__init__.py 删除 session_context 导出 | ✅ 已合入 |
| 测试文件修复 | 2 个测试文件（test_orchestrator_planner.py / test_session_context.py） | ✅ 已合入（来迟 gate 通过） |

### 2.3 Step 1 — 修 Orchestrator 缺口（进行中）

**Step 1A：抽取公共 LLM 流式函数到 `app/core/llm_stream.py`**

| # | 原子步骤 | 文件 | 预计工作量 | 状态 |
|---|---------|------|-----------|------|
| A.1 | 创建 `app/core/llm_stream.py`，从 `chat_agent.py` 抽出 `get_llm_client()` + `emit_streamed_answer()` + `_sanitize_answer/reasoning` + `_safe_flush_point()` | 新建 | ~15min | ⏰ 待 Dispatch |
| A.2 | 更新 `chat_orchestrator.py` import：从 `chat_agent` 改为 `core.llm_stream` | 改 1 行 | ~2min | ⏰ |
| A.3 | 更新 `chat_agent.py`：删除已提取函数，改为从 `core.llm_stream` re-import（保持向后兼容） | 改 1 行（顶部加 import） | ~5min | ⏰ |
| A.4 | `test_llm_stream.py` — import 路径正确性 + 基础功能 | ~15min | ⏰ |
| A.5 | 全局 grep 确认无残留 import | ~3min | ⏰ |
| A.6 | 烟测：legacy 和 orchestrator 各跑一轮 chat | ~10min | ⏰ |

**Step 1B：Planner Pydantic 验证（已决策，待实施）**

| # | 原子步骤 | 文件 | 预计工作量 | 状态 |
|---|---------|------|-----------|------|
| B.1 | 在 `orchestrator/` 下新增 `schemas.py`，定义 PlanStep / Plan Pydantic 模型 | 新建 | ~15min | 📋 已出方案 |
| B.2 | 修改 `llm_planner.py` 的 `_extract_json()` → 用 Pydantic 验证 | ~20min | 📋 |
| B.3 | 验证失败时 retry（最多 2 次）+ 退化 plan | ~15min | 📋 |
| B.4 | 在 `planner.py` 入口二次验证 | ~5min | 📋 |
| B.5 | 测试：`test_orchestrator_planner_validation.py` + golden data | ~20min | 📋 |

**Step 1C：Fallback 确定性改进（已决策，待实施）**

| # | 原子步骤 | 文件 | 预计工作量 | 状态 |
|---|---------|------|-----------|------|
| C.1 | Synthesis 阶段添加分层 fallback 链（重试→降级→fallback Legacy） | `chat_orchestrator.py` | ~20min | 📋 已出方案 |
| C.2 | 每级 fallback 添加结构化日志 | ~10min | 📋 |
| C.3 | 计数器指标 | ~5min | 📋 |
| C.4 | Legacy fallback 加 DeprecationWarning | ~3min | 📋 |

### 2.4 Step 2 — 切换默认运行时（D4-D7 窗口）

| 操作 | 详情 | 回滚方案 |
|------|------|---------|
| 改默认值 | `.env` / `settings.py` 中 `CHAT_RUNTIME = "orchestrator"` | 改回 `"legacy"` 立即恢复 |
| 灰度策略 | 先切 10% 流量观察 1 天（如通过 Langfuse 按用户 hash 抽样） | 关灰度即切回 |
| 监控对比 | 对比两套运行时的：成功率 / 响应时长 / 用户反馈 | 持续 2 天 |
| 公告 | 内部通知开发团队默认已切换，关注异常 | — |

### 2.5 Step 3 — 规则迁移（D7-D10 窗口）

Legacy 的 36 条 system prompt 规则拆分为 3 层：

| 层次 | 目标 | 位置 | 规则数 |
|------|------|------|--------|
| Planner 层 | 路由决策（多能力域分发） | skills/planner-prompt.md | ~12 条 |
| Skill 层 | 各能力域行为约束（交易/百科/BD/PoB） | skills/{domain}-prompt.md | ~15 条 |
| Synthesis 层 | 最终回答整合风格 | skills/synthesis-prompt.md | ~9 条 |

每迁移一条，在 Legacy 侧标记 `// @deprecated - migrated to planner/skill/synthesis`。

### 2.6 Step 4 — Legacy 清理（D10+ 窗口）

**删除范围**：

| 文件 | 原因 |
|------|------|
| `backend/app/services/chat_agent.py` | Legacy ReAct 核心，整文件废弃 |
| `backend/app/services/chat_tools.py` 中 legacy 专用 tool wrapper | 如已有 orchestrator 等价实现 |
| `backend/app/services/_deprecated/`（可选） | 不立即删，先移至此目录保留 1 个 sprint |

**保持兼容的 import shim**：

```python
# 在 chat_agent.py 删除前，临时保留为 shim
# backend/app/services/chat_agent.py → 重命名为 _chat_agent_legacy.py
# 原位置仅保留 import 转发
from app.core.llm_stream import emit_streamed_answer  # 实际已移至 core
from app.orchestrator.session_context import build_session_context  # 已移至 services
```

**兼容期**：Step 4 后保留 shim 1 个 Sprint（~7 天），期间任何尝试 import legacy 模块的代码会收到 DeprecationWarning。之后清理 shim。

---

## Part 3 — 双轨切换影响分析

### 3.1 影响模块清单

| 模块 | 受影响程度 | 详细说明 |
|------|-----------|---------|
| `chat_agent.py` | 🔴 整文件废弃 | Step 4 删除。Step 1A 将其公共函数抽取到 core/，Step 4 直接删除剩余 ReAct 循环。 |
| `chat_orchestrator.py` | 🟡 修改 import + 加 fallback | Step 1A 改 import 路径；Step 1C 加 fallback 链。无业务逻辑变化。 |
| `_stream_chat()` in `knowledge.py` | 🟢 无影响 | 运行时入口已通过 `CHAT_RUNTIME` 环境变量切换，逻辑不感知具体运行时。 |
| SSE 流式响应 | 🟢 无直接影响 | 流式接口由 `emit_streamed_answer()` 统一处理，Legacy/Orchestrator 共用。 |
| API 路由 (`/api/chat/*`) | 🟢 无影响 | 路由层不感知运行时，只调用 `_stream_chat()`。 |
| Skills 层 (`skills/`) | 🟢 无直接影响 | 但 Step 3 规则迁移会利用 skills/ 目录作为目标位置。 |
| `app/core/llm_client.py` | 🟢 无影响 | 已是公共模块。 |
| `services/session_context.py` | 🟢 已解耦 | Step 0 已移到 services。 |
| `orchestrator/` 包 | 🟡 Step 1B/1C 新增代码 | 加 schemas.py，改 llm_planner.py、planner.py、chat_orchestrator.py。 |
| 测试文件 | 🟡 需补充 | Step 1A: test_llm_stream.py；Step 1B: test_planner_validation.py；Step 1C: test_fallback_chain.py |

### 3.2 对归鸿 R-01~R-05 的影响

**结论：无阻塞，正交关系。**

归鸿的 R-01~R-05 修复（超长上下文裁剪、幻觉声明、重试等）作用于 `chat_orchestrator.py` 和 `orchestrator/` 包中的 Synthesis 阶段。这些修改与 Step 1（llm_stream.py 抽取 / Planner 验证 / Fallback）完全不冲突。

具体来说：
- R-01（上下文窗口管理）→ 修改 `chat_orchestrator.py` 的 Synthesis 上下文组装逻辑。Step 1A 只改 import 路径，Step 1C 加 fallback 链——两者改的是不同函数，git 不会冲突。
- R-02（幻觉声明）→ 修改 synthesis prompt / post-processing。完全独立。
- R-03（重试）→ 与 Step 1C 的 fallback 链有重叠——归鸿可基于 Step 1C 合并后的代码继续。
- R-04/R-05 → 完全独立。

**建议**：归鸿基于当前 main（含 Step 0）即可开工。Step 1A/1B/1C 合入后 rebase 一次即可。

### 3.3 对织墨后端清理的影响

| 阶段 | 织墨工作 | 预计人时 |
|------|---------|---------|
| Step 1A（现在） | 创建 llm_stream.py + 改 import | ~45min |
| Step 1B | 加 Pydantic schema + 验证逻辑 | ~60min |
| Step 1C | 加 fallback 链 + 日志 | ~40min |
| Step 2 | 改默认值 + 灰度部署 | ~15min |
| Step 3 | 规则迁移（36 条分层） | ~2h |
| Step 4 | 清理 legacy 文件 + shim | ~30min |
| **总计** | | **~5h** |

### 3.4 与其他人成员的并行关系

| 成员 | 当前工作 | 与运行时切换的关系 | 处理方式 |
|------|---------|-----------------|---------|
| 守夜 | TC 数据修复 | 完全正交 | 独立推进 |
| 松烟 | 数据管道脚本化 | 完全正交 | 独立推进 |
| 归鸿 | AI 稳定性 R-01~R-05 | 正交，共享 orchestrator 模块 | 基于 main 开工，rebase |
| 栖霞 | SSE 重连 | 完全正交 | 独立推进 |
| 来迟 | 测试基础设施 | 辅助验证 | 运行时切换后负责集成测试 |
| 行舟 | CI/CD / 运维 | 辅助部署 | Step 2 灰度需行舟配合配置 |

### 3.5 风险 & 缓解措施

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| Step 1A 抽取 llm_stream.py 时遗漏私有函数引用 | 低 | 中 | 全局 grep + 烟测 |
| Step 2 切换默认后成功率下降 | 中 | 高 | 灰度 10%→50%→100%，保留 fallback |
| Step 1B Pydantic schema 与 LLM 实际输出格式不匹配 | 中 | 中 | 先分析 50 条历史 planner 输出再定 schema |
| Step 3 规则迁移遗漏关键规则 | 中 | 高 | 迁移前后 A/B 测试用户满意度 |
| 归鸿 R-01~R-05 与 Step 1 同时改 chat_orchestrator.py | 低 | 中 | git rebase 解决，冲突范围有限 |

---

## 附录：文件变更总清单

### 新增文件
1. `backend/app/core/llm_stream.py` — 公共 LLM 流式函数（Step 1A）
2. `backend/app/orchestrator/schemas.py` — Pydantic 模型（Step 1B）
3. `tests/test_llm_stream.py` — 流式函数测试（Step 1A）
4. `tests/test_orchestrator_planner_validation.py` — Planner 验证测试（Step 1B）

### 修改文件
1. `backend/app/services/chat_orchestrator.py` — 改 import（Step 1A）+ 加 fallback（Step 1C）
2. `backend/app/services/chat_agent.py` — 删除公共函数，改 import（Step 1A）；整文件废弃（Step 4）
3. `backend/app/orchestrator/llm_planner.py` — 加 Pydantic 验证（Step 1B）+ 改进 fallback（Step 1C）
4. `backend/app/orchestrator/planner.py` — 入口二次验证（Step 1B）

### 删除文件（Step 4+）
1. `backend/app/services/chat_agent.py`（整文件）
2. 可能：`backend/app/services/chat_tools.py` 中 legacy wrapper

---

*文档结束。远岫 / 项目时间 第 4 天 10:00*
