# Build 详情页 (`/build/[id]/`) QA 测试方案

> **版本**: v1.0  
> **日期**: 2025-01-XX  
> **作者**: QA (磐石)  
> **范围**: 独立 Build 详情页 `/build/[id]/` 的端到端验收测试方案

---

## 一、项目背景

当前首页 (`/`) 已实现了 PoB 代码提交 → Build 创建 → 轮询获取结果 → 展示 Build 详情 + AI 攻略 的完整流程。  
即将开发独立的 Build 详情页路由 `/build/[id]/`，用户通过分享链接直接访问特定 Build 的完整信息。

**参考现有实现**：
- `frontend/src/app/page.tsx` — 首页 Build 展示逻辑（组件复用参考）
- `backend/app/api/builds.py` — Build API 端点（GET/POST/Chat）
- `backend/app/models/schemas.py` — BuildDetail 数据模型

---

## 二、功能验收清单

### 2.1 Positive Cases（正向用例）

| ID | 场景 | 预期行为 | 关联 API |
|----|------|---------|----------|
| F-01 | 通过 URL 参数 `?build=123` 跳转（兼容旧版分享链接格式） | 自动提取 build ID，导航至 `/build/123`，展示对应详情 | `GET /api/builds/{id}` |
| F-02 | 直接访问 `/build/{id}`（如 `/build/42`） | 页面加载该 Build 完整信息 | `GET /api/builds/{id}` |
| F-03 | Build 状态为 `done`（攻略已生成完毕） | 展示完整的 Build 信息：职业等级、属性面板、技能宝石、AI 攻略（含所有折叠区块）、装备列表、天赋树规格 | BuildDetail |
| F-04 | Build 状态为 `pending`（AI 仍在生成） | 展示基础 Build 信息（无 homework），显示加载进度提示 | BuildDetail |
| F-05 | Build 状态为 `failed` | 展示 Build 基础信息 + 错误提示，引导用户重试 | BuildDetail |
| F-06 | 点击 AI 攻略各折叠区块标题 | 展开/收起对应内容（`core_idea`, `core_items`, `budget_alternatives`, `talent_highpoints`, `strength_review`） | 无 |
| F-07 | 点击"在对话里搜装备"链接 | 跳转至 `/chat?build={id}`，携带 build ID 上下文 | 导航 |
| F-08 | 点击"复制链接"按钮 | 将当前 URL 复制到剪贴板，并显示成功反馈 | `navigator.clipboard` |
| F-09 | 点击"在 AI 问答中深入讨论这个 Build"卡片 | 跳转至 `/chat` | 导航 |
| F-10 | 首次访问时无本地历史记录 | 侧边栏"本机历史"区域显示空状态提示 | 无 |
| F-11 | 从首页提交新 Build 后直接跳转到详情页 | 自动加载并展示新建的 Build 详情 | `GET /api/builds/{id}` |
| F-12 | Build 包含多个天赋树规格 (treeSpecs) | 展示所有天赋树，支持切换 | BuildDetail.treeSpecs |
| F-13 | Build 包含多套技能组 (skillSets) | 展示全部技能组及宝石列表 | BuildDetail.skillSets |
| F-14 | Build 包含装备列表 (items) | 按槽位展示装备，显示稀有度标识 | BuildDetail.items |

### 2.2 Negative Cases（异常用例）

| ID | 场景 | 预期行为 | 关联 API |
|----|------|---------|----------|
| N-01 | 访问不存在的 Build ID（如 `/build/999999`） | 显示 404 页面或"Build 不存在"错误提示，提供返回首页按钮 | `GET /api/builds/{id}` → 404 |
| N-02 | 后端服务不可达（网络断开） | 显示网络错误提示，提供"重试"按钮 | 任意 API |
| N-03 | 后端返回非 200 状态码（如 500） | 显示通用错误提示，不崩溃 | 任意 API |
| N-04 | Build 数据不完整（部分字段缺失） | 优雅降级：缺失字段不展示或显示占位符 | `GET /api/builds/{id}` |
| N-05 | homework 为 null（攻略未生成） | 隐藏 AI 攻略区块，不报错 | BuildDetail.homework |
| N-06 | playerStats 为空对象 | 属性面板显示默认值（0）或不展示 | BuildDetail.playerStats |
| N-07 | gems 列表为空 | 隐藏技能宝石区块 | BuildDetail.skillSets |
| N-08 | items 列表为空 | 隐藏装备区块 | BuildDetail.items |
| N-09 | 无效 build ID 格式（如 `/build/abc`） | 显示参数错误提示，或重定向到首页 | Next.js 路由 |
| N-10 | 复制链接失败（权限被拒） | 静默失败，不阻塞页面功能 | `navigator.clipboard` |

