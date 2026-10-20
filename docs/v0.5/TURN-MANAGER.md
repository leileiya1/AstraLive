# Turn Manager — Agent 3

实现：`backend/internal/turnmanager/`。`Decide`是纯策略；`Manager.Step`读取Agent2状态、选择一个业务来源、Claim一次并唤醒已有Outbox。`Manager.Run`接受checkpoint/ingress合并唤醒并每100ms检查一次，不等待观众提问才开始讲解。计划完成后空闲，需新计划才继续；不会循环重播已经确认完成的计划。

| 场控状态 | 含义 |
| --- | --- |
| IDLE | 当前没有有效待执行内容 |
| EXPLAINING | 当前/下一商品段占话轮 |
| YIELD_PENDING | 已接纳评论，但当前段还没有可信完成边界 |
| ANSWERING | 当前/下一来源是Scheduler已选评论 |
| RESUMING | 问答后重新认领下一未完成段 |
| OPERATOR_OVERRIDE | 操作员接管，自动准入暂停 |
| RECOVERING | UNKNOWN、未决attempt、版本变化、Provider不可用或状态不足 |
| STOPPED | Stop意图/tombstone或终态禁止自动讲话；不代表物理输出已全部停止 |

这些是场控投影，不修改既有Session/Utterance FSM。优先处理Stop/操作员屏障；OPERATOR/SYSTEM紧急媒体继续走现有已授权中断路径。普通COMMENT只在业务边界准入，永不FORCE。没有CurrentTurn空闲时继续SCRIPT。

已选择的评论按持久接纳顺序进入下一话轮，不在本模块重新评分、合并或限流。每次最多连续2次回答，或累计本地执行达到8秒，或脚本等待达到12秒，则就绪脚本至少播放1段。之后重置问答预算。预算从Agent2已持久Turn历史计算，Manager重启不重置；已开始的回答不被计时器强截断。默认TTL沿用Scheduler的20秒；配置要求MaxScriptWait<TTL，最大连续回答≤2、累计预算≤8秒。集成需同步两者TTL配置，不给恢复的旧评论重置期限。长回答/模型波动可能超过等待参数，参数是下一话轮准入预算，不是外部时延硬上限。

核心调用序列：RestoreContentPlan → PolicyReader一致性视图 → Decide → 必要时YieldAtSegmentBoundary并重新读取 → Facts预检 → SCRIPT AdmitTurn（COMMENT已由Scheduler适配器Admit）→ ClaimNextTurn → DispatchTurn。Confirm仅调用Agent2验证器；没有本地游标推进。SQL/网络调用不在Scheduler/controller mutex或borrowed SQL事务中执行；Step仅用atomic exclusion拒绝同一实例重入。跨实例互斥仍依赖Agent2 CAS/lease/slot。

PolicyReader是进程内授权repo适配器，必须同run revision提供待答候选、当前Turn、上次脚本以来完整公平历史、Provider和商品版本、经批准gap映射。不是新RPC/SQL存储。缺字段/版本不一致拒绝准入。Agent4接线前本模块无生产入口，默认关闭。
