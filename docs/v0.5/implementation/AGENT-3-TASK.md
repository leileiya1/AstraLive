# Agent3 — semantic streaming and Turn task package

状态：任务包已准备，未在本轮派发/启动。使用原AstraLive-agent-3 Worktree/现有分支。先同步并记录[baseline](../IMPLEMENTATION-BASELINE.md)开工pin、冻结SHA/digest和[ownership](ownership.json)。

## 独占范围与依赖

`backend/internal/contentplan/**`、`backend/internal/turnmanager/**`及其测试属于Agent3。可在其内增加隔离v2子包；不另建Scheduler、Session、Utterance、媒体slot或DB。现有Comment Scheduler的选题继续复用；`backend/internal/interaction/scheduler.go` 修改提交patch/说明给Agent4串行集成，不直接争写。

消费Agent4统一wire，持久/Authority依赖Agent2，事实工具与Session/Binding装配、Runtime共享入口由Agent4提供。可先用明确Mock对端测试策略与回压，不能复制DTO/SQL或把Mock标为真实互操作。Python纯语义模块需要扩展时先由Agent4登记路径，不改session.py/main.py/Journal等热点。

## 分阶段交付

1. 保守中文完整语义单元：数字、价格、单位、否定/条件/比较不被断开；不靠句号机械拆分掩盖不完整断言。首个安全单元不等LLM EOF，Token/assembler/lookahead必须有界并反压上游；无法安全分句fail-closed。
2. 每个Artifact保存实际回答正文、textHash/artifactHash、商品快照及完整事实依赖；问题requestHash不可替代答案Hash。事实查询复用既有商品事实工具/DeepSeek路径，不用旧库存价格，不把未核验断言默认为可说。Tool/fact预检不占SQL事务。
3. 单COMMENT Turn/Attempt/Utterance/Generation：Accept后只允许读LLM；Prepare并取得合法首次START/ticket→Receiver一次消费ACK后才TTS。流式lookahead最多一个；支持前驱STARTED或可信DRAINED后Prepare，Continuation及消费仍等前驱trusted drain。
4. 完成语义为Seal+全部连续required drain+既有CONTROL业务提交；正常Finish不等于Run Stop，不释放全局业务slot、不提前推进讲解cursor。Unit2不新建全局START，迟到旧媒体不重贴当前slot。ACK/Permit/事实/Stop/Binding/旧Epoch/UNKNOWN都保持保守取消。
5. 复用公平预算、评论TTL、原始合并身份、Operator FORCE和商品切换策略。连续评论不饿死商品讲解，不连续FORCE；恢复下一未完成商品段，已完成前缀不重讲。

## 验收与交付

CPU语义正反例、首单元早于provider EOF、硬资源上限/backpressure、两种Prepare/Drain顺序、迟到Unit2、跨事实变化/过期、丢START/continuation/consume ACK、同Turn一次START/每单元一次TTS意图、缺Seal/缺required drain不得业务完成、Stop×Resume/商品切换/UNKNOWN不越cursor、公平/TTL/重复/merged身份。策略测试使用Fake须明确标CPU/Mock；与Agent2真实PG和Agent5真实输出联验是后续独立门槛。

交付base/head、wire/Authority依赖SHA、文件清单、资源预算、原始结果和失败/skip；137契约/11Journal与既有Planner/Turn/v1回归保留。PR目标integration，公共入口patch由Agent4合入；不改迁移、冻结22文件、GPU Wire/PTS/Credit，不启用LIVE或自行GPU验收。