---

## 三、UI/UX 检查项

### 3.1 响应式布局

| ID | 断点 | 检查内容 |
|----|------|---------|
| U-01 | ≥1280px (Desktop) | 双列布局：左侧主内容 + 右侧固定侧边栏（历史列表），最大宽度 `78rem` |
| U-02 | 768px–1279px (Tablet) | 侧边栏历史列表折叠或移至底部，保持可读性 |
| U-03 | <768px (Mobile) | 单列堆叠布局，所有网格改为 `grid-cols-1` |
| U-04 | 极窄屏 (<360px) | 统计卡片自适应缩小，文字不换行溢出 |

### 3.2 加载态

| ID | 场景 | 检查内容 |
|----|------|---------|
| L-01 | 页面初始加载（SSR 或 CSR） | 显示骨架屏或加载动画，不白屏 |
| L-02 | API 响应期间 | 全局 loading spinner，禁用交互按钮 |
| L-03 | 折叠区块展开 | 如有懒加载内容，显示渐显动画 |
| L-04 | 长时间等待（>5s） | 显示"加载中…"进度提示，避免用户困惑 |

### 3.3 空态

| ID | 场景 | 检查内容 |
|----|------|---------|
| E-01 | Build 存在但无 homework | 显示"AI 攻略生成中…"提示，附预计时间 |
| E-02 | Build 不存在 | 404 页面，含返回首页按钮和搜索入口 |
| E-03 | 无技能宝石 | 不展示宝石区块，或显示"暂无技能宝石" |
| E-04 | 无装备数据 | 不展示装备区块 |
| E-05 | 无本地历史记录 | 显示"暂无记录" |

### 3.4 错误态

| ID | 场景 | 检查内容 |
|----|------|---------|
| Er-01 | API 请求失败 | 红色边框的错误提示框（参考首页 `ninja-panel-accent` 样式） |
| Er-02 | 后端返回结构化错误 (`ErrorResponse`) | 展示 `error` 和 `reason` 字段，格式友好 |
| Er-03 | 前端渲染错误 | 错误边界 (Error Boundary) 捕获，显示降级 UI |
| Er-04 | 剪贴板权限被拒 | 静默失败，不弹窗报错 |

### 3.5 可访问性 (Accessibility)

| ID | 检查内容 |
|----|---------|
| A-01 | 所有交互元素有 `aria-label` 或可访问名称 |
| A-02 | 折叠区块使用 `<details>` 或 `aria-expanded` 管理状态 |
| A-03 | 颜色对比度符合 WCAG AA（暗色主题下特别注意金色文字可读性） |
| A-04 | 键盘导航：Tab 顺序合理，焦点可见 |
| A-05 | 图片/图标有 `alt` 或 `aria-hidden` |

---

## 四、边界条件

### 4.1 数据边界

| ID | 场景 | 预期行为 |
|----|------|---------|
| B-01 | 极长文本（homework 单段 > 5000 字符） | 文本不换行溢出时用 `whitespace-pre-line` 保留换行，必要时截断 + "展开全文" |
| B-02 | 大量技能宝石（>50 个） | 使用横向滚动或分页展示，避免页面过长 |
| B-03 | 大量装备（>30 件） | 分组展示（武器/防具/饰品），每组分页或折叠 |
| B-04 | 数值极大（生命 > 100000） | 使用 `formatNum` 格式化（K/M 后缀） |
| B-05 | 特殊字符（emoji、CJK、Unicode 全角） | 正确渲染，不出现乱码 |
| B-06 | 空字符串字段（`className=""`） | 显示占位符如"未知职业" |
| B-07 | 所有 stats 为 null/undefined | 显示默认值 0，不崩溃 |

