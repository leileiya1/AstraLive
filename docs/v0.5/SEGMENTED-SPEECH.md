# Segmented Speech — 业务段与流式分句

`runtime/app/session.py` 的 `sentence_stream()`在同一Utterance的LLM输出内寻找TTS可用句子。它优化首次音频准备，但没有稳定segmentId、段级Utterance、持久cursor或每句全required sink检查点；原长AUTO_SCRIPT仍占用整个Utterance。

本实现的SpeechSegment在播放前形成完整的不可变文本和身份，每个段由Agent2创建独立业务Turn/Utterance/Outbox，复用现有AUTO_SCRIPT媒体路径。一个run一次只有一个slot。只准备文本，不预先投递下一段音频，不建立第二个Avatar队列。

初始目标3秒，可配置2–4秒；估计按5个发音单位/秒，字母数字分别计数，标点计停顿。估计不是实际时长SLA。完整句短于2秒可以合并，但合并不能超过目标。逗号、分号、顿号、数字、尺码列表、型号和单位均不是切分点。引号/括号内部保留；跨句不完整条件保守合并或拒绝。初版不声称通用中文语义解析；长复句不能安全切开时直接返回SEGMENT_TOO_LONG，要求上游提供更短的完整陈述。

不可分段预计超过6秒拒绝自动准入，不按字节、PCM或固定秒数截断。测试覆盖129.90元、129,990.50元、满199减20、XL/XXL/2XL、AB-2XL-Pro、500毫升、20 cm、5 L、否定范围和条件结论。

新增 `runtime/app/durable_live_segments.py` 是纯exact-text校验辅助函数：检查SCRIPT_TEXT、精确hash、商品/来源、deadline和重新取得的事实，返回原文；不调用LLM、不创建任务、不标记完成。Agent4须在新的journal/fence wrapper中接它，再复用现有XiaoYa TTS/GenerationContext/SoulX媒体链。COMMENT_QUESTION继续走现有商品Tool/FactAnswerResolver/DeepSeek Streaming。该模块尚未接入Session，不得将它称为已上线exact-text执行器。

正常边界是Agent2已事务提交的COMPLETED/BUSINESS_COMMIT；LOCAL_MEDIA_DRAINED单独到达也不能让出。所有required sink的连续范围、尾部和Generation映射由Agent2/journal/guardian验证，不把旧OR消费credit当成全部sink完成。未修改PCM、PTS、H.264、Worker wire、WebRTC或RTMP实现。
