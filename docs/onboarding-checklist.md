# 工程师 Onboarding Checklist

> **版本**: v1.0
> **负责人**: 织墨 (PM)
> **用途**: 新入职工程师自主完成的环境配置与前置知识清单
> **所有工程师完成本 checklist 后 → 联系远岫分配第一个 Sprint 任务**

---

## 📖 阅读材料（必须阅读，按顺序）

| 顺序 | 文档 | 阅读时间 | 掌握要点 |
|:----:|------|:--------:|---------|
| 1 | **CLAUDE.md** (`/CLAUDE.md`) | ~20min | 完整项目架构、Agent 三层设计、P0 核心流程、各子系统职责 |
| 2 | **CONTEXT.md** (`/CONTEXT.md`) | ~10min | 领域术语：PoB、Build、Trade API 基础概念 |
| 3 | **工程细节文档 2.0** (`PoE2智能工具站-工程开发细节文档（2.0）.md`) | ~15min | 产品需求与功能规格（非技术细节，关注 what 而非 how） |
| 4 | **Sprint 1 Backlog** (`docs/Sprint-01-Backlog.md`) | ~5min | 本期目标和你的具体任务 |
| 5 | **你的岗位相关 ADR** | ~10min | 见下方按角色筛选 |

### 按角色额外阅读

| 角色 | 必读 ADR | 关键代码文件 |
|:----:|---------|------------|
| **后端（暮鼓）** | ADR-0001 (PoB解码) | `backend/app/services/pob_service.py`, `backend/app/api/` |
| **AI Agent（归鸿）** | — | `backend/app/services/chat_agent.py` (38.7KB ReAct), `backend/app/services/chat_tools.py`, `backend/app/services/chat_response_guard.py` |
| **前端（鸣涧）** | — | `frontend/src/app/page.tsx`, `frontend/src/app/chat/page.tsx`, `frontend/src/components/` |
| **数据（拾遗）** | — | `backend/scripts/ggpk/`, `backend/scripts/import_game_data.py`, `backend/scripts/game_graph.py` |

---

## 🔧 环境配置

### 通用

- [ ] Git 已安装，可拉取仓库
- [ ] 已 clone 项目到本地：`git clone https://github.com/TangCuPaiGu233/PoE2LI.git`
- [ ] 已创建个人开发分支

### 后端（暮鼓、归鸿）

- [ ] Python ≥ 3.11 已安装
- [ ] 虚拟环境已创建：`python -m venv venv`
- [ ] 依赖已安装：`pip install -r backend/requirements.txt`
- [ ] `pytest` 可运行：`cd backend && pytest`（Phase 1a 完成后可全绿）
- [ ] （可选）Docker Desktop 已安装

### 前端（鸣涧）

- [ ] Node.js ≥ 18 已安装
- [ ] `cd frontend && npm install` 无报错
- [ ] `npm run dev` 可启动，三页（首页/Chat/Filter）可访问无白屏

### 数据（拾遗）

- [ ] Python ≥ 3.11 已安装
- [ ] 后端虚拟环境已配置
- [ ] PostgreSQL 客户端工具（pgAdmin / DBeaver / psql）

---

## ✅ 前置确认事项

完成阅读和环境配置后，找织墨确认以下事项：

- [ ] 已理解 Sprint 1 目标（"地基打牢"— 测试/评估/诊断，不做新功能）
- [ ] 清楚自己的首任务和交付物
- [ ] 知道技术负责人是**远岫**，质量审核是**半山居**，PM 跟进是**织墨**
- [ ] 知道汇报路径：任务进展 → 织墨；技术问题 → 远岫；质量/安全 → 半山居；紧急 → 朝露

---

## 🆘 遇到问题怎么办

| 问题 | 找谁 | 怎么找 |
|------|:----:|--------|
| 环境配置卡住 | **织墨**（PM） | send_message |
| 技术方案不确定 | **远岫**（架构师） | send_message 远岫 |
| 测试没过不知道为什么 | **半山居**（QA） | send_message 半山居 |
| 不知道当前做什么 | **织墨**（PM） | send_message |
| 任务做完了 | **织墨**（PM） | send_message + 附交付物 |

---

*文档维护：织墨 (PM) | 最后更新：第 1 天 04:08*
