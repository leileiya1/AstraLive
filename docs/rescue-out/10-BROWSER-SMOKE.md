# 10 — 浏览器实测（默认模式，本地隔离栈，2026-10-20）

## 怎么启动

```sh
scripts/run-local-isolated.sh
```

然后打开 http://127.0.0.1:18081 。脚本在全新临时目录里启动私有 PostgreSQL/Redis、Go Backend（:18080）、真实 Runtime（Mock AI，`MOCK_MEDIA=false`，WebRTC 可用，:18000）和前端+同源代理（:18081）；Ctrl-C 后全部停止并删除。不连 school-linux、不用共享数据库、不用 GPU、`RTMP_ENABLED=false`（不推流），Durable LIVE 仍关闭。桌面 App 里也可以用 `.claude/launch.json` 的 `astralive-local` 在浏览器面板启动。

## 实测结果（在 App 内置浏览器中操作）

| 步骤 | 结果 |
| --- | --- |
| Dashboard | Control Plane `UP` |
| 创建 Avatar（MOCK）/ Voice / 商品 / 直播间（API） | 全部 201，直播间列表显示 |
| Live Console → 创建 Session → Start Live | Session `LIVE`，Runtime events `connected` |
| WebRTC | `Media: connected`；浏览器实测 audio+video 两条 live track，约 31 秒解码 **773 帧**（256×256，未暂停）。画面为黑色是 MOCK Avatar 的输出，不是故障 |
| Speak（“欢迎大家来到直播间……”） | utterance → `COMPLETED`，无 Runtime 错误 |

## 实测中发现并修复的问题

- **弹幕互动面板在未登录时每秒轮询 2–3 次并永远收到 401**（原 v0.4 前端缺陷）。修复：收到 401/403 后停止轮询，保留错误提示，登录后重新挂载即恢复（`frontend/src/features/live-console/InteractionPanel.tsx`）。新测试 `stops polling after an authentication refusal…` 在修复前失败（5 秒内 6 次请求），修复后通过；真实浏览器中 8 秒直播只发出 1 次请求（修复前同等时间约 20 次）。
- 其它控制台记录：`/api/v0.3/config/me` 404（本地栈未挂载用户配置中心）与启动前 2 次空响应，均不影响直播主流程；未修改。

## 不代表什么

这是**默认（v0.4）模式**的回归实测，证明合并后的 main 没有破坏原有直播链路。它**不是** Durable LIVE v2 的演示：v2 在阶段 6（CPU 端到端）完成前无法在浏览器中端到端运行；真实 GPU 数字人/真实 TTS/RTMP 平台推流属于阶段 7。
