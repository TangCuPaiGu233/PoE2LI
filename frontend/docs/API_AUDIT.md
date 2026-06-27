# 前端 API 对接审计（Sprint-01 FE-02）

> 目标：列出当前前端对后端真实 API 的对接状态、硬编码/模拟数据位置、缺口与优先级。
> 说明：本期不新增功能，仅输出审计结果，供后续 FE-03 / Sprint 2 实施参考。

## 一、总体结论

| 页面 | 核心 API | 当前状态 | 结论 |
|------|----------|----------|------|
| `/` 首页（PoB） | `POST /api/builds`、`GET /api/builds/:id` | 已对接真实后端 | ✅ 已接通 |
| `/chat` | `POST /api/chat`（SSE） | 已对接真实后端 | ✅ 已接通 |
| `/filter` | `GET /api/filter/download` | 已对接真实后端 | ✅ 已接通 |

## 二、共性基础设施

### 2.1 API 地址方案
- `frontend/src/lib/apiUrl.ts`：支持 `NEXT_PUBLIC_API_URL`，默认同源（Next rewrite）。
- `/chat` 页面通过 `frontend/src/app/api/chat/route.ts` 走 Next API Route 代理，再转发到 `API_PROXY_TARGET`。
- 首页和 Filter 页**未走** Next API Route，直接请求后端地址。

### 2.2 潜在不一致点（P1）
- `apiUrl()` 默认返回空字符串表示同源 rewrite，但首页与 Filter 页硬编码了 `:8000` 端口直连。
- 在 Docker/生产环境里，推荐通过 Next rewrite 或环境变量控制，避免端口耦合。

## 三、页面级缺口清单

### 3.1 首页 `page.tsx`

| 缺口 | 类型 | 优先级 | 说明 |
|------|------|:------:|------|
| API 地址直连 `:8000` | 配置 | P1 | 与 `apiUrl()` 并存，部署环境需切换；建议统一走同一函数 |
| 轮询固定 2s、最多 150 次 | 体验 | P2 | 可用 SSE/WebSocket 或增加退避策略降低无效请求 |
| 空结果/失败提示较简单 | 体验 | P2 | 当前只展示“AI 生成失败/超时”，缺少可操作引导 |
| 历史仅 localStorage | 数据 | P2 | 无服务端持久化与多设备同步（非本期需求） |

### 3.2 Chat 页 `chat/page.tsx`

| 缺口 | 类型 | 优先级 | 说明 |
|------|------|:------:|------|
| 空对话引导（welcome chips） | 体验 | P0 | FE-03 范围项 |
| loading 状态（发送中/生成中） | 体验 | P0 | FE-03 范围项 |
| 网络错误 / 502 fallback | 体验 | P0 | FE-03 范围项 |
| 滚动行为优化 | 体验 | P0 | FE-03 范围项 |
| 消息列表 671 行、单文件耦合 | 维护 | P2 | 本期不做大重构；Sprint 2 拆分 |
| 交易卡片（TradeMatchCard） | 功能 | P1 | 聊天内已能展示，但缺少独立 Trade 页面 |

### 3.3 Filter 页 `filter/page.tsx`

| 缺口 | 类型 | 优先级 | 说明 |
|------|------|:------:|------|
| API 地址直连 `:8000` | 配置 | P1 | 同首页，建议统一 |
| 规则与教程静态文案 | 内容 | P2 | 当前无可配置化/动态化需求 |
| 下载失败提示较简 | 体验 | P2 | 可增加更明确的错误类型提示 |
| 无生成/扫描按钮 | 产品 | P1 | HANDOVER 指出“前端还没有对应的搜索 UI 页面”，但 Filter 当前是模板下载，非用户触发生成 |

## 四、真实数据流接通情况

```
用户输入 PoB 码 → POST /api/builds → 后端解码 → 返回 build id → 前端轮询 GET /api/builds/:id → 生成攻略后渲染
用户输入聊天消息 → POST /api/chat → SSE → 前端分帧解析并渲染
用户点击下载过滤器 → GET /api/filter/download → 浏览器下载文件
```

## 五、后续建议

1. **优先统一 API 地址获取**：首页与 Filter 页统一使用 `apiUrl()`，避免硬编码端口。
2. **FE-03 落地顺序**：空状态/loading/错误/滚动，按 P0 逐项实现，控制范围不扩散到重构。
3. **Sprint 2 候选**：
   - 独立 Trade 搜索 UI 页面
   - Chat 页面拆分（Messages / Input / ThinkingPanel）
   - 首页轮询改为 SSE 或 Server-Sent Events push
