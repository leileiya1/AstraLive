# AstraLive v0.3 SoulX GPU Worker 产品化设计

更新2026-10-10；内部推理协议 **1.1**，管理状态 **1.0**。非GPU回归、2080Ti部署模拟及用户授权的RTX3080固定模型直接Worker短测通过，RTX3080隔离真实媒体连续3714.792s/六个同步检查点已通过；严格原生录像PTS、完整恢复与正式业务绑定仍有gate。整套商业一体／分离安装器尚未交付，生产默认 Provider 保持原值。

## 基线与边界

### 2026-10-10 用户确认的安装方向

同一产品采用可选模块，支持一体安装与分离安装。应用模块包含前端、Go Backend、Runtime及现有业务存储；GPU模块包含本Worker、固定推理环境、模型和Avatar缓存。一体安装在同一台满足兼容性要求的NVIDIA/Linux主机部署两个模块；分离安装在应用主机部署应用模块，在GPU主机仅部署GPU模块。客户浏览器始终访问Go Backend，GPU模块不引入第二套业务数据库、用户认证或LLM/TTS凭据。Windows/macOS的完整一体安装尚未验收，不能由Linux云GPU测试推出支持。

两种方式共享同一Worker协议、模型Manifest和配置契约；区别是操作员登记本地端点还是安全隧道端点，不能复制两套业务逻辑。模型/环境放持久目录，代码更新与停止重启不删除或重新下载；首次准备和明确模型迁移属于独立部署阶段。当前可执行产物是独立GPU安装包；整套应用组合安装、平台启动编排及完整媒体绑定仍待实现/验收，不宣称已有全平台一体安装器。

必读基线：[最终专项验收](astralive-avatar-lab/reports/SOULX-FINAL-ONE-HOUR-PINNED-ACCEPTANCE.md)、[环境复用](astralive-avatar-lab/reports/SOULX-DEPLOYMENT-REUSE.md)、[Worker 设计](astralive-avatar-lab/reports/GPU-WORKER-DESIGN.md)、[原私有协议](astralive-avatar-lab/streaming/PRIVATE-PROTOCOL.md)、`worker_final.py`、streaming 代码与测试。

原连续 3600.781 秒音画同步专项 PASS、正常 Stop/Cleanup PASS 保留。末约五分钟 LLM 鉴权失败仍是全业务验收限制。它不等同于本次新服务的发布 PASS。固定 SoulX Lite、512×512、原 Python 3.12.3 / Torch 2.8.0+cu128 / CUDA 12.8 / FlashAttention 2.8.3；模型源码 revision `9bc03de06bb0de82cd6bc477804512ae06144bf2`。不训练、不评选模型、不自动下载或安装 GPU 依赖。

## 实现与所有权

| 路径 | 职责 |
| --- | --- |
| `gpu_worker/config.py`, `model.py` | 操作员配置、素材/Manifest/七个权重 SHA256、源码/环境固定、一次模型加载、三块预热及 H264 Ready Gate |
| `gpu_worker/service.py`, `validated/adapter.py` | 一 Worker 一连接租约、增量 PCM、Session/Epoch/Generation Fence、FORCE、有界流控 |
| `gpu_worker/telemetry.py`, `resources.py` | 进程状态、真正新生成帧、CUDA allocated/reserved、GPU util/temp/device memory、磁盘、轮换日志 |
| `gpu_worker/supervisor.py`, `cli.py` | 容器内启动、停止、重启、健康监督、有限重试、Unix 控制 socket、优雅终止 |
| `gpu_worker/release.py`, `install.py`, `manage.py`, `doctor.py`, `hardware.py` | 可信离线包构建、幂等安装/升级、持久配置/token、日常一条命令、启动前兼容性与READY检查 |
| `gpu_worker/client.py` | 登记表解析、授权 Binding 消费、版本/Session/Epoch 校验、原接收/消费确认逻辑、有限重连 |
| `gpu_worker/runtime_adapter.py` | 可选 Provider 工厂、保留业务 Session 的 Lightweight 降级、下一语音边界恢复、消费确认包装 |
| `backend/internal/userconfig/worker_status.go` | 使用现有 Go cookie 身份、Profile 归属和物理 Worker ACL，返回允许的状态字段 |

