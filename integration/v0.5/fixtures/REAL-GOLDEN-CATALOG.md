# 真实 Golden 商品与讲解 fixture

`real_golden_catalog.json` 是用户确认的演示 SKU“桌面整理指南”电子说明书：价格99、币种CNY、库存20、规格电子版。说明书内容由140条独立完整陈述组成，覆盖商品信息、准备、分类、分区、纸张、线缆、文具、小物、电子资料、每日收尾、小空间、共享、安全维护和复盘。每条陈述对应一个全局唯一 factId，明确含义保存在 facts 字典；没有循环重复陈述或为凑时间改 ID。

plan 的 policy=AT_BOUNDARY，style 和14个 beats 直接供生产 Go BuildPlan 使用。140条文本含标点长度20–29字符，每条均有非空 factIds，因此实际生产 planner 生成140个完整段，不依赖字数切片或事实空白段打包。真实归档源码 BuildPlan 调用验证：长 fixture14 beats/140 segments，短 fixture10 beats/10 segments，均 PASS。

questions 保持 list[str]，可直接给现有 reader。questionsMetadata 是测试调度/oracle 元数据：id 为稳定 replay 事件标签，priority 为输入评论优先级，injectAfterSegment 表示建议在已完成该数量讲解段之后注入；expectedFactIds 表示问题应该涉及的商品事实。这些元数据不伪造 Backend 选择、回答或媒体回执。五条评论只模拟评论 transport，内容分别询问价格、库存、名称、价格、库存，均为单主题；真实 LLM/TTS/GPU/Runtime/SQL/sink 层不得由 fixture 替换。

`real_golden_smoke.json` 复用明确商品信息的10个完整段和1条价格评论，scope=SHORT_SMOKE_NOT_GOLDEN_TEST_1。短测只能验证业务接线；不把它声明为十分钟、五问题或自然续讲验收。

## 实际 CPU TTS 预检

使用已缓存 zh_CN-xiao_ya-medium，真实 SherpaOnnxTTSProvider（CPU、speaker0、speed1、2 threads），经生产 StreamingVoiceAdapter 从22050Hz归一到16000Hz mono s16le，再按640 source-sample 边界补零计数。下列 duration 来自真实样本，不是字数/时长提示推算；短 fixture 复用同一次测量的前10句，不额外合计重复运行。

| 独立预检 | 140句总音频 | 短10句 | 最长句（含pad） | >7.5秒 | >8秒 |
| --- | --- | --- | --- | --- | --- |
| 首次 |754.88秒|48.92秒|6.52秒|0|0|
| 重复 |753.88秒|49.16秒|6.32秒|0|0|

首次最慢句 guide.14.04：“工作内容变化时重新确认高频用品，不保留已经过时的桌面安排。”。全部都保留了超过1.4秒的8秒余量，无须删除、切断必需事实或调快 TTS。140句累计音频约12分35秒，但它不是一次持续直播证据：真实 Golden 必须实际运行同一个 Session，记录真实墙钟、Sink 和 Chrome 音画，再检查回答、恢复位置、语义与质量。

生产 Go 三类固定答案也实际测量，首次价格/库存/名称分别2.44/5.60/2.48秒，重复2.40/5.56/2.80秒。原生 TTS 对固定价格答复中的 CNY 发出 `Ignore OOV 'CNY'`，已保留完整告警；这表明币种缩写的可听表达有缺口，CPU 时长通过不能当作回答音质/事实可听性通过。本 fixture 没有修改生产金额读法。

这些陈述不能使用1.92秒 profile；真实短业务 smoke 也需在短 GPU gate 已通过后明确启用8秒 profile，并遵守固定身份、内存、A Grant、StageRenew和播放边界。不得假设音频符合8秒就证明 GPU、Stage TTL、流控或整段 artifact 合格。

原始逐句样本、pre-pad PCM SHA256、pad、总和、重复性测量、实际生产 BuildPlan 探针源码/stdout 和原生 TTS stdout 保存在 [预检证据](../../../docs/v0.5/evidence/integration-f/catalog-tts-preflight-1/README.md)。两次测量分开保留，不将其累加为直播时长。仅F统一提交这些文件；fixture 本身不更改产品数据库/生产配置。
