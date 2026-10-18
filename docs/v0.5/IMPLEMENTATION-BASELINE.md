# CCR-ADL-001 implementation baseline

DTO后续交付：统一生成器/Go/Python wire实现已完成，详见 [DTO-HANDOFF](implementation/DTO-HANDOFF.md)；本文件记录原e98基线分工，原“尚未实现”描述保留为该阶段状态。新DTO完整SHA以PR8定版通知为准，生产接线仍未实施。

本登记只分配实现责任，不改变获批技术协议，也不启动生产功能。

- Baseline ID: `v05-ccr-adl-001-approved-20261017`。
- PR9 normal merge: `0eed2d030c3440cd8770568d9317fca5dc981bf0`；parents为原integration `546ad9aa40bfe6949f32b55fb8ab6dc25d30dcb7` 和交付HEAD `c14085c67368c295eee53a6e4b01ac68ba3cd4a6`。无squash/force push。
- Frozen contract: `c7fd46209d3cbc6f58541dba8b4e1c85609c823e`。
- 22-file normative digest: `3c0c317ed00f6fa4d2cf15ef3f61fc002d4bb22bf02d53ee9f1b407458bb28b1`。
- Versions: `durable-live-2` / `receiver-1`；25 core + 13 private operations。
- 当前批准以[FINAL-APPROVAL](ccr/CCR-ADL-001-FINAL-APPROVAL.json)及[Agent1决定](https://github.com/leileiya1/AstraLive/pull/9#issuecomment-6231271734)为准；冻结规范/旧ACKS中的BLOCKED/PENDING是历史评审状态，不是运行配置，不能为消除文字差异重写冻结文件。
- 唯一开工pin为Agent4在[Draft PR8](https://github.com/leileiya1/AstraLive/pull/8)发布的本次baseline登记提交完整SHA；该提交在上述merge之后只追加非规范协调文档和证据。各Agent记录该完整SHA，不能仅记录浮动main。代码基线merge与文档登记提交分开列出以便追溯。

## 已实际完成与未完成

PR9已合入integration，22个规范文件、manifest原字节和digest独立校验一致；冻结到交付HEAD的差异只有4个审批/交接文件。PR没有配置CI检查，Agent4在交付HEAD独立运行137项契约/11项Journal/两个validator/Go示例编译及Backend回归；合并后在原工作树再次运行137及两个validator。原始命令、完整stdout/skip在[evidence](evidence/agent-4/approved-baseline-2026-10-17/)中。Backend是95 PASS/0 FAIL/50 SKIP，未提供专用DB/Redis，不能写成真实SQL或故障验收。

生产源文件与合并前integration相同。`ASTRALIVE_DURABLE_LIVE_ENABLED` 默认false，Go/Python即使设true仍拒绝 `OUTPUT_FENCE_UNPROVEN`；v2没有注册生产路由/可运行执行器。不得因契约productionEnabled字段或审批状态解除保护。Frozen v1.1、durable-live-1、GPU Wire、PCM/PTS/Credit保持原行为。一个Session不混用v1/v2，也不能将v2任务自动降级到旧接口。

## DTO、迁移和共享文件

[DTO生成计划](DTO-GENERATION-PLAN.md)及[所有权登记](implementation/ownership.json)是本阶段唯一路径分配。Agent4独占生成器、Go `backend/internal/durablelivev2/wire/` 与Python `astralive_contracts/durable_live_v2/`。目录目前只是保留，生成器/生产DTO尚未实现，其他Agent不得复制样例形成第二套类型。Agent4下一项窄范围实现应先交付DTO/严格decode/固定hash校验及default-off验证，再提供完整SHA给依赖方。

正式integration迁移链最高000006。保留 `backend/db/migrations/000007_answer_stream.sql` 给Agent2独占；不创建空SQL占位、不自动应用迁移、不改000006。已检查最新远程main、integration、Agent1/2/3/5正式分支；这些链没有000007。实验Golden分支有另一套不兼容的000006–000008，未引入，不能把那套链的编号/表直接拼入本基线。任何新正式迁移先登记再提交，若其他正式分支占用000007则停下由Agent4重排，禁止静默重编号。

Agent4独占所有公共入口、身份装配、Session/Binding及Runtime接线。Agent2/3/5只在自己原有Worktree/分支工作；开工fetch，确认干净或保留自己的未提交修改后，以正常merge同步本次pin，不reset/stash/clean/force，不编辑其他Agent工作树。共享文件需求提交patch/说明，由Agent4串行合入。原PR5/6的交付已可追溯，后续新实现应使用基于现有分支的增量PR面向integration，不重合并旧main目标PR。

## 并行顺序与交付门槛

1. Agent4先实现统一DTO、版本/闭合解码和认证上下文类型，继续保留LIVE拒绝。当前只登记任务，未启动该实现。
2. Agent2优先提交additive SQL/Authority；Agent3可同时做纯语义/有界流式域逻辑；Agent5可同时做局部gate/不可逆tombstone/连续输出域逻辑。允许用显式Mock对端做模块单测，禁止把Mock作为正式实现。消费共享DTO的编译/合并门槛依赖Agent4 DTO提交，不能自行定义替身DTO。
3. 推荐集成顺序：Agent4 DTO → Agent2 SQL/Authority → Agent3 stream/Turn → Agent5 Guardian → Agent4 Registrar/Session/Runtime共享接线。无共享冲突的独立模块可调整PR顺序；真实跨进程验收必须等真实Authority、Registrar及Guardian齐备。
4. 所有实现PR保留137契约/11Journal及旧回归，提供准确base/head、修改文件、依赖SHA、原始命令/日志、失败/skip、资源上限、回滚与NOT TESTED。真实DB、IPC、fsync、媒体输出、GPU/浏览器/官方观众各层分别验收。

任务包：[Agent2](implementation/AGENT-2-TASK.md)、[Agent3](implementation/AGENT-3-TASK.md)、[Agent5](implementation/AGENT-5-TASK.md)。本轮只生成任务包，没有新建/启动Agent，也没有向其他Agent自动派发实施任务。

## 剩余阻塞

架构契约门槛已解除，生产v2能力仍未实现/验收：统一DTO、SQL注册/消费、可信Registrar/进程安装、Session/Binding、Runtime一次TTS与媒体lineage、Guardian真实输出独占/短gate/连续Publisher/Decoder/Sink及逐单元drain。专用SQL/Redis故障、主机恢复、真实GPU/Chrome/RTMP/官方观众和busy latency仍需后续证据。OUTPUT_FENCE_UNPROVEN保持；整体结论仍 `ASTRALIVE V0.5 BLOCKED`。PR8保持Draft且不合main。
