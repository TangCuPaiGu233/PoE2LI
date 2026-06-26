# SSE 断连重试机制方案

> 对应技术债 #1.4（P1）  
> 范围：`src/app/chat/page.tsx` `send()` 中的 SSE 流式读取逻辑  
> 约束：不引入新依赖，仅处理传输层断开

---

## 1. 现状分析

当前 `send()`（`src/app/chat/page.tsx:179-337`）的 SSE 流程：

```
用户发送 → 创建 AbortController → fetch POST /api/chat
  → resp.body.getReader() → while(true) reader.read()
    → 解析 SSE 事件 → 更新 messages/thinking/toolCalls
  → 异常捕获：AbortError 静默退出，其他错误写入 "网络错误: ..."
```

**问题**：
- `reader.read()` 抛出网络异常后直接终止，无重连
- 用户弱网下需手动重发，体验断裂
- 已有 `AbortController` 可复用为取消机制

---

## 2. 重连机制设计

### 2.1 状态机

```
idle → connecting → streaming → (断开?) → reconnecting → streaming
                                    ↘ exceeded → failed(展示提示)
```

新增状态：
- `reconnectAttempt: number` — 当前重连次数（0 开始）
- `maxRetries: 4` — 最大重连次数
- `networkError: string | null` — 超过阈值后的错误提示

### 2.2 重连触发条件

仅以下情况触发重连：
1. `fetch()` 抛出 `TypeError`（网络断开）
2. `reader.read()` 抛出 `TypeError`（流传输中断）
3. `response.ok === false` 且状态码为 5xx/网络错误

**不触发重连**：
- 用户主动 `AbortError`（新消息/离开页面）
- 4xx 客户端错误（如 401/403）
- 后端返回业务错误码（由后端 R-03/R-04 处理）

### 2.3 指数退避策略

| 第 N 次重连 | 延迟 | 说明 |
|:-----------:|:----:|------|
| 1 | 1s | 瞬时抖动 |
| 2 | 2s | 短退避 |
| 3 | 4s | 中退避 |
| 4 | 8s | 长退避 |
| >4 | — | 放弃，展示提示 |

退避公式：`delay = 2^(attempt-1) * 1000 ms`

### 2.4 消息保留策略

重连时**不重置** `messages`：
- 已有用户消息和 assistant 草稿保留
- 重连成功后继续向最后一个 assistant 消息追加内容
- 重连失败后 assistant 草稿保留错误提示

---

## 3. 实现方案

### 3.1 在 `send()` 内直接加重连循环

保持 `send()` 结构，新增：
```ts
const [reconnectAttempt, setReconnectAttempt] = useState(0);
const [networkError, setNetworkError] = useState<string | null>(null);
const reconnectRef = useRef(0);

// 将原有 try/catch 内的 SSE 逻辑抽为 connect()
async function connect() { ... }

// 重连循环
let retry = 0;
const maxRetries = 4;
while (retry < maxRetries) {
  try {
    await connect();
    setReconnectAttempt(0);
    setNetworkError(null);
    break;
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") return;
    retry += 1;
    if (retry >= maxRetries) {
      setNetworkError("网络异常，请重发");
      return;
    }
    setReconnectAttempt(retry);
    await new Promise(r => setTimeout(r, 2 ** (retry - 1) * 1000));
  }
}
```

### 3.2 UI 反馈

在输入区上方增加：
```tsx
{networkError && <div className="text-xs text-red-400">⚠ {networkError}</div>}
{reconnectAttempt > 0 && streaming && (
  <div className="text-xs text-dim">正在重连... ({reconnectAttempt}/4)</div>
)}
```

---

## 4. 与后端重试的边界

| 层级 | 处理内容 | 负责方 |
|------|----------|--------|
| 前端传输层 | 网络断开、连接超时 | 本方案 |
| 后端应用层 | 5xx、LLM 超时、重试 | 归鸿 R-03/R-04 |
| 前端业务层 | 4xx、字段错误 | 保持现状 |

---

## 5. 实施步骤

1. 在 `ChatPage` 增加 `reconnectAttempt`/`networkError` 状态
2. 将 `send()` 内 SSE 逻辑抽为 `connect()`
3. 增加 `while (retry < maxRetries)` 重连循环
4. 增加 UI 提示
5. `npm run build` + 手动断网验证

---

## 6. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 重连时重复消息 | 后端 SSE 幂等性保障（后端 R-03 负责） |
| 重连延迟累积 | 最大 4 次，最长 15s，可控 |
| 内存泄漏 | AbortController + cleanup 确保取消 |

---

*方案结束，approved 后编码。*
