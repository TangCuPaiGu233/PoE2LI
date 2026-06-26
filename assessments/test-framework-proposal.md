# 测试框架技术方案

**撰写者**：远岫（技术架构师）
**时间**：项目时间 第 0 天 09:30
**状态**：草案 / 待朝露和织墨审阅

---

## 一、现状

当前项目代码库中 **零测试基础设施**：
- 无 `test_*.py` 文件
- 无 `conftest.py` 配置
- 无 `pytest.ini` / `pyproject.toml` 测试配置
- 无 CI 流水线中的测试步骤

这是我在《技术架构评估》中标记的 **最高风险项**（可测试性评分 ★☆☆☆☆）。
朝露已确认该判断，Phase 1 首要任务即建立测试体系。

---

## 二、测试策略分层

```
        ┌─────────────────────────┐
        │   E2E 测试 (少量)        │  ← 完整链路验证，P0 核心循环 1-2 条
        ├─────────────────────────┤
        │   集成测试 (中等)         │  ← API + DB + Redis 真实交互
        ├─────────────────────────┤
        │   单元测试 (大量)         │  ← 纯逻辑，可 mock 外部依赖
        └─────────────────────────┘
```

### 2.1 单元测试（覆盖率目标：核心模块 ≥ 80%）

**测试对象**：纯函数、确定性逻辑、数据转换

**典型模块**：
| 模块 | 测试内容 | 优先级 |
|------|---------|--------|
| `pob_service.py` | PoB 解码（base64+zlib+XML 解析） | P0 |
| `entity_resolver.py` | 实体别名查找、O(1) catalog 查询 | P0 |
| `entity_validator.py` | 实体名校验规则 | P0 |
| `chat_response_guard.py` | 输出守卫规则 | P0 |
| `trade_stats_index.py` | 词缀索引构建和查询 | P1 |
| `trade_items_index.py` | 物品索引 | P1 |
| `filter_generator.py` | 过滤规则生成 | P1 |
| `multi_affix_compare.py` | 词缀对比逻辑 | P1 |
| `build_design.py` / `encyclopedia.py` | Skill 工具的原子逻辑 | P1 |

**策略**：
- 不 mock LLM / 外部 API —— 这些属于集成测试
- 只测试纯函数：输入 X → 输出 Y
- PoB 解码：用 Golden Data（已知的 PoB 分享码 → 期望的解析结果）

### 2.2 集成测试（覆盖率目标：API 端点 ≥ 90%）

**测试对象**：FastAPI 路由 + 数据库 + Redis 缓存

**典型场景**：
| API 端点 | 测试内容 | 优先级 |
|----------|---------|--------|
| `POST /api/builds/decode` | 解码 PoB（含异常码、空码） | P0 |
| `POST /api/builds` | 创建构建（解码+存储+homework 触发） | P0 |
| `GET /api/builds/{id}` | 读取构建详情 | P0 |
| `POST /api/qa/ask` | 问答（mock LLM 返回） | P0 |
| `GET /api/entities/{name}` | 实体解析 | P0 |
| `POST /api/trade/search` | 市集搜索（mock 外部 API） | P1 |
| `POST /api/filter/generate` | 过滤生成 | P1 |
| `GET /api/knowledge/search` | 知识库搜索 | P1 |

**策略**：
- 使用 SQLite `:memory:` 数据库，每次测试独立建表
- FastAPI `TestClient` 直接调用，不启动 Uvicorn
- Redis 用 `fakeredis` 或测试实例
- LLM 调用用 `pytest-monkeypatch` 或 `unittest.mock` 打桩
- 外部 HTTP API（Path of Exile 官方 API、poe.ninja）用 `responses` 或 `httpx_mock`

### 2.3 E2E 测试（1-2 条核心路径）

**目的**：验证 P0 核心循环通不通，不做全覆盖

**路径**：
1. 用户输入 PoB 分享码 → 解码成功 → 生成 homework → 存入数据库 → 前端可查
2. 用户提问 "这个 Build 适合打什么图" → AI 回答含知识引用

**策略**：
- 使用真实数据库（SQLite 文件）和真实 LLM（但限制 token 用量）
- 跑通即绿，不追求深度覆盖
- 作为 pre-merge 的 smoke test

---

## 三、技术选型

