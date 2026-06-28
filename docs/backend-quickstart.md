# Backend Quickstart

PoE2LI 后端 FastAPI 应用启动与验证指南。

## 1. 安装依赖

```bash
cd backend
pip install -r requirements.txt
```

## 2. 启动服务

```bash
cd backend
python -m uvicorn app.main:app --reload --port 8000
```

服务默认监听 `http://localhost:8000`。

## 3. 健康检查

```bash
curl http://localhost:8000/health
```

预期响应：

```json
{"status": "ok"}
```

## 4. 环境变量

如需要自定义配置，可通过环境变量覆盖：

- `DATABASE_URL` — 数据库连接字符串（默认 `postgresql://poe2li:poe2li_secret@postgres:5432/poe2li`）
- `CHAT_RUNTIME` — 聊天运行时模式：`legacy` 或 `orchestrator`（默认 `legacy`）

## 5. 备注

- CORS 已配置为允许所有来源，前端开发服务器可直接调用后端接口。
- 启动时自动创建数据库表（`Base.metadata.create_all`）。
- 如需在 CI/CD 中验证，请确保构建环境已安装 Python 3.10+ 及 `requirements.txt` 中全部依赖。
