# AstraLive v0.3 — Voice Clone 核验与评估

日期：2026-10-09。**尚未选定正式商业 Provider；个人声音真实推理 NOT BENCHMARKED。** 官方资料与本仓库代码核验完成，适配器测试不等于真实声音验收。

## 1. XiaoYa/Sherpa 现状

`runtime/app/real_tts.py` 构造 `OfflineTtsVitsModelConfig`，加载 `zh_CN-xiao_ya-medium.onnx`、词典和规则；合成调用 `engine.generate(text, sid=self.speaker_id, speed=1.0, callback=...)`。没有参考音频、参考文本、embedding 或用户 speaker 注册入口。`speaker_id` 是已有 VITS speaker 的选择，不是新建用户音色。

结论：**当前 XiaoYa Provider 不支持声音克隆。** sherpa-onnx 生态存在其他模型类型，不代表现有 VITS 适配器支持它们。原 callback 增量 PCM 为原生模型采样率，既有实测测试期望22050Hz；不能直接送给要求16k的 SoulX。配置契约虽允许 speed，但当前代码固定1.0，产品不能声称已经生效；本轮没有改变正式默认行为。

系统音色保留为可显式选择的独立音色。禁止上传音频后依旧调用 XiaoYa 而标注“克隆完成”。

## 2. 候选方案与授权核验

以下是2026-10-09可读官方资料的初筛。型号、代码、所有权重/辅助组件及版本必须在部署前固定；仓库 main 和模型卡声明不构成完整数据来源/第三方素材权利证明。

| 方案 | 中文及流式机制 | 已核验许可声明 | 本项目决定 |
| --- | --- | --- | --- |
| CosyVoice2-0.5B | zero-shot 接收参考文本/音频；原生接口允许stream=True；作为适配首轮基线 | 代码及官方权重模型卡标注Apache-2.0 | 优先工程验证候选；尚未商业准入 |
| Fun-CosyVoice3-0.5B-2512 | 官方描述中文/方言及双向流式；可与2代用同一素材比较 | 官方权重卡标注Apache-2.0 | 对照候选；需验证提示文本要求和锁定具体版本 |
| VoxCPM1.5 / VoxCPM2 | 官方项目提供参考语音克隆及流式能力；不同型号不能混用采样率/性能 | 官方声明代码和权重Apache-2.0；1.5卡同时建议生产前严格测试 | 后续对照；本轮没有实现适配或安装模型 |
| F5-TTS官方预训练权重 | 可研究中文零样本效果；不能因离线WAV分块就宣布低延迟 | 代码MIT，官方预训练权重CC-BY-NC，归因Emilia训练数据 | RESEARCH_ONLY；禁止未经许可作为商业默认引擎 |
| 外部托管克隆服务 | 需真实测首音频、连续PCM、取消和数据留存 | 需要具体服务合同、音色权利及数据处理条款 | 未选定、未上传任何用户素材 |

