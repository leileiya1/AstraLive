# AstraLive v0.3 — 个人 Avatar 验收记录

日期：2026-10-09。最终状态：**PARTIAL IMPLEMENTATION — NOT ACCEPTED**。

本轮完成设计、授权研究、素材校验、可选Voice桥接、PCM/取消控制以及Agent 1 v0.3.1 processor协议对接代码。**没有完成网页“创建→上传→试听→真人预览→保存→再次使用”，没有本人素材真实SoulX GPU输出，没有真实克隆试听。** 本模块不修改正式默认形象/TTS，不训练基础模型，不启动收费GPU。

## 1. 本轮实际验证

从仓库根执行：

```bash
PYTHONPATH=runtime runtime/.venv/bin/python -m unittest discover -s runtime/tests -p 'test_personal_assets.py' -v
PYTHONPATH=runtime runtime/.venv/bin/python -m unittest discover -s runtime/tests -p 'test_voice_stream.py' -v
PYTHONPATH=runtime runtime/.venv/bin/python -m unittest discover -s runtime/tests -p 'test_personal_processor.py' -v
PYTHONPATH=runtime runtime/.venv/bin/python -m unittest discover -s runtime/tests -p 'test_personal_voice.py' -v
PYTHONPATH=runtime runtime/.venv/bin/python -m unittest discover -s runtime/tests -p 'test_personal_validation.py' -v
PYTHONPATH=runtime runtime/.venv/bin/python -m unittest discover -s runtime/tests -v
```

素材单测9项通过，Voice流式15项、processor/schema10项、个人Voice解析5项、隔离启动器3项通过，共42项新增检查。照片和人脸观察使用合成fixture；WebM/Opus是合成正弦波；CosyVoice是FakeEngine，内部HTTPS是MockTransport，Linux隔离只查参数及macOS拒绝路径。验证控制/协议语义，**不证明真人识别、声纹相似度、Backend存储部署、实际Linux隔离或模型推理**。

Runtime全量回归执行121项：110通过、11项真实服务环境开关测试跳过，耗时5.434秒。日志位于本地忽略的 `runtime/evidence/personal-avatar-20261009/runtime-tests.log`，不将skip计为真实服务PASS。测试环境已有PyAV17.1.0、Pillow12.3.0、NumPy2.5.3；本轮没有安装新环境或权重，也没有验证依赖清单的全新安装。

前端现有 `bun run build && bun run test` 已执行：build成功，7个文件/34项测试通过。没有新个人素材页面或个人产品浏览器验收；该回归只确认当前前端保持可构建。

| 检查 | 本轮结果 |
| --- | --- |
| JPEG/PNG/静态照片裁剪、清晰度门限、元数据清除、检测器缺失拒绝 | 9项素材测试的一部分PASS，检测器本身未提供 |
| WAV双声道下采样、WebM/Opus解码、时长/静音/削波/坏文件拒绝 | 素材合成测试PASS |
| 16/22.05/24/48k分块不变性、sequence、generation、样本/PTS、EOF | Voice测试PASS |
| 模型stream=True、有界背压、共享引擎互斥、native异常脱敏 | FakeEngine控制测试PASS |
| 取消、timeout隔离、关闭源、后续重用 | 模拟Voice控制测试PASS；真实CUDA取消待测 |
| 不自动回退到错误音色、空PCM拒绝 | Voice测试PASS；真实provider失败待测 |
| 测量按实际样本计数，主观评分保持pending | Voice测量fixture测试PASS |
| Agent 1 schema、claim-only读写、scope/摘要/lease/心跳、SIMULATION拒绝 | 10项协议单测PASS；无真实Backend部署 |
| VoiceProfile解析、参考lineage、参数拒绝、临时WAV权限/清理 | 5项模拟引擎单测PASS |
| 受限decoder的mount/namespace/temp参数与不支持平台拒绝 | 3项单测PASS；实际Linux待测 |
| Runtime整体回归 | 121项执行；110 PASS，11 SKIP；5.434秒 |
| Backend个人契约包 | `go test ./internal/personalconfig` PASS；不代表HTTP/存储实现 |
| Frontend既有构建/单测 | build PASS；34 PASS |
| 私人素材API/存储/网页向导 | NOT IMPLEMENTED |
| 个人照片+真实SoulX GPU预览 | NOT RUN |
| 个人参考声音+真实Voice Provider试听 | NOT RUN |

## 2. 当前未满足的依赖

1. Agent 1已交付冻结v0.3.1 AvatarProfile、VoiceProfile、AssetStorage及Job schema，processor直接消费；Backend目前可见Go接口/DTO不能代替其HTTP handler、SQL持久化、配额及私有存储实现。
2. AssetStorage私有存储、tenant+user隔离、素材租约、ASSET_IN_USE/删除与缓存回收尚未实现。
3. 未提供有授权且校准的本地人脸/姿态检查器；helper默认明确拒绝。
4. 现有SoulX worker仅接受官方固定Girl照片哈希；个人多头像prepare/cache需要正式worker契约和实现。
5. 候选Voice引擎没有完成完整商业授权链核验，也没有本轮已配置/运行的真实克隆模型；不从实验全局凭据或用户未授权服务兜底。
6. 当前无用户本人授权照片/参考语音用于验收；不把官方示例素材当本人的结果。已有GPU收尾报告记录关机，本轮没有开机/租赁/调用GPU，不以旧报告推断当前在线。
7. v0.3.1已定义personal binding24h租约/renew及原子快照；其Backend/Session实际集成仍需验证。Voice输出VOICE_PREVIEW不能直接作为Avatar要求的NORMALIZED_AUDIO，目前缺少合法组合preview/转换边界。

