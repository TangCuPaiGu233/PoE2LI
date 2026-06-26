# 前端技术债审计报告

> 日期：2026-06-26  
> 范围：`frontend/` 全量源码 + 配置  
> 方法：静态代码审计 + 配置审查  
> 目的：输出可直接进入 Sprint 2 backlog 的技术债清单

---

## 一、API 层

### 1.1 API 地址管理不一致（P0）
- **位置**：`src/app/page.tsx:7-12`、`src/app/filter/page.tsx:5-10` 硬编码 `:8000`
- **现状**：`src/lib/apiUrl.ts` 已支持 `NEXT_PUBLIC_API_URL` / 同源 rewrite，但首页与 Filter 页未使用
- **风险**：Docker 生产环境依赖 Next rewrite，直连 `:8000` 在部分部署下失效
- **修复**：统一调用 `apiUrl()`，移除所有 `getApiUrl()` 硬编码函数

### 1.2 请求错误处理不统一（P1）
- **位置**：`src/app/page.tsx:103-109` 对 `/api/builds` 做了对象结构化错误解析，但其他页面（Filter、Chat）未做同类处理
- **风险**：后端返回非预期格式时前端崩溃或提示模糊
- **修复**：抽离统一 `fetchWithError` 工具，所有页面复用

### 1.3 长轮询无退避/取消机制（P1）
- **位置**：`src/app/page.tsx:121-139` 固定 2s 轮询，最多 150 次
- **风险**：无效请求密集；用户离开页面后仍在轮询
- **修复**：改用指数退避 + `AbortController` 随组件卸载取消

### 1.4 聊天 SSE 断连无重连（P1）
- **位置**：`src/app/chat/page.tsx:179-260` 只支持手动重发，不自动重连
- **风险**：弱网下用户需手动重发，体验断裂
- **修复**：增加断连重试次数 + 退避，超过阈值提示“网络异常，请重发”

### 1.5 请求类型安全缺失（P2）
- **位置**：多处 `fetch(...).then(res => res.json())` 未做泛型或 zod 校验
- **风险**：后端字段变更导致前端运行时崩溃
- **修复**：为高频接口定义 TypeScript 接口 + 运行时校验（zod）

---

## 二、路由 & 页面

### 2.1 单文件过重（P1）
- `src/app/page.tsx` 448 行（PoB 输入、轮询、结果渲染、历史侧栏、工具函数）
- `src/app/chat/page.tsx` 671 行（消息流、图片、toolCalls、滚动、输入）
- **风险**：维护成本高，修改输入逻辑需穿越大量无关代码
- **修复**：拆分为 `usePoBSubmit`、`useBuildPolling`、`BuildResultCard`、`ChatInput` 等

### 2.2 页面状态覆盖不全（P1）
- 首页：有 loading/error，但无“空结果”引导（如历史记录为空时）
- Filter 页：下载失败提示单一，未区分 404/500/网络错误
- Chat 页：有 welcome chips，但“首次加载中”态较弱
- **修复**：统一页面级状态机：`idle → loading → success | error | empty`

### 2.3 路由结构待补（P2）
- `/trade` 目前 302 到 `/chat`，缺少独立 Trade 搜索页面
- **风险**：用户从外部链接进入 `/trade` 时上下文丢失
- **修复**：Sprint 2 建设独立 `/trade` 页面

---

## 三、组件层

### 3.1 ChatMarkdown 组件对象不稳定（P1）
- **位置**：`src/components/chat/ChatMarkdown.tsx:137-167`
- **现状**：`components` 对象在 `useMemo` 中每次依赖变化时重建，但闭包内 `wrapChips` 依赖外部状态
- **风险**：ReactMarkdown 在 streaming 场景下可能重复渲染或丢失 chip
- **修复**：将 `wrapChips` 抽为稳定 ref 或 memo 化子组件