| 工具 | 用途 | 理由 |
|------|------|------|
| **pytest** | 测试框架 | Python 生态标准，plugins 丰富 |
| **pytest-cov** | 覆盖率报告 | 集成度好，支持按模块过滤 |
| **httpx** / **TestClient** | API 测试 | FastAPI 原生支持，异步兼容 |
| **fakeredis** | Redis mock | 纯 Python 实现，无需 Redis 实例 |
| **responses** 或 **httpx_mock** | HTTP mock | 拦截外部 API 调用 |
| **pytest-xdist** | 并行执行 | 后期提速用 |
| **pytest-sugar** | 可读性 | 美化输出，CI 日志友好 |

---

## 四、目录结构

```
backend/
├── tests/
│   ├── conftest.py              # 全局 fixture（DB session, TestClient, mock LLM）
│   ├── pytest.ini                # pytest 配置
│   ├── requirements-test.txt     # 测试依赖（独立于 prod requirements）
│   │
│   ├── unit/
│   │   ├── test_pob_service.py          # PoB 解码单元测试
│   │   ├── test_entity_resolver.py      # 实体解析器
│   │   ├── test_entity_validator.py     # 实体验证器
│   │   ├── test_chat_response_guard.py  # 输出守卫
│   │   ├── test_trade_stats_index.py    # 词缀索引
│   │   └── test_filter_generator.py     # 过滤生成
│   │
│   ├── integration/
│   │   ├── test_api_decode.py           # POST /api/builds/decode
│   │   ├── test_api_builds.py           # CRUD /api/builds
│   │   ├── test_api_qa.py               # POST /api/qa/ask
│   │   ├── test_api_entities.py         # GET /api/entities/{name}
│   │   ├── test_api_trade.py            # POST /api/trade/search
│   │   └── test_api_filter.py           # POST /api/filter/generate
│   │
│   └── e2e/
│       └── test_p0_core_loop.py         # P0 核心循环 smoke test
│
├── tests_golden/
│   ├── pob_codes/                # 已知 PoB 分享码（文本文件）
│   │   ├── basic_warrior.txt
│   │   ├── stormweaver_mage.txt
│   │   └── invalid_code.txt
│   └── expected_outputs/         # 对应的期望解析结果（JSON）
│       ├── basic_warrior.json
│       ├── stormweaver_mage.json
│       └── invalid_code_error.json
```

---

## 五、核心 Fixture 设计

### 5.1 数据库 Fixture（`conftest.py`）

```python
# backend/tests/conftest.py (草案)
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.database import Base
from app.main import app
from fastapi.testclient import TestClient

@pytest.fixture(scope="function")
def db_session():
    """每次测试独立的内存数据库。"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)
    session = TestSession()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)

@pytest.fixture(scope="function")
def client(db_session):
    """FastAPI TestClient，依赖注入覆盖为测试 DB。"""
    def override_get_db():
        yield db_session
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()

@pytest.fixture(scope="function")
def mock_llm(monkeypatch):
    """为所有 LLM 调用提供固定返回。"""
    # 使用 monkeypatch 替换 llm_client.py 中的调用
    ...
```

### 5.2 Golden Data Fixture

```python
@pytest.fixture
def golden_data_path():
    """指向 tests_golden/ 目录的 Path 对象。"""
    from pathlib import Path
    return Path(__file__).parent.parent / "tests_golden"

@pytest.fixture
def sample_pob_code(golden_data_path):
    """读取 basic_warrior 的 PoB 分享码。"""
    return (golden_data_path / "pob_codes" / "basic_warrior.txt").read_text()
```

---

## 六、优先执行顺序

### Phase 1a —— 基础设施（半天项目时间）
1. 创建 `tests/` 目录结构
2. 编写 `conftest.py`（DB + TestClient + mock LLM）
3. 配置 `pytest.ini` 或 `pyproject.toml`
4. 编写第一个冒烟测试：`GET /health` 返回 `{"status": "ok"}`
5. 验证测试能在本地运行（`python -m pytest tests/ -v`）

### Phase 1b —— P0 模块覆盖（1-2 天项目时间）
按优先级：
1. **PoB 解码单元测试**（`pob_service.py`）—— 使用 golden data，mutation-free
2. **实体解析单元测试**（`entity_resolver.py` + `entity_validator.py`）—— 别名匹配的边界情况
3. **API 集成测试**（`/api/builds/decode` + `/api/builds`）—— 全链路
4. **输出守卫单元测试**（`chat_response_guard.py`）—— 规则验证

### Phase 1c —— 剩余模块覆盖（2-3 天项目时间）
- 交易搜索 API 集成测试
- 过滤生成单元+集成测试
- 知识库 API 测试
- E2E smoke test

---

## 七、Golden Data 管理

