# AstraLive — Frontend Requirements

> Owner：Frontend Agent  
> 允许修改：`frontend/**`  
> 必须遵守 `contracts/CONTRACTS.md`

## 1. 技术栈

```text
React
Vite
TypeScript 7
Bun
TanStack Query
Zustand
Tailwind CSS
shadcn/ui
Zod
```

统一包管理器：

```text
bun
```

禁止：
- npm
- pnpm
- yarn

必须提交并锁定：
- `bun.lock`

---

## 2. 项目结构

```text
frontend/
├── FRONTEND.md
├── src/
│   ├── app/
│   ├── pages/
│   ├── features/
│   │   ├── avatars/
│   │   ├── voices/
│   │   ├── products/
│   │   ├── rooms/
│   │   └── live-console/
│   ├── components/
│   ├── api/
│   ├── stores/
│   ├── hooks/
│   ├── lib/
│   └── types/
├── public/
└── tests/
```

---

## 3. 页面范围

MVP 只做：

1. Dashboard
2. Avatars
3. Voices
4. Products / KnowledgeBase
5. Live Rooms
6. Live Console

不做：
- 登录注册
- 多租户
- 支付
- 复杂权限
- BI

---

## 4. Server State 与 UI State

### TanStack Query

负责：

```text
avatars
voices
products
knowledgeBases
rooms
sessions
jobs
```

### Zustand

只负责：

```text
sidebar
selectedRoomId
console panel state
preview settings
local UI preferences
```

禁止用 Zustand 保存完整后端业务数据副本。

---

## 5. API Client

核心 DTO 不允许手写两份。

正式开发应从：

```text
contracts/control-api.openapi.yaml
```

生成 TypeScript Client/Types。

前端业务通过统一 API Client 访问 Go。

禁止：

```text
fetch("http://localhost:8080/...")
```

散落在组件里。

---

## 6. 环境变量

至少：

```text
VITE_API_BASE_URL
VITE_ENABLE_DEV_PLATFORM_EVENTS
```

禁止硬编码 IP。

---

## 7. Dashboard

展示：

```text
Control Plane Status
Runtime Status
Active Session Count
Current Session
Recent Runtime Errors
```

MVP 可简单。

---

## 8. Avatar 页面

功能：
- 列表
- 创建
- 查看状态
- Prepare
- 删除
- Job Progress

Avatar 状态显示必须使用 Contract Enum，不自造状态。

---

## 9. Voice 页面

功能：
- Voice 列表
- 新增预置 Voice
- Provider 展示
- 删除

第一版无需录音克隆 UI。

---

## 10. Product 页面

功能：
- 创建商品
- 修改
- 库存
- 价格
- 尺码
- 描述

用于模拟 Tool Calling。

---

## 11. LiveRoom 页面

配置：

```text
name
avatar
voice
knowledgeBase
systemPrompt
```

创建后可进入 Live Console。

---

## 12. Live Console

推荐布局：

```text
┌──────────────────────────────────────────────┐
│ AstraLive Console                            │
├─────────────────────────┬────────────────────┤
│                         │ Session Status     │
│ WebRTC Preview          │ Avatar             │
│                         │ Voice              │
│                         │ Runtime            │
│                         │ FPS / Delay        │
├─────────────────────────┴────────────────────┤
│ [ text input........................ ] Speak │
│ Interrupt                         Stop       │
├──────────────────────────────────────────────┤
│ Event Timeline                               │
└──────────────────────────────────────────────┘
```

---

## 13. Session Start UX

按钮：

```text
Start Live
```

点击：
1. POST start
2. UI 立即进入“Preparing”
3. 禁止重复点击
4. 通过 SSE 等待：
   - ready
   - live
   - failed

不能等待 HTTP 长请求返回“直播已启动”。

---

## 14. Speak UX

输入文本：

```text
欢迎大家来到直播间
```

点击 Speak：

```text
POST utterance
```

返回 `QUEUED`。

Timeline 根据 SSE 更新：

```text
QUEUED
GENERATING
SYNTHESIZING
RENDERING
PLAYING
COMPLETED
```

---

## 15. Interrupt UX

显示：
- Current Utterance
- Priority
- Status

点击 Interrupt：
- POST interrupt
- UI 不自行标记“已打断”
- 等待 SSE `utterance.interrupted`

---

## 16. SSE

统一 Hook：

```text
useLiveSessionEvents(sessionId)
```

负责：
- connect
- reconnect
- heartbeat timeout
- cleanup
- dispatch event

禁止每个页面自己 new EventSource。

---

## 17. WebRTC

统一封装：

```text
useLivePreview(sessionId)
```

职责：
- 建立 PeerConnection
- 显示 Remote Stream
- 断线处理
- Cleanup

WebRTC 媒体允许绕过 Go，但控制仍走 Go。

---

## 18. Mock Platform Event

开发模式显示：

```text
Developer Panel
```

支持输入：

```text
COMMENT: 有 XL 吗？
```

调用：

```text
POST /api/v1/dev/platform-events
```

用于全链路测试。

生产构建默认隐藏。

---

## 19. Error Handling

统一错误组件读取：

```text
code
message
requestId
```

对用户显示友好 message。

开发模式可显示：
- code
- requestId

禁止把堆栈直接暴露给用户。

---

## 20. TypeScript 规则

- `strict: true`
- 不允许核心模块 `any`
- API DTO 来自生成类型
- UI 自有类型可手写
- 使用 discriminated union 处理状态
- Enum 与 Contract 一致

---

## 21. Loading / Empty / Error

每个资源页必须处理：
- Loading
- Empty
- Error
- Retry

---

## 22. 测试

至少：
- API Client mock
- Session Start UI
- SSE Event reducer
- Utterance Timeline
- Interrupt button
- Runtime Error UI
- WebRTC wrapper mock

E2E 由 Integration Agent 负责。

---

## 23. 完成标准

1. `bun install`
2. `bun run build`
3. `bun run test`
4. 页面可在 Mock Backend/Runtime 下使用
5. 无手写重复核心 DTO
6. SSE 正确
7. WebRTC Preview 容器可工作
8. 不直接调用 Internal Runtime API
9. 不修改 Contracts
