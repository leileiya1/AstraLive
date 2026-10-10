# AstraLive v0.3 — 个人真人 Avatar 设计与实现边界

日期：2026-10-09。结论：**基础组件已实现；网页产品链路尚未实现，个人真人验收未通过。**

## 1. 当前事实与契约对接

已经读取 `architecture/ARCHITECTURE.md`、`contracts/CONTRACTS.md`、`USER-CONFIG-CONTRACT.md`、`PROVIDER-CONTRACT.md`、`SECURITY-BOUNDARY.md` 和当前 v0.3 schema。

Agent 1已新增冻结v0.3.1：`contracts/AVATAR-PROFILE-CONTRACT.md`、`VOICE-PROFILE-CONTRACT.md`、`ASSET-STORAGE-CONTRACT.md`，机器schema为`contracts/personal-assets/schema.json`，Go接口为`backend/internal/personalconfig/contracts.go`。本模块直接校验该机器schema，不复制AvatarProfile/VoiceProfile/AssetStorage DTO。通用v0.3.0 Profile/avatarRef与个人档案区分，旧 `/api/v1/avatars`、`/voices`没有同等级用户隔离，不能用它们保存私人照片和声音。

没有另外创建档案DTO、数据库表、浏览器API或Provider config字段，也没有修改冻结schema。processor按已交付JobClaim/AssetDescriptor/SuccessResult/FailureResult处理；HTTP handler与实际私有存储尚不能由接口定义证明已部署。跨模块剩余缺口见 `integration/issues/011-personal-avatar-contract-and-real-provider-gates.md`。

## 2. 用户完整操作

数字人管理展示本人已有档案。创建时填写名称，确认形象/声音使用权及用途，再上传一张清晰正脸照片；参考声音可文件上传或浏览器录音。界面先展示本地预览，Backend 授权成功后才接收素材。

Provider 列表由后端能力与审核状态决定。系统 XiaoYa 可选，但显示“系统音色，不支持声音克隆”；不可因上传参考语音便显示克隆成功。没有审核通过的克隆 Provider 时，明确显示尚不可用。参数只展示 Provider 真正支持且已进入配置契约的项。

用户填写与参考声音一致的参考文本，调用真实试听；成功后发起独立 10 秒 SoulX Lite 预览。预览支持查看进度、取消、失败重试和人工确认。界面说明单张照片的相似度因素材而异，以真实预览为准，不承诺完全还原。

保存需要当前照片版本、声音版本、模型版本下的试听、GPU 预览和用户确认记录。修改素材/Provider 后，旧确认失效。只有准备完成且启用的档案才能显式设为当前 Avatar；选择影响新 Session，既有 Session 不热换模型。再次使用按身份和版本命中缓存，不要求开发者改文件或 SSH。允许多个档案；禁用不删除，删除另有独立入口。

浏览器录音使用 HTTPS 下的 MediaRecorder，停止所有麦克风 tracks；根据浏览器支持选择音频 MIME，限制 3–30 秒，允许试听、重录和填写参考文本。组件卸载/替换素材时撤销本地 blob URL。浏览器上传的 MIME、时长及身份声明不是服务端可信依据。

## 3. 已实现的基础代码

| 文件 | 实际实现 | 限制 |
| --- | --- | --- |
| `runtime/app/personal_assets.py` | 内存照片校验、人物裁剪、512×512 RGB PNG、清除 EXIF/文本/ICC；音频解码为 16k mono s16 WAV | 不存储；不是 HTTP 接口；需可信人脸检查器 |
| `runtime/app/voice_stream.py` | 沿用 TTSProvider/AudioChunk 的 VoiceProvider 能力边界；状态式重采样、20ms PCM、样本索引和 PTS | 未注册到正式 Session；没有 VoiceProfile DTO |
| `runtime/app/cosyvoice_tts.py` | 对已加载本地 CosyVoice 引擎调用 zero-shot/stream=True；有界队列、互斥、超时和取消隔离 | 只做可选适配；未加载真实权重或进行商用审批 |
| `runtime/app/voice_evaluation.py` | 可注入实际 Provider 的首 PCM、间隔、时长、RTF 测量 | 不填主观分数；不测浏览器/SoulX/GPU |
| `runtime/app/personal_contract.py` | 直接消费Agent 1 v0.3.1 schema并拒绝unknown字段 | 无另一套档案结构 |
| `runtime/app/personal_processor.py` | 内部claim/input/output/result协议、HTTPS服务身份、摘要、心跳、超时、旧租约栅栏 | 未部署；缺真实executor/隔离validator时明确失败 |
| `runtime/app/personal_voice.py` | VoiceProfile解析、版本/能力校验、已注册本地引擎、私有参考副本与规范化试听WAV | 无引擎工厂时不可用；工厂注册需完成模型授权审核 |
| `runtime/app/personal_validation.py` / `personal_validation_worker.py` | Linux bubblewrap独立网络/PID、受限内存/CPU/临时文件及子进程取消 | 本机macOS只测拒绝路径，Linux实际沙箱/检测器待部署验证 |
| `runtime/requirements-personal-avatar.txt` | 可选 CPU 媒体依赖 | 不安装克隆引擎，不下载权重 |