### 4.2 并发与网络边界

| ID | 场景 | 预期行为 |
|----|------|---------|
| C-01 | 同一 Build 被多标签页同时访问 | 每个标签页独立请求，无冲突 |
| C-02 | 快速连续刷新页面 | 不产生重复请求，debounce 或 cache |
| C-03 | 网络中断后恢复 | 自动重试机制（最多 3 次），给用户明确提示 |
| C-04 | 慢速网络（3G） | 骨架屏持续显示，loading 超时提示 |
| C-05 | API 响应延迟（>10s） | 显示"生成中…"状态，不阻塞页面渲染 |
| C-06 | 页面停留超过 Celery 任务超时（2min+） | Build 从 pending → done 自动刷新（轮询或 SSE） |
| C-07 | Build 在加载过程中被删除 | 显示 410 Gone 或 404 |

### 4.3 客户端边界

| ID | 场景 | 预期行为 |
|----|------|---------|
| D-01 | localStorage 已满 | 历史条目截断到最近 30 条（已有逻辑），不报错 |
| D-02 | localStorage 不可用（隐私模式） | 静默跳过历史读写 |
| D-03 | Cookie 被禁用 | 不影响功能（当前为无状态 API） |
| D-04 | JS 被禁用 | 降级为服务端渲染基本内容，无交互 |

---

## 五、跨浏览器检查项

| 浏览器 | 版本范围 | 重点检查 |
|--------|---------|---------|
| Chrome | 最新 ±2 大版本 | 主测试浏览器，全面检查 |
| Firefox | 最新 ±2 大版本 | CSS Grid 兼容性、`whitespace-pre-line` 渲染 |
| Safari (macOS) | 最新 ±2 大版本 | `-webkit-` 前缀、backdrop-filter 兼容性 |
| Safari (iOS) | 最新 ±2 大版本 | 移动端布局、触摸交互、剪贴板权限 |
| Edge | 最新 ±2 大版本 | Chromium 内核一致性 |
| Samsung Internet | 最新 | Android 小众浏览器覆盖 |

**CSS 特性兼容性检查**：
- `clamp()` 函数（标题字号缩放）
- CSS 自定义属性（`var(--xxx)`）
- `backdrop-filter`（导航栏毛玻璃效果）
- `radial-gradient` 背景（暗色氛围效果）
- `::-webkit-scrollbar` 样式

---

## 六、性能基准

### 6.1 页面加载时间

| 指标 | 目标值 | 测量方式 |
|------|--------|---------|
| FCP (First Contentful Paint) | ≤ 1.5s (Lighthouse) | Chrome DevTools / Lighthouse |
| LCP (Largest Contentful Paint) | ≤ 2.5s | Chrome DevTools / Lighthouse |
| TTI (Time to Interactive) | ≤ 3.5s | Chrome DevTools / Lighthouse |
| CLS (Cumulative Layout Shift) | ≤ 0.1 | Chrome DevTools / Lighthouse |
| INP (Interaction to Next Paint) | ≤ 200ms | Chrome DevTools |

### 6.2 API 响应时间

| 端点 | 目标值 | 说明 |
|------|--------|------|
| `GET /api/builds/{id}` (done) | ≤ 500ms | 含完整 BuildDetail + homework |
| `GET /api/builds/{id}` (pending) | ≤ 200ms | 仅基础 build 数据 |
| `GET /api/builds/{id}` (not found) | ≤ 200ms | 404 快速返回 |

### 6.3 资源大小

| 资源 | 预算上限 |
|------|---------|
| 首屏 JS bundle | ≤ 150KB (gzip) |
| 首屏 CSS | ≤ 50KB (gzip) |
| 首屏请求数 | ≤ 8（不含字体 CDN） |
| 总页面大小 | ≤ 500KB |

