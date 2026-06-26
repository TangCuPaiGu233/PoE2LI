# PR Merge 前 QA 审查 Checklist

> **用途**：首个工程师 PR 到达时，按本清单执行 QA Code Review Gate
> **依据**：`docs/qa-gate-process.md` + `docs/review-process.md`
> **维护人**：半山居

---

## 使用方式

1. PR 到达后，先确认是否属于 QA 必须介入类型（见第 1 节）
2. 按第 2 节执行 Code Review 审查
3. 按第 3 节确认 CI Gate 结果
4. 按第 4 节给出审查结论
5. 记录到第 5 节

---

## 1. 介入判定

| PR 类型 | QA 是否介入 | 说明 |
|:--------|:-----------:|:-----|
| API 端点新增/修改 | ✅ 必须 | 参数校验、响应 schema、错误码 |
| 数据模型变更 | ✅ 必须 | migration、字段约束、索引 |
| AI/LLM 相关 | ✅ 必须 | prompt、输出 schema、guard 规则 |
| 安全配置变更 | ✅ 必须 | CORS、鉴权、secret 处理 |
| CI/CD 变更 | ✅ 必须 | 门禁、依赖、扫描 |
| 工具逻辑变更 | ✅ 必须 | `chat_tools.py`、副作用 |
| 纯 UI 组件（无 API 对接） | 🟡 可选 | 视影响范围 |
| 文档/注释/README | ❌ 豁免 | 仅需 Peer Review |

---

## 2. Code Review 审查清单

### 2.1 五轴快速扫描（远岫 Checklist 补充）

- [ ] **正确性**：代码实现了需求？边界条件已覆盖？错误路径有处理？日志足够定位问题？
- [ ] **设计**：符合现有架构？无 unnecessary dependency？接口可扩展？模块职责单一？
- [ ] **可维护性**：命名自文档化？复杂逻辑有 Why 注释？配置已提取？类型注解完整？
- [ ] **测试**：新功能有测试？修复的 bug 有 regression test？测试独立可重复？
- [ ] **安全**：外部输入已校验？API 鉴权已考虑？无敏感数据泄露？降级策略已定义？

### 2.2 QA 专项审查

- [ ] **测试覆盖**：新增/修改代码有对应测试？核心模块覆盖率未下滑？
- [ ] **回归风险**：修改是否影响既有模块？相关测试是否已跑？
- [ ] **AI/LLM 安全**：LLM 调用有输入/输出控制？prompt 有注入风险？输出有 schema 验证？
- [ ] **数据安全**：无 SQL 拼接？无敏感数据日志？向量操作类型正确？
- [ ] **外部依赖**：新增依赖是否必要？版本是否锁定？
- [ ] **错误处理**：失败路径是否可观测？try/except 是否恰当？有降级策略？
- [ ] **性能**：无明显性能陷阱？循环内无 DB 查询？热路径有缓存？

### 2.3 按模块专项检查

| 模块 | 检查项 |
|:-----|:--------|
| `api/*` | 参数校验、响应 schema、错误码一致性、无敏感信息泄露 |
| `services/chat_agent.py` | LLM 超时、空回复、工具调用失控、上下文长度 |
| `services/chat_tools.py` | 工具输入 schema 校验、副作用（DB 写入/外部调用） |
| `services/pob_service.py` | 畸形 PoB code 错误恢复、zombie XML 解析 |
| `services/entity_resolver.py` | 别名消歧准确性、fallback 行为 |
| `services/filter_generator.py` | 生成的 filter 语法正确性、注入风险 |
| `services/trade_*.py` | 外部 API 超时、限流、缓存失效策略 |
| `core/database.py` | SQLite/PostgreSQL 行为一致性、pgvector 类型 |
| `orchestrator/*` | 并行调用异常传播、session 泄漏 |
| `tasks/*` | Celery 任务幂等性、失败重试、死信风险 |

---

## 3. CI Gate 确认

- [ ] pytest 全绿（0 failure）
- [ ] lint 全绿（ruff check 0 error）
- [ ] 覆盖率报告已生成
- [ ] 无 security alert

---

## 4. 审查结论

| 结论 | 说明 | 下一步 |
|:-----|:-----|:-------|
| ✅ Approve | 无问题 | 进入 Merge |
| 🟡 Comment | 非阻塞建议 | 可合并后跟进 |
| 🔴 Request Changes | 阻塞项 | 必须修复后重新审查 |

**响应时限**：P0 PR ≤ 2 项目时，P1 ≤ 8 项目时，P2 ≤ 1 项目日。

---

## 5. 审查记录模板

```
PR: #
作者:
模块:
审查时间:
结论:

问题清单:
1. [ ] ...
2. [.].

备注:
```

---

*维护人：半山居 | 最后更新：项目时间 第 2 天*