官方依据：[CosyVoice代码](https://github.com/QwenAudio/CosyVoice)、[CosyVoice2权重卡](https://huggingface.co/FunAudioLLM/CosyVoice2-0.5B)、[CosyVoice3权重卡](https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512)、[VoxCPM项目](https://github.com/OpenBMB/VoxCPM)、[VoxCPM1.5权重卡](https://huggingface.co/openbmb/VoxCPM1.5)、[F5官方许可说明](https://github.com/SWivid/F5-TTS#license)。这些性能描述来自上游，**不是 AstraLive 延迟/中文自然度实测**。

正式准入需要逐项证据：代码及子模块LICENSE/NOTICE；具体基础及辅助权重revision/SHA256/许可证；tokenizer、声纹encoder、vocoder、文本规范化和可选加速组件；训练/预置声音数据的来源、使用限制及发布方声明；用户参考素材授权；自托管或托管服务条款、地域/留存/删除安排。对无法核验的数据权利记录 UNKNOWN，不能因代码Apache便填全部PASS。记录审核人、日期、限制和到期/撤销规则；本轮没有完整许可证闭环。

## 3. 原生 streaming 与服务示例的差别

CosyVoice `inference_zero_shot(..., stream=False, speed=1.0)` 默认关闭原生流式。官方 FastAPI 示例没有给该调用传stream=True。HTTP StreamingResponse 只能说明传输可分块，不能证明模型未等待完整合成。[原生接口](https://github.com/QwenAudio/CosyVoice/blob/main/cosyvoice/cli/cosyvoice.py)、[官方FastAPI示例](https://github.com/QwenAudio/CosyVoice/blob/main/runtime/python/fastapi/server.py)

本轮可选 `CosyVoiceTTSProvider` 显式使用stream=True、speed=1.0；接收已经加载的本地引擎和共享模型互斥锁、已解析的私有参考WAV、voiceId、参考文本。不调用AutoModel，不训练、下载、访问远端或保存spk2info。新语速控制保留为不支持，音量仅在PCM域0..2倍缩放/限幅，不能暗示所有上游instruct参数已经验证。v0.3.1个人VoiceConfig已定义该音量字段，不回填旧v0.3.0 TTSConfig。

Agent 1已冻结v0.3.1 VoiceProfile：xiaoya严格speed=1/volume=1；cosyvoice严格speed=1/volume0..2、operator-registered modelRef、referenceAssetId/referenceText。使用`personal_contract.py`直接校验这些结构；`personal_processor.py`从assigned JobClaim获取版本和参考素材，以摘要验证的claim-only输入处理，桥接与测量仍由注册的真实Voice executor接入。

`PersonalVoiceRenderer`已实现该executor边界，按合法VoiceProfile选择operator注册的system/CosyVoice工厂，验证profile版本/能力/参考lineage，真实PCM归一化成≤30秒试听WAV。没有注册引擎时返回PROCESSOR_UNAVAILABLE；本轮未配置实际模型工厂。测试用FakeEngine证明这些控制条件，不作为真实试听结果。CosyVoice工厂必须复用已审核安装的模型与共享互斥锁，异常native隔离必须由服务监督器回收，不让下一档案重用仍在运行的模型。

引擎需由隔离服务负责加载并持有，服务启动前禁用第三方遥测/自动下载，关闭上游记录合成文本的日志。参考文件必须由AssetStorage按租约提供到私有不可变路径，不能把浏览器文件名当路径；本地路径检查不是身份/授权检查。

## 4. Runtime 音频边界

沿用已有 `TTSProvider.synthesize_stream(text, VoiceConfig, GenerationContext)` 与 `AudioChunk(generation_id,sequence,pcm,sample_rate,channels)`；VoiceProvider仅追加 worker内部能力描述，未新增公共VoiceProfile。

一个 synthesis 使用一个PyAV状态式重采样器，保持滤波状态，输出16k、mono、little-endian s16；20ms对应320样本/640bytes，EOF不足20ms直接发送真实尾部，不任意补静音。sequence严格连续，拒绝旧generation、采样率变化、奇数字节、双声道及超限原生块。不同上游chunk切分在测试中输出完全一致，避免逐块round的累计漂移。

`TimedPCM.first_sample_index` 是服务内证据，PTS=`index*1_000_000//16000`，以实际输出样本累计。Runtime/worker编排必须分配Session连续origin；新一句话/新generation不能无意把共享播放时钟归零。既有AudioChunk不额外塞入未定义字段。当前正式Session未接此适配，不能声称现有链路已经完成该迁移。

桥接队列最多4个原生块，每块≤524288样本，另有一个正在提交的块；这是字节/块有界，不保证4个20ms。PCM转换只保留不到20ms尾部，消费者停止取数据会反压native producer。共享引擎互斥，忙时明确返回VOICE_WORKER_BUSY，不自动混用其他用户声音。

默认首原生块deadline30秒、后续块10秒、整个synthesis120秒、关闭等待0.5秒；这些是资源失败上限，**不是产品延迟目标**。可取消时丢弃重采样尾部并关闭源。不可抢占CUDA调用超过关闭上限时隔离该provider、保留引擎锁直至线程退出，拒绝再次使用；管理服务需回收/重启隔离worker。不能将快速返回aclose等同于GPU计算已经终止。

失败策略沿用当前v0.3 STOP：异常向上抛，未偷偷变成XiaoYa。后续若Agent 1明确增加用户选择的系统声音回退：只允许首PCM之前、使用重新授权的独立voiceId、明确通知音色变化；发出部分克隆音频后失败必须终止该generation，不能拼接两种声音并报告克隆成功。当前无此新增契约/回退实现。

## 5. 实测方法

`measure_voice_stream` 接收实际解析后的provider，可记录请求到本地16k PCM的首包时间、合成总时长、音频样本数/时长、最大/p95块到达间隔和RTF。它不保存照片、音频、文本，不填主观评分，也不把Mock的结果标成真实模型。输出`gpuResources=NOT_MEASURED`和`subjectiveReview=PENDING_HUMAN_REVIEW`；执行者另附provider/model/code/weight版本及REAL或SIMULATED证据来源。

真实测量使用同一批本人授权的3–30秒干净参考语音及校对文本；中文测试包括问候、数字/价格/单位、多音字、长句、短句和中英混读。每个Provider先单独运行，记录冷加载、冷/热首PCM、30次短句p50/p95和连续10分钟输出间隔；再测取消/重用/失联/空输出/参考素材删除。不以在线demo或上游150ms宣传值替代测量。

另测browser请求到首可听声音、PCM到SoulX首GPU帧/首CPU帧/首浏览器帧，分开时钟范围；部署网络计入端到端，跨主机需校时或往返事件关联。首PCM和首帧分别报告冷/热缓存、reference准备是否包含，避免把预热后的300ms官方人物视频块当全产品首帧。

中文清晰度用固定转写/人工复核，CER需记录规范化规则和ASR版本；音色相似度用参考/合成盲听和选定授权声纹模型辅助；自然度由人听评，不由Agent填满分。留审阅人、时间、具体问题，用户确认前状态PENDING_HUMAN_REVIEW。

## 6. GPU成本与选型门槛

分开测TTS单独、SoulX单独、同GPU同时运行、独立TTS服务四种配置。采集nvidia-smi每秒占用/利用率、Torch分配/保留峰值、GPU型号、并发、首PCM/首帧p95、长时输出间隔、OOM和音画同步。0.5B/2B参数量不能直接换算本部署显存；现有SoulX单独测试的显存不是共GPU安全依据。

成本使用实际机器单价×占用时长÷成功音频时长，分开空闲/冷加载和失败重试；未获取报价/计费记录时不编造金额。第一轮优先独立TTS服务作为测量基线，不默认启动另一台GPU，也不认定共用不可行。只有实际并发测量满足目标后才决定部署形式。

本轮所有个人声音的相似度、清晰度、自然度、首PCM、GPU显存和成本：**NOT BENCHMARKED**。接口控制测试不是该表的实测结果。