### 原则
- **版本控制**：所有 golden data 随代码入库
- **可复现**：每次测试应产生相同结果（确定性输入→确定性输出）
- **可审计**：期望输出变更需 diff review

### PoB 解码 Golden Data 获取
1. 从真实游戏中导出几个代表性 Build（战士、法师、弓手各一）
2. 用当前代码跑一次，人工验证结果正确性
3. 将分享码和正确结果入库作为 baseline
4. 后续代码修改后跑 golden test，对比与 baseline 的差异

### 注意事项
- PoE2 游戏版本更新可能导致解码结果变化 —— 那时需要集体更新 golden data
- 记录每个 golden data 的 PoE2 版本号和时间戳

---

## 八、AI 输出测试策略

AI 输出天然非确定性，不能硬编码期望值。方案：

### 8.1 Schema 验证
用 Pydantic schema 验证 AI 输出结构：
```python
def test_ai_homework_output_schema(mock_llm):
    """AI 作业必须返回符合 schema 的 JSON。"""
    result = ai_service.generate_homework(build_data)
    validated = HomeworkResponse(**result)  # 抛异常即测试失败
    assert validated.build_id > 0
```

### 8.2 守卫规则测试
测试 `chat_response_guard.py` 能正确拦截：
- 超出指定格式的输出
- 含敏感内容的输出
- 空值 / 不完整输出

### 8.3 Retry 机制测试
验证 schema 验证失败后触发重试逻辑：
```python
def test_ai_retry_on_invalid_output(mock_llm_fails_first_two):
    """前两次返回非法 JSON，第三次返回合法结果。"""
    result = ai_service.generate_homework(build_data, max_retries=3)
    assert result is not None
```

---

## 九、CI 集成建议

建议后续 GitHub Actions（或 GitLab CI）配置：

```yaml
# .github/workflows/test.yml (草案)
name: Test
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r backend/requirements.txt
      - run: pip install -r backend/tests/requirements-test.txt
      - run: python -m pytest backend/tests/ -v --cov=app --cov-report=term-missing
```

指标门禁（渐进式）：
| 阶段 | 覆盖率底线 | 通过条件 |
|------|-----------|---------|
| Phase 1 完成 | ≥ 50% (核心模块) | 所有测试通过 |
| Phase 2 完成 | ≥ 70% (全模块) | 同上 + lint 通过 |
| v1.0 发布前 | ≥ 80% (全模块) | 同上 + 无高危漏洞 |

---

## 十、风险与应对

| 风险 | 影响 | 应对 |
|------|------|------|
| SQLite vs PostgreSQL 行为差异 | 测试漏过 PG 特定问题 | CI 加一个 PG 模式（用 testcontainers 或 docker） |
| 游戏数据更新导致 golden data 过期 | 测试误报失败 | 每次游戏版本更新后集体 re-baseline |
| LLM mock 不完整 | 无法覆盖 AI Agent 逻辑 | 先测守卫/重试逻辑，用录制回放（vcrpy 风格）测真实 LLM |
| 测试维护成本 | 开发速度下降 | 将测试纳入 review gate，不允许 PR 无测试；但不对简单 getter/setter 强求覆盖 |

---

## 十一、实施路线

```mermaid
gantt
    title 测试体系建设
    dateFormat  YYYY-MM-DD
    axisFormat  %m-%d
    
    section Phase 1a — 基础设施
    创建测试目录结构           :t1, 0, 1d
    编写 conftest.py          :t2, 1d, 1d
    冒烟测试验证运行           :t3, 2d, 1d
    
    section Phase 1b — P0 覆盖
    PoB 解码测试              :t4, 3d, 3d
    实体解析测试              :t5, 4d, 2d
    API 集成测试              :t6, 5d, 3d
    输出守卫测试              :t7, 6d, 2d
    
    section Phase 1c — 剩余覆盖
    交易搜索测试              :t8, 8d, 3d
    过滤生成测试              :t9, 9d, 3d
    知识库测试                :t10, 10d, 2d
    E2E smoke test            :t11, 10d, 2d
```

> 注：以上时间基于项目时间，1 天 = 15 真实分钟。Phase 1a 可在半天项目时间内完成。

---

## 十二、下一步行动

1. **朝露**：确认方案方向，批准 Phase 1a 启动
2. **暮鼓**（后端开发）：Phase 1a 落地 —— 创建目录、conftest、冒烟测试
3. **归鸿**（AI Agent）：Phase 1b 的第 4 项 —— 输出守卫测试
4. **织墨**（PM）：将测试任务排入 sprint，确保与 P0 核心循环对齐
