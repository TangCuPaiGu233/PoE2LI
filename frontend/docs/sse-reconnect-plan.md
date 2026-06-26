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

### 3.1 将 SSE 逻辑抽为 `useSSEStream` hook

**原因**：
- `send()` 当前 160 行，已包含消息构建、流解析、事件处理
- 抽离后可独立测试重连逻辑
- 保持 `send()` 只负责"发起请求"

**Hook 接口**：
```ts
function useSSEStream(options: {
  onThinking: (text: string) => void;
  onToolUse: (tc: ToolCallInfo) => void;
  onToolResult: (result: { name: string; ok: boolean; preview: string }) => void;
  onAnswer: (chunk: string) => void;
  onTradeResult: (result: TradeResult) => void;
  onSources: (sources: { type: string; preview: string }[]) => void;
  onFollowUps: (questions: string[]) => void;
  onDone: () => void;
}): {
  send: (history: ApiMsg[], images?: string[]) => Promise<void>;
  abort: () => void;
  reconnectAttempt: number;
  networkError: string | null;
}
```

### 3.2 重连状态管理

在 `ChatPage` 中：
```ts
const [reconnectAttempt, setReconnectAttempt] = useState(0);
const [networkError, setNetworkError] = useState<string | null>(null);
```

在 `useSSEStream` 内部：
```ts
const reconnectAttemptRef = useRef(0);
const maxRetries = 4;

async function connectWithRetry(history: ApiMsg[], signal: AbortSignal) {
  while (reconnectAttemptRef.current < maxRetries) {
    try {
      await connect(history, signal); // 原有 SSE 逻辑
      reconnectAttemptRef.current = 0; // 成功则重置
      setNetworkError(null);
      return;
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") throw e;
      if (reconnectAttemptRef.current >= maxRetries - 1) {
        setNetworkError("网络异常，请重发");
        throw e;
      }
      const delay = 2 ** reconnectAttemptRef.current * 1000;
      await new Promise(r => setTimeout(r, delay));
      reconnectAttemptRef.current += 1;
      setReconnectAttempt(reconnectAttemptRef.current);
    }
  }
}
```

### 3.3 取消机制

- `abortRef` 已在组件卸载时调用 `abort()`
- 重连循环检查 `signal.aborted`，若被取消则立即退出
- 组件卸载时 `useEffect` cleanup 调用 `abort()`

### 3.4 UI 反馈

在 Chat 输入区上方增加重连提示：
```tsx
{networkError && (
  <div className="text-xs text-red-400 mb-2">
    ⚠ {networkError}
  </div>
)}
```

重连中显示轻量 loading：
```tsx
{reconnectAttempt > 0 && streaming && (
  <div className="text-xs text-[var(--ninja-text-dim)]">
    正在重连... ({reconnectAttempt}/4)
  </div>
)}
```

---

## 4. 与后端重试的边界

| 层级 | 处理内容 | 负责方 |
|------|----------|--------|
| 前端传输层 | 网络断开、连接超时 | 本方案 |
| 后端应用层 | 5xx、LLM 超时、重试 | 归鸿 R-03/R-04 |
| 前端业务层 | 4xx、字段错误 | 保持现状 |

前端重连只处理**传输层**断开，不处理后端返回的业务错误码。

---

## 5. 实施步骤

1. **抽离 `useSSEStream` hook**：将 `send()` 内的 SSE 读取逻辑移入 hook
2. **增加重连状态**：`reconnectAttempt`、`networkError`
3. **实现指数退避重连**：`connectWithRetry` 循环
4. **增加 UI 提示**：重连中/失败提示
5. **验证**：Dev 模式模拟断网，确认重连行为

---

## 6. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 重连时重复消息 | 后端 SSE 幂等性保障（后端 R-03 负责） |
| 重连延迟累积 | 最大 4 次，最长 15s，可控 |
| 内存泄漏 | AbortController + cleanup 确保取消 |

---

*方案结束，等待 review 后编码。*