### 3.2 PoeEntityChip 类型映射死代码（P1）
- **位置**：`src/components/chat/PoeEntityChip.tsx:18-28`
- **现状**：`TYPE_BORDER`/`TYPE_BADGE` 只覆盖 `item/skill/ascendancy`，但后端可能返回 `passive/node` 等
- **风险**：新类型出现时样式回退到灰色，视觉不一致
- **修复**：增加未知类型默认样式 + 后端枚举对齐

### 3.3 ThinkingPanel 内联样式（P2）
- **位置**：`src/components/chat/ThinkingPanel.tsx:224-262`
- **现状**：用 `<style>` 注入 CSS，与 Tailwind 体系混用
- **修复**：迁移到 `chat-markdown.css` 或专用 CSS module

### 3.4 缺少 Error Boundary（P2）
- **现状**：全项目无 React Error Boundary
- **风险**：运行时异常导致整页白屏
- **修复**：Sprint 2 增加全局 Error Boundary + 降级 UI

### 3.5 ChatMessageImage thumb 参数未使用（P2）
- **位置**：`src/components/chat/ChatMessageImage.tsx:9` `thumb?: boolean`
- **现状**：父组件未传 `thumb`，且内部仅影响 group scale，行为与预期不一致
- **修复**：移除或补充使用场景

---

## 四、构建 & 配置

### 4.1 Next.js rewrite 与直连并存（P1）
- **位置**：`next.config.ts:9-15` 已配置 `/api/*` rewrite
- **现状**：但 `page.tsx`/`filter/page.tsx` 绕过 rewrite 直连 `:8000`
- **风险**：本地开发与生产行为不一致
- **修复**：统一走 rewrite 或 `apiUrl()`

### 4.2 环境变量无校验（P2）
- **现状**：`API_PROXY_TARGET`、`NEXT_PUBLIC_API_URL` 未做必填/格式校验
- **风险**：部署时漏配导致前端请求 127.0.0.1:8000
- **修复**：在 `next.config.ts` 或 `lib/apiUrl.ts` 增加启动时校验

### 4.3 依赖版本 pinned（P2）
- **位置**：`package.json:11-17`
- **现状**：`next`/`react` 固定到 `16.2.6`/`19.2.4`，未使用 `^` 或 `~`
- **风险**：安全补丁需手动升级
- **修复**：改为 `^16`/`^19` + 定期 `npm audit`

### 4.4 构建产物分析缺失（P2）
- **现状**：未配置 `@next/bundle-analyzer`
- **修复**：Sprint 2 增加 bundle 分析，监控 `react-markdown` 等包体积

---

## 五、安全 & 性能

### 5.1 实体图标 URL 未校验（P1）
- **位置**：`src/components/chat/PoeEntityChip.tsx:44,98`
- **现状**：`iconSrc` 直接拼接用户输入 `label`，未校验是否为相对路径或恶意 URL
- **风险**：若后端返回异常 `name`，可能触发 SSRF 或加载恶意资源
- **修复**：后端强制返回相对路径或白名单域名；前端增加 URL 校验

### 5.2 atob 无 Polyfill 检查（P2）
- **位置**：`src/components/chat/ChatMessageImage.tsx:18`
- **现状**：直接使用 `atob`，在部分现代浏览器/Service Worker 中可能不可用
- **修复**：增加 `buffer` polyfill 或使用 `Uint8Array` 解码

### 5.3 未使用懒加载（P2）
- **现状**：`ChatMarkdown`、`PoeEntityChip`、`ThinkingPanel` 均同步加载
- **修复**：对非首屏组件增加 `next/dynamic` 懒加载

### 5.4 CSS 体积（P2）
- **位置**：`src/app/globals.css` 779 行
- **现状**：大量 PoE2 主题 token + 动画，未做 tree-shaking
- **修复**：提取共用 token 到 `@theme`，移除未引用动画

---

## 六、汇总表