素材校验 dataclass 和 TimedPCM 都是 worker 内部结果，不是 Agent 1 档案/存储结构；不跨 API 传输。现有 Runtime models、Provider 工厂、默认形象和默认 TTS 均未改变。

照片限制按已冻结photo-face512-v1：≤10 MiB，JPEG/PNG/静态 WebP，最短边≥512，≤1600万像素；必须只有一张脸。可信检测器提供框、姿态及眼口可见性：confidence≥0.9，yaw/pitch≤15°，roll≤10°，脸框最短边≥192；裁剪边长为脸框最大边的1.6倍，不能越界。脸区域统一缩放到256后拉普拉斯方差≥40。**这些阈值不是人脸真实性认证或质量保证；调整须走契约版本。** 默认没有检测器时返回FACE_CHECK_UNAVAILABLE，不默认为正脸通过。检测器模型、授权和真实素材校准仍待交付。

参考音频限制：≤20 MiB，解码支持 WAV/MP3/Ogg/WebM/MP4音频/FLAC，只有一个音频流，无视频；源采样率8–96k，单/双声道；输出3–30秒16k mono s16。缺参考文本、损坏文件、太静音或归一化后明显削波均拒绝。关闭 demuxer URL 协议，避免嵌套 URL 读取。RMS/削波检查不能判断是不是单人语音、噪声或文本是否匹配，VAD/ASR/人工复核仍需接入。解码必须放在进程级 CPU/内存/时间限制下，Python helper 本身不提供进程沙箱。