缺口与所有权见 `integration/issues/011-personal-avatar-contract-and-real-provider-gates.md`。

## 3. 与既有SoulX结果的区别

已有 `astralive-avatar-lab/reports/SOULX-REAL-TEST.md` 记录官方Girl图片在RTX4090D上的真实Lite输出和短/长时推理；`SOULX-FINAL-ONE-HOUR-PINNED-ACCEPTANCE.md`记录音画同步专项结果及业务LLM鉴权缺口。它们证明既有实验链路在其版本/素材下运行，不证明个人照片、个人克隆声音、私有素材隔离或网页档案管理。

没有复跑这些旧结果；本轮不将旧性能写入个人验收表，更不把其warm首视频块时间等同用户点击到首浏览器帧。主观相似度必须由用户/人工看本人照片与结果确认。

## 4. 最终网页验收场景

使用HTTPS管理后台、真实登录身份A、独立的同租户身份B和不同租户身份C。A不修改模型代码、文件或SSH，从页面完成创建与同意、照片上传、声音上传/录音、参考文本、Provider选择、真实试听、10秒真实SoulX预览、人工确认、保存、设为当前、刷新/新Session再次使用。

A创建第二人物并切换，核查人物/声音缓存和播放generation不串档案；禁用后不可新开播。素材/Provider版本更新使旧确认失效。B/C无法列出、读取、预览、删除A素材/Job。检查网络响应与匿名访问均无原始素材公开URL、API Key或GPU SSH信息。

主动取消preview、断开Voice/GPU服务、注入坏音频/缺人脸、在prepare期间重传/删除；错误可见、旧结果不复活，失败不显示真实成功。检查正常Stop和删除后Session、线程、GPU对象、临时文件/对象存储/缓存最终状态。刷新后再次使用必须依靠已存私有档案，不能只保留在浏览器内存。

保存前的10秒视频必须有真实SoulX模型/权重版本、输入资产版本、帧数/时长、完整解码、provider来源、是否补静音/裁剪、浏览器实际播放证据。降级视频不能通过真人确认。声音试听必须同样记录真实Voice来源，而非MockPCM或XiaoYa冒充克隆。

## 5. 必须分别记录的指标

| 指标 | 证据与方法 | 本轮个人素材结果 |
| --- | --- | --- |
| 形象一致性 | 本人照片对照真实视频，身份/嘴脸/运动稳定性人工确认，留审阅人/时间/问题 | NOT BENCHMARKED / PENDING_HUMAN_REVIEW |
| 音色相似度 | 同一参考与合成的盲听、可选授权声纹模型辅助 | NOT BENCHMARKED / PENDING_HUMAN_REVIEW |
| 中文清晰度 | 固定句、转写/CER规则、数字多音字人工复核 | NOT BENCHMARKED |
| 语音自然度 | 多句听评停顿/韵律/噪声，人工评分，允许缺失而不默认满分 | NOT BENCHMARKED / PENDING_HUMAN_REVIEW |
| TTS首PCM | 真实请求→首本地PCM，冷/热、p50/p95；另测browser首可听声 | NOT BENCHMARKED |
| 数字人首帧 | 请求→首GPU/CPU/browser帧分别计，记录积累音频和准备成本 | NOT BENCHMARKED |
| 音画同步 | 样本索引/视频PTS与浏览器actual播放核对，持续讲话、闲置、FORCE | NOT BENCHMARKED |
| GPU资源 | TTS/SoulX分开及共GPU并发，Torch峰值和nvidia-smi占用、OOM/利用率 | NOT BENCHMARKED |
| 持续PCM/中断 | 首包后最长断流、10分钟稳定输出、取消/重用、残留线程/显存 | NOT BENCHMARKED |

初步工程目标供产品负责人确认：warm首PCM p95≤1秒、warm端到端首浏览器真人帧p95≤3秒、RTF<1、连续10分钟无非预期失败，音画同步按现有项目专项口径另确认。它们不是已达成结果，也不能在没有采集时填0。主观项由本人/审阅者明确接受后才通过，不以Agent自动评分代替。

## 6. 交付物与结论

四份要求文档均已创建：本设计、Voice评估、素材安全、验收记录；并交付9个可选Runtime模块、依赖清单和42项控制/格式/协议测试。当前发布结论保持NOT ACCEPTED，直到私有产品API、网页链路、真实个人推理及人工确认完成。并行工作区出现其他Agent的Worker/Backend/Session修改，本模块未覆盖这些修改，也不将其结果计入个人验收。