GPU 服务不持有商家/直播间业务权限，也不接收 LLM/TTS Key。其子进程环境仅传递白名单环境变量。GPU 不创建/结束业务 Session；业务优先级、音频时钟、事实回答、最终媒体和本地降级继续由 Runtime 拥有。

Mac Audio Health、WebRTC Preview Recovery 原文件未改。`adapter.py`、`wire.py`、`prefetch.py` 原样封存；`async_link.py`、`resample.py` 仅调整包导入。已验证的 Remote Avatar、消费确认和 RTMP Paired Clock 保留其媒体逻辑，移除实验 WAV 录制并将日志改为轮换写入。`runtime/app/session.py` 搬入既有实验的可选 `stream_audio` hook，保留原 TTS 文本证据开关；不改变默认 Provider、公共 Session FSM 或 MediaOutput 实现。

## Avatar Cache

每个逻辑 Worker 固定一个操作员批准的 `avatarRef` 和原始素材 SHA256，拒绝客户端文件路径、未知素材或其他 Avatar。进程启动时预处理一次；多次 PrepareAvatar、多个 Generation 复用同一 resident model/portrait。Cache key 与原验证算法一致，包含模型 Manifest、素材、源码、512/33/9/4/seed42 参数。

持久化的是经过重新校验的 cache identity 元数据，不保存 pickle/CUDA 指针、旧语音、旧 latent motion 或业务状态。重启后元数据匹配则 `metadataRestored=true`，仍重新建立 GPU 预处理和 warmup（`preprocessingRebuilt=true`）；不能宣称零预处理重启。新连接创建独立 Adapter，首次 generation 重置至 portrait；跨 Session 不复用前一 Session 的已消费姿态。允许登记多 Worker，但不宣称一个模型同时服务多房间的容量已经验证。

## 冻结内部通信 1.1

继续使用两段 uint32 网络序长度 + UTF-8 JSON + 二进制 payload；header ≤16 KiB，payload ≤2 MiB。只绑定 `127.0.0.1`；跨主机必须通过操作员配置的已验证主机密钥 SSH 隧道。连接 Auth 除 `protocol_version=1` 外必须带 `internal_version="1.1"`、部署 token 和非空 `session_id`。READY 返回新 `worker_epoch`。后续每个请求/响应都携带该 Session/Epoch；认证前 READY 响应除外。拒绝旧版本，不把实验 Worker 当正式 Worker。

| 消息 | 固化行为 |
| --- | --- |
| PrepareAvatar | 必须匹配固定 `avatar_id=avatarRef` 及 `input_asset_sha256`，返回 cache_id |
| BeginGeneration | ID 在同一 epoch 严格递增；s16le/16k/mono/25FPS、非负 first_sample_index；一个 active generation |
| AudioChunk | sequence、sample_index 连续，长度等于 sample_count×2；只接受布尔 EOF；旧代际拒绝 |
| VideoPacket | H264、无 B 帧、GOP25；每代际新编码器、第一帧 IDR；保留 source sample 派生 PTS |
| Credit | 仅实际消费后逐帧确认；最多四帧在途；只把确认的九帧写入 committed pose |
| CancelGeneration | 立即清除旧队列/发布资格；返回 GenerationCancelled；运行中的 CUDA 在安全边界结束后旧结果被丢弃 |
| Health | nonce、ready、活动代际、最后发出帧、队列和静态错误；RTT 只用请求端单一单调时钟 |

Auth/readiness 5s，连接建立 1s，写 drain 5s，cancel ack 2s，客户端健康报文每 0.5s、连续读取 5s 无响应失效；服务端已认证 socket 15s I/O 截止。监控独立于推理连接。Inference/embedding 无进展 gate 默认 5s，保持与旧 gate 同量级，不用扩容队列掩盖故障。TCP 中已发送的旧包不可撤回，接收端仍必须在解码/消费/最终输出处拒绝旧 Epoch/Generation。

