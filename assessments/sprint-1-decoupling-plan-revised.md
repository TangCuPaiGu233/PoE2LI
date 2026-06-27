# Sprint 1 运行时解耦方案（修订版 v2）

> 基于 2026-06-27 代码稽核结果重写
> 原 `chat-runtime-unification-plan.md` 声称 Step 0 已完成，实际未执行
> 作者：重构 (Tech Lead) | 审核：白鹭 (CEO) ✅ v2 已响应审核意见

---

## 一、当前状态（实测）

### 循环依赖链路

```
orchestrator/session_context.py (218行)
    ↑ 被以下文件 import：
    ├── orchestrator/llm_planner.py:14
    ├── orchestrator/planner.py:7
    ├── services/chat_agent.py:17  ← 关键
    ├── services/chat_orchestrator.py:15  ← 关键
    └── tests/ 下 3 个文件

services/chat_agent.py (735行)
    ↑ 被以下文件 import：
    └── services/chat_orchestrator.py:16 (_emit_streamed_answer, _llm_client)
    └── services/chat_orchestrator.py:256 (stream_chat_agent, lazy import)
    └── tests/ 下 3 个文件

services/llm_stream.py (206行)
    → 已提取，但 0 个消费者 ← 文档说 Step 1 已完成，实际没用上
```

### 重复代码确认
| 函数 | chat_agent.py | llm_stream.py | 状态 |
|------|--------------|---------------|------|
| `_emit_streamed_answer` | L332 ✅ | `emit_streamed_answer` L143 ✅ | 完全重复 |
| `_llm_client` | L302 ✅ | `get_llm_client` L127 ✅ | 完全重复 |
| `_first_choice` | L327 ✅ | `first_choice` L137 ✅ | 完全重复 |
| `_sanitize_answer` | 内部 | `sanitize_answer` L29 | 待确认 |

---

## 二、Step 0：移动 session_context.py

### 操作
1. `git mv backend/app/orchestrator/session_context.py backend/app/services/session_context.py`
2. 更新 7 处 import

### 需要修改的文件

| 文件 | 原 import | 改为 |
|------|----------|------|
| `orchestrator/llm_planner.py:14` | `from app.orchestrator.session_context import ...` | `from app.services.session_context import ...` |
| `orchestrator/planner.py:7` | 同上 | 同上 |
| `services/chat_agent.py:17` | 同上 | 同上 |
| `services/chat_orchestrator.py:15` | 同上 | 同上 |
| `tests/test_orchestrator_planner.py:7` | 同上 | 同上 |
| `tests/test_session_context.py:3` | 同上 | 同上 |
| `tests/unit/test_chat_truncation.py:8` | 同上 | 同上 |

### 验证标准
- [ ] `git grep "from app\.orchestrator\.session_context"` 返回 0 结果
- [ ] `python -c "from app.services.session_context import build_session_context"` 成功
- [ ] `python -c "from app.orchestrator.llm_planner import llm_plan_dispatch"` 成功
- [ ] `python -c "from app.services.chat_agent import stream_chat_agent"` 成功
- [ ] `python -c "from app.services.chat_orchestrator import stream_chat"` 成功

### 预估工时
~30min（文件移动 + 7 处 import 修改 + 验证）

---

## 三、Step 1：消除 chat_agent.py ↔ chat_orchestrator.py 交叉依赖

### 操作
1. 从 `chat_agent.py` 中删除重复函数：
   - 删除 `_emit_streamed_answer`（L332-~390）
   - 删除 `_llm_client`（L302-303）
   - 删除 `_first_choice`（L327-329）
   - 删除 `_model`（L306-307）
2. 在 `chat_agent.py` 顶部添加：
   ```python
   from app.services.llm_stream import emit_streamed_answer, get_llm_client
   ```
3. 更新 `chat_orchestrator.py:16`：
   ```python
   # 改前
   from app.services.chat_agent import _emit_streamed_answer, _llm_client
   # 改后
   from app.services.llm_stream import emit_streamed_answer, get_llm_client
   ```
4. 更新 `chat_orchestrator.py:256`（lazy import）：
   - `stream_chat_agent` 是 `chat_agent.py` 的入口主函数，暂时保留
   - 这是 Legacy ReAct 的运行入口，其存在不构成循环依赖（因为 session_context 已迁移）
   - 但标记为待废弃（Step 3-4, Sprint 2 范围）
5. 更新测试文件：
   - `tests/test_chat_orchestrator.py:318`：更新 import
   - `tests/test_sanitize_answer.py:9`：确认 `_sanitize_answer` 是否已抽取