### 6.4 关键路径优化检查

- [ ] 是否使用 Next.js 服务端渲染 (SSR) 或静态生成 (SSG) 减少 FCP
- [ ] Build 数据是否可缓存（`Cache-Control` 头设置）
- [ ] 图片/资产是否有适当的 lazy loading
- [ ] 字体是否使用 `display=swap` 避免 FOIT

---

## 七、自动化测试建议

### 7.1 E2E 测试（推荐 Playwright）

**选型理由**：
- Next.js 16 对 Playwright 集成更成熟
- 支持多浏览器引擎（Chromium/Firefox/WebKit）
- 内置截图/视频录制，便于调试
- 可模拟网络条件（3G、离线等）

**测试用例覆盖**：

```
e2e/build-detail.spec.ts
├── ✓ 访问 /build/{valid-id} 展示完整信息
├── ✓ 访问 /build/{invalid-id} 展示 404
├── ✓ 访问 /build/{nonexistent-id} 展示 404
├── ✓ 点击折叠区块展开/收起
├── ✓ 点击"复制链接"成功复制
├── ✓ 点击"在对话里搜装备"跳转 /chat
├── ✓ 加载 pending 状态 Build 显示加载提示
├── ✓ 网络超时后重试机制
├── ✓ 移动端响应式布局验证
└── ✓ 无障碍键盘导航测试
```

**Playwright 配置建议**：
```typescript
// playwright.config.ts
{
  testDir: './e2e',
  projects: [
    { name: 'chromium', use: { browserName: 'chromium' } },
    { name: 'firefox', use: { browserName: 'firefox' } },
    { name: 'webkit', use: { browserName: 'webkit' } },
  ],
  use: {
    viewport: { width: 1280, height: 720 },
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  webServer: {
    command: 'npm run dev',
    port: 3000,
    reuseExistingServer: !process.env.CI,
  },
}
```

### 7.2 集成测试（推荐 React Testing Library + Vitest/Jest）

**组件测试覆盖**：

```
tests/components/
├── BuildDetailPage.test.tsx          # 页面组件
│   ├── ✓ 渲染 done 状态的完整 Build
│   ├── ✓ 渲染 pending 状态显示加载提示
│   ├── ✓ 渲染 failed 状态显示错误
│   ├── ✓ 404 时展示错误页面
│   └── ✓ 空数据时优雅降级
├── StatCard.test.tsx               # 属性统计卡片
│   ├── ✓ 正确格式化数值 (K/M 后缀)
│   ├── ✓ 空值显示 0
│   └── ✓ 超大数值正确处理
├── CollapsibleBlock.test.tsx       # 可折叠区块
│   ├── ✓ 默认展开/收起
│   ├── ✓ 点击切换展开状态
│   ├── ✓ 空 content 不渲染
│   └── ✓ 长文本正确换行
├── GemChip.test.tsx                # 宝石标签
│   └── ✓ 渲染名称 + 等级
└── ShareLink.test.tsx              # 分享链接
    └── ✓ 正确构造分享 URL
```

### 7.3 单元测试

**测试覆盖范围**：

```
tests/unit/
├── formatNum.test.ts               # 数字格式化函数
│   ├── ✓ 0 → "0"
│   ├── ✓ 1500 → "1.5K"
│   ├── ✓ 1500000 → "1.5M"
│   └── ✓ NaN/null → "0"
├── buildHistory.test.ts            # 本地历史记录操作
│   ├── ✓ addLocalBuildHistory 追加并去重
│   ├── ✓ MAX_ENTRIES 限制 30 条
│   └── ✓ localStorage 不可用时不报错
├── schemas.test.ts                 # API 数据校验
│   ├── ✓ BuildDetail 字段完整性
│   └── ✓ 可选字段的默认值
└── validation.test.ts              # PoB 输入验证
    ├── ✓ 有效 pobb.in URL
    ├── ✓ 有效 poe.ninja URL
    ├── ✓ 有效 base64 代码
    └── ✓ 无效输入拒绝提交
```

### 7.4 API 测试

