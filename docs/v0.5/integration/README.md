# Agent 4 共享接线补丁

基线 main：`7fe5d24810e2df348c58dd7748e97ffbe5cff384`。补丁未应用到 Agent 2 的共享文件。

```sh
git apply --check docs/v0.5/integration/agent-2-shared.patch
# 以下由 Agent 4 在其集成分支执行
git apply docs/v0.5/integration/agent-2-shared.patch
gofmt -w backend/internal/app/service.go backend/internal/eventbus/consumer.go backend/internal/httpapi/server.go
```

补丁内容：

- Service 增加 nil 默认的 Durable Store；阻止已归属 durable 的 Session 走 legacy Start/Speak/Interrupt/Stop。durable Stop 必须使用独立受权的 v0.5 入口。
- eventbus 对 durable Utterance 的 v1 事件只保留观察，避免无 epoch 的旧事件绕过 Journal；保留原 XREADGROUP/XAUTOCLAIM/XACK/DLQ 流程。
- httpapi 允许挂载独立鉴权的 `NewDeployment.Handler`，不使用原 v1 DTO/鉴权中间件解析新协议。
- Runtime 的新开关默认 false；打开时必须提供完整注册器/routers，缺失就拒绝启动。已管理的 Session 不再走旧 v1 控制路径。
- 添加 jsonschema 依赖。

Agent 4 的 main 接线还需建立受信任角色/进程注册，实例化 Store + FactVerifier + Sender，赋给 Service.Durable / Server.DurableHandler，运行 Deployment.Run。Runtime registration 必须按 Session 配置真实 exact-text 执行器、Worker readiness 和 Guardian；不要用测试 probe 作为生产工厂。

此补丁只封住双调度和旧事件旁路，不代替 Guardian 部署或 Provider/Worker 适配。跨进程回答准备日志缺少冻结操作，需要 Agent 1/4 的契约协调；没有协调就保留 COMMENT_QUESTION 拒绝执行。

`python scripts/durable-live/check_integration_patch.py` 会在自建临时源码快照里应用、格式化、跑 Go 回归和 Python 编译，不修改本工作区或其他 Agent worktree。最终证据见 `../agent-2-evidence/final/integration-patch.txt`。这不是完整产品接线验收。