### 验证标准
- [ ] `chat_agent.py` 不再定义 `_emit_streamed_answer` / `_llm_client` / `_first_choice`
- [ ] `chat_orchestrator.py` 不再 import `chat_agent` 除 `stream_chat_agent`（lazy）外的任何符号
- [ ] `python -c "from app.services.chat_orchestrator import stream_chat"` 成功
- [ ] eval 基线通过（不退化）

### 预估工时
~45min（删除重复代码 + 更新 import + 测试修复 + 验证）

---

## 四、Step 1.5（推荐在 Sprint 1 内完成）：llm_stream 统一化

### 操作
- 将 `chat_agent.py` 中其他 LLM 相关的辅助函数也迁移到 `llm_stream.py`
- 确认 `_sanitize_answer` / `_sanitize_reasoning` 是否存在重复（与 `sanitize_answer` / `sanitize_reasoning`）
- 如果重复，统一为 llm_stream 版本

### 预估工时
~20min

---

## 五、Sprint 1 完整技术 Backlog

### 核心目标
**运行时解耦 + 文档修复 + 技术债清单化**

### S1.5 定位说明（响应白鹭审核意见）
S1.5（RRF + reranker）是 P0-B "检索流水线重构"的收尾，**不是运行时解耦的依赖**。去掉 S1.5 后核心目标依然完整。因此 S1.5 降级为 **stretch goal**——资源有余裕再安排，不做不阻塞主线。

### 任务清单

| 编号 | 任务 | 工时 | 依赖 | 负责人 |
|:---:|------|:---:|:----:|:------:|
| **S1.0** | Step 0：移动 session_context.py | 30min | 无 | `缓存` |
| **S1.1** | Step 1：消除交叉依赖 + 去重 | 45min | S1.0 | `缓存` |
| **S1.2** | 步骤验证：import 链 + 单元测试 | 20min | S1.1 | `缓存` |
| **S1.3** | 文档对账：修复 doc-vs-code 不一致（B4） | 30min | 无 | 可并行 |
| **S1.4** | 技术债清单归档（B7） | 30min | 无 | `重构` |
| **S1.6** | CI 门禁：eval 基线 + 自动化测试入口 | 2h | S1.1 | `卡农` |
| **S1.7** | 像素入职：读 CLAUDE.md + 搭 FE 开发环境 | 30min | 无 | `像素` |
| **S1.8** | Trade 搜索结果前端页面（B6） | 3h | S1.7 | `像素` |
| **S1.5** | **RRF + reranker（stretch goal）** | 4h | 无（与主线并行） | `卡农` |

### 核心任务（不含 stretch goal）总工时
~8.5 人·小时，分配到 3 人可在 1 天内完成

### 不纳入 Sprint 1 的内容
- ❌ P1 实体重建（依赖数据工程师 + AI 工程师到位）
- ❌ P1 玩家经验注入（上述依赖 + schema 变更需评审）
- ❌ Legacy ReAct 完全废弃（Step 3-4，需更多测试覆盖）
- ❌ Docker 重构（B5，P1 优先级）

---

## 六、风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|:---:|:----:|---------|
| session_context 移动后部分隐式 import 遗漏 | 中 | 高 | 全局 grep + 验证脚本 + import 测试 |
| chat_agent.py 大量删减后功能退化 | 中 | 高 | Eval 基线前后对比 + stream_chat_agent 入口不动 |
| 文档对账发现更多不一致 | 高 | 低 | 随发现随修复，不阻塞主线 |
| 拼图排期与技术人员可用时间冲突 | 中 | 中 | 协商并行窗口 |
| 像素首次接触项目，FE 环境搭建遇阻 | 低 | 中 | 缓存或卡农可协助后端侧问题 |

---

## 七、代码评审要点（代 QA 来日方长）

审查应重点检查：
1. Step 0 的 import 替换是否全局覆盖（不要遗漏 test 文件）
2. Step 1 删除的函数是否被除 `chat_orchestrator.py` 外的文件引用
3. `stream_chat` 函数在两种 runtime 下的行为是否一致
4. `llm_stream.py` 中的 `emit_streamed_answer` 是否完全兼容原 `_emit_streamed_answer`
5. 前端 Trade UI 页面是否与 `trade_service.py` 的 API 响应字段对应

---

## 八、执行顺序建议（待拼图确认排期）

```
第 1 天:
  S1.7 [像素] 入职 + 环境搭建 (30min)
  S1.0 [缓存] Step 0 (30min)
  S1.3 [可并行] 文档对账 (30min)
  S1.4 [重构] 技术债归档 (30min)
  
第 1-2 天:
  S1.1 [缓存] Step 1 (45min)
  S1.2 [缓存] 验证 (20min)
  S1.6 [卡农] CI 门禁 (2h)
  S1.8 [像素] Trade UI (3h)
  
 stretch goal（如果有余裕）:
  S1.5 [卡农] RRF + reranker (4h)
```
