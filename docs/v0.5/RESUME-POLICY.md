# Resume Policy — durable-live-1

Agent2是业务状态、持久化、lease、Outbox、journal和Recovery唯一owner。Agent3仅使用冻结请求/响应，不建数据库、迁移、Recovery Coordinator或另一套Session。

| 持久事实 | 场控行为 |
| --- | --- |
| 连续COMPLETED前缀 | 不再认领这些段；从下一个READY开始 |
| 当前ACTIVE/未决attempt/slot被占用 | 等可信完成或Recovery对账；不发第二段 |
| UNKNOWN（即使slot已被隔离清空） | 默认RECOVERING，不跳过、不直接重播 |
| SCRIPT INTERRUPTED | 默认暂停人工处理，不把它当READY |
| COMMENT完整完成/证明中断 | 不推进讲解cursor；可恢复原计划下一READY段 |
| 经批准SKIP_WITH_GAP | 通过Agent2的segment→decision持久映射和快照decision校验跨越；原段不伪造COMPLETED |
| 商品或快照版本变化 | 关闭旧计划准入；先暂停/隔离，再新planId/revision和合法Binding |
| Stop或终态 | 永不自动Resume；迟到证据仅由Agent2归档/统计 |
| 旧epoch请求/证据 | Agent2拒绝当前投影变更；Agent3不按更大Generation猜恢复 |

NextSegment核对真实连续前缀、segmentOrder、hash、scope、resumeSequence和gap引用；不使用最高完成编号推导进度。恢复合法新Session由Agent2/现有Binding服务处理；Session终态不复活。

Manager.Restore每次从持久快照恢复，不依赖Python队列或进程内lastSegment。公平历史和已接纳WAITING评论也必须从Agent2读取。Fake仅存在于`*_test.go`，重建Manager时复用Fake持久对象模拟进程级策略重启；这不是实际PostgreSQL持久化、SIGKILL或guardian故障注入验收。

默认MANUAL_ON_UNKNOWN；SAFE_SCRIPT_NEXT_BOUNDARY仅能继续已证明未开始或已完成后的下一READY段。授权CREATE_NEW_TURN/WAIT_FOR_EVIDENCE等操作由Agent2/操作员恢复服务处理，Agent3不会发明新的恢复权限。本版直接支持安全READY恢复和经批准gap；中断段新话轮重述需Agent4接Agent2操作员恢复入口，不由Manager自动生成重试。