`IsolatedMediaValidator`提供Linux受限子进程入口：bubblewrap隔离network/PID/IPC，仅只读挂载系统库、Python环境、app代码与明确注册的模型目录，独立/tmp限制256MiB；child核对network namespace改变，再设置512MiB地址空间/60秒CPU，父进程60秒墙钟及stdout/stderr硬上限。未安装兼容bubblewrap、kernel不能创建namespace或macOS均明确不可用，没有进程内fallback。实际Linux能力探测、恶意素材测试和人脸模型必须在注册processor为可用之前完成，不能仅凭参数单测打开capability。[bubblewrap官方选项](https://github.com/containers/bubblewrap/blob/main/bwrap.xml)

`PersonalVoiceRenderer`直接消费JobClaim/VoiceProfile，验证当前profile版本、启用状态、Provider能力及PREPARE固定测试文本；系统音色和CosyVoice工厂由operator注册，未知modelRef拒绝。参考只来自claim中匹配sourceAssetId/摘要/preprocessing的NORMALIZED_AUDIO；在0700工作根创建0600不可变临时WAV，正常/失败后清理。若native调用被隔离，先等待监督器证明model进程停止再清理；不能证明时保留到服务回收，禁止宣称已删除全部缓存。试听收集≤30秒真实PCM成WAV，直播仍使用StreamingVoiceAdapter；WAV Job不替代流式验收。

## 4. SoulX Lite 个人缓存

只使用预训练推理和官方图像准备函数，不进入基础模型训练或微调。照片规范化成功后，由后端发起长任务，worker 先核对授权与 AssetStorage 租约，再执行图像编码和缓存准备。模型缺失/worker离线时任务明确等待或失败；不自动租赁 GPU、下载大权重或切换成假真人预览。

缓存身份应纳入 tenant/user、档案与素材版本、规范化照片内容、裁剪策略版本、代码 commit、所有权重 SHA256、512分辨率、采样参数等，由 AssetStorage 提供 opaque 引用。缓存只是特征/准备结果，不是训练出的新模型。不可用跨租户全局内容哈希作为访问许可。声音 conditioning、运动历史和生成缓存必须按 Session/档案隔离，切换时清空；共享预训练模型不等于共享人物状态。

`astralive-avatar-lab/streaming/worker_final.py` 当前只为固定官方 Girl 调用 `get_base_data`，PrepareAvatar 拒绝其他图像哈希。已有 Lite GPU 性能验证成立于那张官方图片；需要 worker 正式增加授权资产准备、多人物缓存、切换/驱逐后，才能用于用户照片。不能直接换全局 image 变量造成其他 Session 人物变化。

严格使用v0.3.1 ProfileState的CREATED/VALIDATING/PREPARING/READY/FAILED/DISABLED/DELETED，Job的QUEUED/RUNNING/SUCCEEDED/FAILED/CANCELLED以及Asset独立状态，不复用Session FSM。READY是当前版本实际准备证明，不是人工相似度确认。PREPARE_AVATAR必须REAL、≥3帧warmup及encoderReady，输入摘要与preprocessing匹配；processor拒绝SIMULATION。人工确认/保存门槛需采用Backend产品实现，不另造wire状态。

## 5. 10 秒预览与再次使用

目标是从当前真实Voice Provider生成中文声音，转换16k后送SoulX，生成完整10秒视频与音轨。当前冻结Avatar preview要求输入READY NORMALIZED_AUDIO且≤10秒；Voice preview生成VOICE_PREVIEW WAV。两种purpose不能直接互换，目前没有VOICE_PREVIEW→NORMALIZED_AUDIO转换或组合preview协议。此项已列为对接缺口；不重新上传生成音频伪装成本人原始素材来绕过purpose。短音频补静音到10秒、裁剪等需worker依契约明确执行并记录真实padding/cut样本，不循环视频。

预览必须由真实 SoulX Lite 执行；失败或降级 Lightweight 必须标识为失败/降级并禁止个人真人确认，不能以返回 MP4 或任务 completed 代替证据。浏览器仅通过认证媒体读取或现有媒体链路播放，原始照片/参考语音没有公开 URL。重复使用可以复用已准备人物特征，真实预览验收仍绑定当前版本。

上游模型卡列明 DiT/wav2vec2 为 Apache-2.0、Lite 的 VAE_LTX 为 Open-RAIL-M，Lite 发布需要单独核验该组件条款，不能只看代码 LICENSE。[SoulX 官方模型卡](https://huggingface.co/Soul-AILab/SoulX-FlashHead-1_3B)

## 6. Backend / Runtime 对接

Agent 1 是 AvatarProfile、VoiceProfile、AssetStorage、Provider Config 的唯一结构来源。Frontend 使用其生成类型和 Go 公共 API；后端从 HttpOnly cookie 获取 tenant/user，原子解析选中的启用档案和不可变 binding。Runtime 只消费服务端解析结果；不得由浏览器发送本地路径、asset URL、tenantId、API key、GPU SSH 信息。

新个人公共API已统一位于`/api/v0.3/config`，沿用原cookie覆盖范围；内部processor使用独立注册Bearer，不能获取LLM凭据。v0.3.1 personal-session-bindings定义一次事务原子捕获、24h租约与至少每小时renew、释放时同时释放detached provider binding；必须验证其Backend实现与正式Session适配后才能启用。

Agent 1已给出档案关系、参考文本/素材引用、同意、版本、启用/禁用/删除、AssetStorage接口、Job API及xiaoya/cosyvoice白名单。仍需Backend实现这些接口与模型注册查询、worker提供个人prepare/cache/preview、以及Voice试听产物到组合Avatar preview的合法音频边界；不能用arbitrary config map绕过。

## 7. 下一步与完成条件

依已冻结v0.3.1实现私有AssetStorage及网页向导，接入资源隔离validator、可信人脸检测器和真实已审查的克隆服务，再做个人多形象worker与组合preview，最后在用户本人授权素材、已运行GPU上完成真实链路及人工评估。需要GPU时使用用户明确配置且已运行的资源，本模块不创建收费实例。

验收方法与本轮实际结果分别见 `VOICE-CLONE-EVALUATION.md`、`AVATAR-ASSET-SECURITY.md`、`PERSONAL-AVATAR-ACCEPTANCE.md`。