```
tests/api/
├── builds.test.ts                  # Build API 端点
│   ├── ✓ POST /api/builds 创建成功
│   ├── ✓ GET /api/builds/{id} 返回完整数据
│   ├── ✓ GET /api/builds/{id} 404 不存在
│   ├── ✓ POST /api/builds/{id}/chat 发送问题
│   └── ✓ 并发请求不产生竞态条件
└── schemas.test.ts                 # Pydantic schema 校验
    ├── ✓ 必填字段缺失时返回 422
    └── ✓ 类型错误时返回 422
```

### 7.5 性能测试

```
tests/performance/
├── lighthouse-ci.test.ts           # Lighthouse CI
│   ├── ✓ FCP ≤ 1.5s
│   ├── ✓ LCP ≤ 2.5s
│   ├── ✓ CLS ≤ 0.1
│   └── ✓ 无障碍评分 ≥ 90
└── api-response-time.test.ts       # API 响应时间
    ├── ✓ GET /api/builds/{id} ≤ 500ms (p95)
    └── ✓ 并发 10 请求不超时
```

---

## 八、测试环境与数据准备

### 8.1 测试数据

| 类型 | 构造方式 | 用途 |
|------|---------|------|
| 正常 Build | 使用已知有效的 PoB 分享码 | 正向用例 |
| Pending Build | 创建后不等待 Celery 完成 | 加载态测试 |
| Failed Build | 手动修改 DB 状态字段 | 错误态测试 |
| 404 Build | 使用不存在的 ID | 异常用例 |
| 边界数据 | 注入极长 homework / 大量宝石 | 边界条件测试 |

### 8.2 Mock 策略

- **开发/测试环境**：使用 MSW (Mock Service Worker) 拦截 API 请求
- **CI 环境**：启动 mock backend 或使用 VCR 录制-回放
- **性能测试**：使用真实后端 + 网络限速模拟

---

## 九、测试执行计划

| 阶段 | 内容 | 执行人 | 时机 |
|------|------|--------|------|
| P0 | 功能验收（正向 + 异常） | 开发自测 + QA | 开发完成后 |
| P1 | UI/UX 检查（响应式 + 可访问性） | QA | P0 通过后 |
| P2 | 边界条件 + 性能基准 | QA | P1 通过后 |
| P3 | 跨浏览器兼容 | QA | P2 通过后 |
| P4 | 自动化测试编写 + CI 集成 | QA + 开发 | 回归测试 |

---

## 十、风险与注意事项

1. **Celery 异步任务依赖**：测试 pending/failed 状态需要控制 Celery worker 行为，建议在测试中 mock 或手动修改 DB 状态
2. **Next.js 16 兼容性**：确认 `build/[id]/page.tsx` 的路由参数读取方式（`params: Promise<{id: string}>` vs 同步）
3. **localStorage 隔离**：E2E 测试需注意不同浏览器实例间的 localStorage 隔离
4. **分享链接格式变更**：如果 `/build/[id]/` 是全新路由而非首页的 `?build=` 查询参数，需确保旧链接兼容性
5. **SSE/轮询策略**：如果 pending 状态使用 SSE 而非轮询，测试方案需调整实时性验证部分

---

## 附录：与首页功能的差异对照

| 功能 | 首页 (`/`) | 详情页 (`/build/[id]/`) |
|------|-----------|------------------------|
| PoB 输入 | ✅ 有 | ❌ 无（纯展示） |
| 历史记录侧栏 | ✅ 本机 localStorage | ⚠️ 可选（可省略或简化） |
| AI 攻略展示 | ✅ 折叠区块 | ✅ 折叠区块（复用组件） |
| 属性面板 | ✅ | ✅ |
| 技能宝石 | ✅ | ✅ |
| 装备列表 | ❌ 无 | ✅ 新增 |
| 天赋树 | ❌ 无 | ✅ 新增 |
| 分享链接 | ✅ 复制链接 | ✅ 复制链接（同） |
| 404 处理 | ❌ 不适用 | ✅ 新增 |
| Chat 入口 | ✅ | ✅ |
