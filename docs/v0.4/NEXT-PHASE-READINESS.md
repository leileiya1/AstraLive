# AstraLive v0.4 — 下一阶段准备度

2026-10-11，fetch后的远程main仍为 `59d96c8818a4512651a2f945ced71278929c9e12`；独立分支 `audit/v04-interaction-gate`。四份报告与 independent/checks.json、原始JSON、回归失败/通过日志一起交付，未修改或合并main。

| 最终门槛 | 状态 | 适用范围 |
| --- | --- | --- |
| **ARCHITECTURE REVIEW** | **PASS** | 修复后单Backend/单Runtime、单操作员MVP；不代表多实例SaaS、exactly-once或商业恢复SLA |
| **INTERACTION INTEGRATION** | **PASS** | 隔离SQL/Redis CPU集成及真实A/B/C/D/E、商品切换、Replay取消、Stop/release；短场景范围 |
| **END-TO-END LATENCY** | **PASS** | 正常低负载Fast/简单LLM/商品综合LLM分别统计；最终综合20条Chrome与本地RTMP的P50/P95误差上界均≤3s/5s；不包含繁忙/高负载SLA |
| **MEDIA REGRESSION** | **PASS** | 客观真实Chrome/RTMP、Generation Fence、headless和CPU媒体回归；用户确认录像及六组音频的读音/同步/唇形通过。最新性能录像另列，官方平台观众端未验 |
| **NEXT PHASE READY** | **CONDITIONAL** | 可进入受控自动场控设计和第一个官方Adapter隔离实现；不建议宣布自主直播、持续3秒SLA或商业发布完成 |

## 已有可靠基础

A的immutable Provider/商品Context、授权、正式Go Session、Stop/release、Worker admission、PTS/Fence/Credit；B的可信Mapping、Normalize、有限候选、去重/合并/TTL、Selection/Dispatcher、事实Fast Path、LLM/TTS增量背压与trace都已独立检查和测试。

新审查修复Room授权缓存、晚TTL、错误合并/2XL、Replay取消竞态、尺码朗读误改单位、UI口径。后续性能改进解耦100ms轮询与2秒口播间隔、立即唤醒、有界Session连接池及首个完整中文短分句增量朗读；保留原媒体协议和时间轴。

最终完整自动化：Go59顶层/90含子测试通过、1skip；Runtime148通过/11skip（159 total）；GPU CPU21、Frozen Contract/guard/marker7、前端40/9files及build通过。真实DeepSeek/XiaoYa/RTX3080、native Chrome和本地RTMP另有原始JSON；不能用CPU/Fake计数代替真实vendor结果。

最终综合20条Chrome P50/P95=2644.14/3656.62ms，上界2656.23/3695.77ms；RTMP=2692.73/3727.61ms，上界2748.36/3813.16ms。5141.91ms最大样本仍保留。此前5660.12、5014.48、5138.53ms慢样本与失败批次均未删除，分阶段报告。有限样本达标不是供应商延迟保证。

## 自动口播场控：可开始受控开发

具备基础，可规划有限长度的AUTO_SCRIPT段、商品快照、自然边界让出、Operator抢占后的可见恢复。当前PRODUCT_EXPLAINING依赖已有任务，不生成脚本、不续讲、不管理长期直播节奏。本轮没有开发完整自动场控。

长讲解中评论默认不打断，真实等待约17–19秒；高频选择等待P95约14.25秒。这是保持普通弹幕不无限FORCE的代价，不能称繁忙时3秒响应已验收。下一阶段应先定义短段/公平性/TTL展示与恢复策略，再逐功能真实验收。

## 第一个官方Adapter：可进入隔离实现，上线仍有门槛

统一Adapter/Event/Sink/Capabilities/Mapping足以承接一个官方授权transport。仍需官方API权限、账号/Room授权、source identity、重连/历史重放、token生命周期、限速/限长、敏感评论留存与可靠取消，并验真正平台观众端。当前仅本地RTMP解码，未接入官方平台，不做私有协议逆向。

单实例Receipt的RESERVED/ACCEPTED/FAILED不重投；崩溃后的丢失、QUEUED orphan和lost acknowledgement歧义仍需保守对账。不能用无限重试换取重复口播，也不能把本机mutex推广成多Backend协调。

## 仍需关闭的产品与运行门槛

- 长时随机多人/真实LLM混合负载，逐速率native RSS/CPU/GPU峰值、每分句TTS调用计数与持续吞吐；本轮仅短时/进程生命期资源快照。
- crash/orphan对账、输入持久身份/retention；当前自动任务at-most-once可能丢失。
- 官方平台观众端；本地decoder/FFmpeg credit不能证明平台扬声器播放。
- native无callback挂起、Session seen_utterances增长、全局命令锁跨Room排队、全新安装/恢复。空DB首轮并发migration失败已保留，初始化隔离schema后回归通过。
- 长时GPU soak与破坏性Worker恢复本轮未重复执行；共享Worker未重启、中断或换权重。

建议进入下一版本的受控开发与隔离官方Adapter阶段，保持上述运行和发布门槛。测试完成后只清理Agent C所有的服务/Session/容器/转发；GPU Worker保留READY，不关闭云实例或删除模型。代码、测试、报告和原始证据以独立分支Commit SHA供审阅；不直接合并main。