没有引入 gRPC。双向安全边界是已验证 SSH 主机/密钥 + 应用部署 token；不存在无认证公网推理/管理端口。用户平台仅接收逻辑引用，不能配置 SSH/IP/key/命令。

## 时间与有界背压

保留 STEP15360（960ms）、2s/32000 样本入站预算、最多一块 pending 音频、8s 特征窗口、24 帧视频队列、4 帧消费信用、9 帧确认姿态。入站容量不足直接结束当前连接租约，不阻塞控制 dispatch。保持预取源与媒体消费分离；收到较早的 PCM 不等于 GPU 失去消费进度。

`pts_us=first_sample_index×1e6/16000 + frame_sequence×40000`，40ms 视频量子对应640样本。保留现有 Paired RTMP 缺帧时两轨同时 filler 的规则，不添加固定音频延迟。

`trueGeneratedFPS` 是最近10s中新推理输出帧/窗口秒数；`modelComputeFPS` 是 GPUOutput 的 CUDA 同步计算帧数/计算耗时；`publishedFrames` 单独累计已发布新帧。它们均不是浏览器解码 FPS，保持/缓存帧不增加 GPU 生成统计。simulation 模式明确标识，显存字段为 null，其计数不能充当真实 GPU 指标。

## 故障恢复

推理错误/卡死或磁盘不足导致 ready=false；Supervisor 启动截止默认300s，ready 后连续三次健康失败则停止子进程。优雅退出默认40s，超过截止才强制结束。一个 Supervisor 生命周期最多初始启动+3次重启，退避1/2/4s（上限15s，有限抖动），用尽进入 EXHAUSTED；不会购机、开机、扩容或循环重试。

Runtime 连接失败后取消/围栏当前 Worker job，继续相同业务 Session 的源 PCM 和本地 Lightweight 画面；健康检查失败不直接发 Session Stop。当前 fallback job 不回放 GPU 旧工作。客户端在与startup gate对应的默认300s恢复窗口内最多24次重连（指数退避，上限15s）；准备成功的候选连接只在新语音边界替换。用尽则保持降级，可在之后创建的新 Session 重新尝试；不在每个20ms样本上无限重连。

## Agent 1 与集成边界

消费冻结的 `GPU_WORKER/soulx.config.workerRef`、`AVATAR/soulx.config.avatarRef`、`workerProfileId`，没有第二套用户数据库/认证服务。`bound_factories(binding, registry_path, scope, session_id, ...)` 仅接收 Go 已解析的不可变 Binding 和可信 scope；它同时核对物理 Worker 的操作员 ACL。

现有 Go 业务 Session 路由尚未捕获/解析 Agent 1 Binding，冻结的 USER-CONFIG-CONTRACT 已明确该集成 gate。本次提供可调用工厂和真实 RuntimeSession CPU 测试，不把配置页 default 选中冒充已切换 Runtime。实际 Session 路由接入需要消费该接口，保留 Binding release/expiry；本次没有偷偷把全局默认改为 SoulX。消费确认适配器仍要求一个实际 WebRTC peer；纯 RTMP 无 peer 的部署需要后续消费确认接口/验收，不能宣传已支持该模式。

新服务在RTX3080完成短时直接GPU验证，数据见验收文档。可选正式 `stream_audio` hook 和新的服务/恢复编排触及媒体路径集成，因此正式启用时要做对应完整媒体回归；旧小时专项 PASS 不能覆盖新恢复与发布编排。不重跑未变化的一小时模型基准。

## 最新交付判定

已验证独立GPU组件能够驻留运行并完成真实增量PCM、FORCE、WebRTC/测试RTMP和正常Stop；固定环境与权重可持久复用。用户要求停止继续测试，未启动独立网络故障run，已注入的恢复run按用户要求正常Stop，不宣称完整恢复PASS。

“用户提供服务器后选择一体／分离并部署整套产品”的要求仍未完全达到：缺统一应用+GPU安装入口、固定基础镜像交付/新空主机恢复证据和正式Go Session Binding集成。7.73GiB离线增量包不是全平台自包含镜像。下一步应完成安装交付，不用反复模型基准代替产品就绪。