| 编号 | 问题 | 维度 | 等级 | 修复建议 |
|:----:|------|:----:|:----:|----------|
| 1 | API 地址硬编码 `:8000` | API | P0 | 统一 `apiUrl()` |
| 2 | 请求错误处理不统一 | API | P1 | 抽离 `fetchWithError` |
| 3 | 长轮询无退避/取消 | API | P1 | 指数退避 + AbortController |
| 4 | SSE 断连无重连 | API | P1 | 断连重试 + 退避 |
| 5 | 请求类型安全缺失 | API | P2 | zod/TS 接口定义 |
| 6 | 单文件过重 | 页面 | P1 | 拆分为 hooks + 小组件 |
| 7 | 页面状态覆盖不全 | 页面 | P1 | 统一状态机 |
| 8 | 路由结构待补 | 页面 | P2 | Sprint 2 建 `/trade` |
| 9 | ChatMarkdown 组件对象不稳定 | 组件 | P1 | memo/ref 稳定化 |
| 10 | PoeEntityChip 类型映射死代码 | 组件 | P1 | 增加默认样式 + 枚举对齐 |
| 11 | ThinkingPanel 内联样式 | 组件 | P2 | 迁移到 CSS module |
| 12 | 缺少 Error Boundary | 组件 | P2 | 全局 Error Boundary |
| 13 | ChatMessageImage thumb 未使用 | 组件 | P2 | 移除或补充使用 |
| 14 | Next rewrite 与直连并存 | 构建 | P1 | 统一 API 调用路径 |
| 15 | 环境变量无校验 | 构建 | P2 | 启动时必填校验 |
| 16 | 依赖版本 pinned | 构建 | P2 | 改 `^` + 定期 audit |
| 17 | 构建产物分析缺失 | 构建 | P2 | 增加 bundle analyzer |
| 18 | 实体图标 URL 未校验 | 安全 | P1 | 后端白名单 + 前端校验 |
| 19 | atob 无 Polyfill | 安全 | P2 | 增加 buffer polyfill |
| 20 | 未使用懒加载 | 性能 | P2 | 非首屏组件 dynamic import |
| 21 | CSS 体积 | 性能 | P2 | tree-shaking + 清理未引用 |

---

## 七、建议实施顺序

1. **立即（P0）**：修复 API 地址硬编码，统一 `apiUrl()`（预计 0.5 天）
2. **Sprint 2 第 1 周**：P1 项批量修复（请求错误处理、长轮询、SSE 重连、单文件拆分、组件稳定化）
3. **Sprint 2 第 2 周**：P2 项治理（类型安全、Error Boundary、环境校验、性能优化）

---

## 八、附录：文件清单

| 文件 | 行数 | 主要问题 |
|------|:----:|----------|
| `src/app/page.tsx` | 448 | 单文件过重、硬编码 API |
| `src/app/chat/page.tsx` | 671 | 单文件过重、SSE 无重连 |
| `src/app/filter/page.tsx` | 271 | 硬编码 API、状态单一 |
| `src/components/chat/ChatMarkdown.tsx` | 177 | 组件对象不稳定 |
| `src/components/chat/PoeEntityChip.tsx` | 144 | 类型映射死代码 |
| `src/components/chat/ThinkingPanel.tsx` | 266 | 内联样式 |
| `src/components/chat/ChatMessageImage.tsx` | 129 | 未使用 prop |
| `src/components/SiteNav.tsx` | 47 | 无 |
| `src/lib/apiUrl.ts` | 13 | 已有正确实现，未被全面采用 |
| `src/lib/chatImage.ts` | 118 | atob 无 polyfill |
| `src/lib/buildHistory.ts` | 53 | 无 |
| `src/app/globals.css` | 779 | 体积大 |
| `next.config.ts` | 20 | rewrite 存在但被绕过 |
| `tsconfig.json` | 35 | 无 |
| `package.json` | 29 | 版本 pinned |

---

*报告结束。可直接复制第 6 章汇总表到 Sprint 2 backlog。*
