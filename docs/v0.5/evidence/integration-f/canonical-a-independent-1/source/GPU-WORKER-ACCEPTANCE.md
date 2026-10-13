# SoulX GPU Worker v0.3 产品化验收

## 2026-10-10 RTX3080 实时全链路与交付结论

**RTX3080 10GB 当前单Worker可用；连续运行和同步检查 PASS。完整严格媒体文件验收非全PASS，整套商业安装交付尚未完成。** 用户要求停止继续测试，已停止后续故障验收并正常清理，不再追加推理基准。

独立Session `session_0d4094ac076d902affe2985bbff31166` 连续 **3714.792s**、191轮语音、**63次正式FORCE**。链路为隔离Go公共Core API → 真实DeepSeek流式LLM → 真实Sherpa VITS增量TTS → 产品Worker私有协议1.1 → 真实Chrome WebRTC及本地测试RTMP接收器。固定SoulX Lite/512×512和原GPU环境未变，生产默认Provider未切换。此为操作员授权lab binding；不替代正式Go配置Binding接入或真实直播平台验收。

| 检查点 | 实际采样秒 | 浏览器播放偏差P95 ms | 原生录像相关测量P95 ms | RTMP录像P95 ms | 结果 |
| --- | ---: | ---: | ---: | ---: | --- |
| 90s | 90.006 | 9.00 | 98.625 | 40.000 | PASS |
| 5m | 300.004 | 11.00 | 23.000 | 40.000 | PASS |
| 15m | 900.005 | 46.05 | 57.991 | 40.000 | PASS |
| 30m | 1800.004 | 38.05 | 45.688 | 40.000 | PASS |
| 45m | 2700.003 | 34.05 | 32.688 | 40.063 | PASS |
| 60m | 3600.004 | 33.00 | 31.688 | 40.063 | PASS |

关键业务失败0、canvas generation fence违规0、队列越界0；同一peer与Worker epoch `f987ad3d9eee4421bd0f7a657ac9ba79`。allocated峰4.344GiB、reserved峰5.338GiB、device used采样峰5.624GiB，队列峰32000样本/24帧。管理10s窗口trueGeneratedFPS采样0–28.8（包含准备/idle），累计modelComputeFPS采样最高44.210；这些不是浏览器解码帧率或未限速吞吐。此前短测35.422新解码帧/s仍单独记录，不混用口径。全小时播放估计偏差P50/P95/max=22/33/**284ms**，保留瞬时峰，不声称所有样本均低于150ms。

最终录像相关测量保留全部窗口：原生3690个可信窗口，最大176.5ms；RTMP984个，最大60ms；两者无>250ms窗口及音频PTS gap。RTMP审计移至接收服务器执行，算法、窗口及P95≤150ms等阈值未变，避免VPN传输增长中录像超时。完整RTMP原文件留在school-linux，完整解码、SHA256/字节数/路径保存在 `rtmp-remote-decode.json`。

完整文件解码：原生93687 video/62483 audio、canvas77293 video/62483 audio、RTMP93605 video/175579 audio。所有音频均无>4ms gap；canvas及RTMP两轨严格单调。**原生WebM视频第68626帧与前帧PTS同为2745.245s，严格解码检查exit1**：仅1处相等、无倒退，不删除样本或放宽断言。该时间附近50个真实呈现帧RTP timestamp没有重复，但记录器与RTP的精确起因尚未确定。连续播放和同步PASS保留；`fullAcceptancePassed=false`，不宣传全部严格媒体项通过。

正常Stop LIVE→ENDED，Runtime activeSessions0，受控Runtime/Go Backend/RTMP FFmpeg reader及driver均退出。后续恢复Session在用户要求停止前已注入一次受控Worker child crash，实际显示958个Lightweight帧；随后按用户要求通过正常API Stop进入ENDED，GPU完整恢复未验收，不写PASS。原浏览器FAILED/peer disconnected保留，并以 `controller-abort.json` / `controlled-stop-classification.json` 记录人为Stop原因。独立隧道故障run仅准备、未启动。

最终Worker supervisor STOPPED、GPU1MiB基线；两个Session及应用进程清理完成，测试MediaMTX停止，Mac临时防休眠及本次两条SSH control master结束。云实例、固定环境、权重、cache元数据和离线包保留；没有自动关机/购机。

证据目录：`astralive-avatar-lab/streaming/integration/soulx-product-3080-one-hour-local-audit-20261010/`，包括 `acceptance-summary.json`、六个checkpoint、全部相关窗口、完整解码/单个PTS异常审阅、正常Stop和进程/显存清理。新harness在 `gpu_worker/tests/live_acceptance/`；本轮CPU服务/部署20条PASS、既有媒体36条PASS、capture清理2条PASS。

前序失败原样保留且不累计时长：31分钟尝试因FORCE前空WAV采集错误失败；106秒尝试因跨Context清理错误主动中止；246秒尝试因用户确认Mac合盖/SSH中断失败；一次重连启动因旧受控隧道端口占用失败；371秒尝试因增长中RTMP文件rsync超时失败。修复只涉及lab采集/审计/隧道恢复与临时防休眠，不重写已验证媒体算法。最后独立3714.792s结果不改写旧尝试为PASS。

**安装交付边界：** 已有可复用独立GPU模块、固定launcher和约7.73GiB离线增量包；日常启动/重启/升级代码无需重新pip或下载模型。包仍依赖匹配的基础Python/Torch/CUDA镜像，未在新空主机完成恢复。尚无前端/Go/Runtime/存储/GPU的统一一体或分离安装器；正式Session Binding接入仍有gate。因此不声称“客户只提供任意云服务器即可自动部署整套商用产品”。用户明确不继续加测；后续优先补交付安装，而非反复跑模型。

## 2026-10-10 RTX3080真实Worker短时验证

**PASS_DIRECT_GPU_SMOKE。** 用户授权在新租用实例首次恢复固定环境与权重并查看效果。实际RTX3080 **10GB**、12vCPU/40GiB RAM/50GiB数据盘；基础Python3.12.3、Torch2.8.0+cu128、CUDA12.8保持不变。独立venv固定FlashAttention2.8.3/PyAV17.1.0及原环境锁依赖；SoulX源码仍为 `9bc03de06bb0de82cd6bc477804512ae06144bf2`，七个原权重SHA256全部通过，没有训练或换模型。

| 项目 | 本次直接Worker证据 |
| --- | --- |
| 首次启动 | 从Worker开始SHA校验到READY **262.474s**，300s内；首次PyTorch编译较慢。一次加载、三次warmup及编码器READY |
| 增量语音/Idle | 每20ms发送16k/mono/s16le PCM，10s录制语音+4s真实零PCM，350个新GPU帧，逐帧40ms PTS/generation/source断言通过 |
| 实际吞吐 | 另一次未限速10s PCM，250帧/7.058s = **35.422新解码帧/s**，包含特征、推理、编码、loopback传输/解码；modelComputeFPS最高43.696，管理10s窗口trueGeneratedFPS最高31.2。三种口径不同 |
| 首帧 | 实时节奏测试1625.77ms；未限速测试731.87ms。前者包含积累首个960ms PCM窗口，不能当音画偏差 |
| GPU内存 | 0.25s采样allocated峰 **4.293GiB**、reserved峰 **5.338GiB**、device used峰 **5.628GiB**；无OOM。采样不保证覆盖每个瞬时峰值 |
| CPU内存 | Worker RSS采样峰7.794GiB、内核VmHWM **8.320GiB**；不含编译子进程的全容器内存峰，40GiB机器不是测得的最低RAM |
| Avatar Cache | 同进程多代际复用，model load count=1；崩溃后cacheId相同、metadataRestored/preprocessingRebuilt=true，每新进程加载一次 |
| FORCE | 等待实际GPUInferenceStart后取消，ACK **0.505ms**；日志记录一次stale_gpu_output_rejected，新generation4成功。ACK是发布围栏，不是CUDA硬抢占/终端零残留 |
| 崩溃恢复 | 交叉核验本Supervisor childPid后SIGKILL，自动重启换epoch并READY，客户端重新准备耗时 **72.400s**；恢复Worker校验到READY69.994s，generation5成功，无旧任务重放 |
| 有界队列 | 采样audio峰32000/上限32000、video峰20/上限24，测试全程断言通过 |
| 正常Cleanup | 客户端ConnectionCleaned.sender_stopped=true；管理入口stop后supervisor STOPPED/control socket移除/GPU回到1MiB环境基线，无存活受控Worker |
| 预览 | 新GPU推理导出14s H264/AAC、512×512、350 video/219 audio frames完整解码；说话/静音样本抽查无黑帧或人物跳变，不是量化视觉质量评级 |

预览与原始数据：`gpu_worker/evidence/rtx3080-real-20261010/rtx3080-speech-idle.mp4`、`real-smoke.json`、`summary.json`、`worker.log`、`supervisor.log`、环境锁及部署/下载日志。预览按源PTS重封装，**不是实时WebRTC/RTMP播放同步验收**。PCM来自既有10秒录制TTS，本轮没有调用真实LLM/TTS，也没有重复一小时推理。

首次测试脚本从外部目录运行时缺PYTHONPATH，报ModuleNotFoundError，保留 `rtx3080-real-smoke.log`；设置已安装代码目录后完整短测通过，未改模型或放宽断言。依赖直连下载缓慢，改用原官方wheel SHA清单的55个固定Linux wheel中转、逐一SHA校验后离线安装，未改变版本。

CPU部署聚焦回归最后5条PASS/8.553s，增加从已安装代码重新构包检查。真实测试使用release `8bfa0c032e8ffb222180e65aadd9f1dbb18d3a473ebe32af3f65b6e6a1081ac2`；收尾安装release `9c7152c6293dedbd89cf799dac928a6a8925d8399ab58bf4a434d61d791a1ec3`，补入固定依赖清单、首次准备脚本路径与快速无损打包，服务/模型/媒体算法内容SHA一致。代码/配置/token/权重均保留，日常不需要重新下载。对保留的所有队列采样和预览两轨单调PTS完成独立离线审计PASS；后续harness显式传播后台采样断言，不将后台任务失败吞成PASS。

离线增量包导出及独立内容检查 **PASS_BUNDLE_CONTENT_AND_PINNED_ASSETS**（命令exit0）：payload8295258245bytes/约7.73GiB，11183个常规文件、解压大小10816038297bytes；整包清单SHA、gzip完整性、路径/类型、七权重及Manifest/头像共九个SHA逐一通过。源码在 `gpu_worker/tests/verify_offline_bundle.py`，证据 `rtx3080-offline-bundle.json` / `rtx3080-offline-verify-final.log`。检查器初稿把JAX的 `_src/state` 库目录误当业务state而拒绝；已改为明确组件/批准资产路径allowlist，保留初稿错误日志。原慢压缩任务仅中止自身且清理未完成临时包；改用快速无损压缩后有界导出成功。**新空主机恢复尚未验证，基础Python/Torch/CUDA镜像仍必须匹配**；没有将包验证写成全平台自包含镜像PASS，也没有把大型权重备份到Mac。

该短测阶段的真实业务Session断线与正式媒体恢复仍只有此前CPU/旧实验证据；后续全链路及用户中止的恢复尝试见本页最新章节。RTX3080单Worker短测证明这张卡能运行固定模型且本次吞吐有25FPS余量，不能推出多房间容量、月租长期SLA或完整商用发布。默认Provider未切换，云实例没有关闭/删除或变更套餐。

## 2026-10-10 RTX3080连接与基础CUDA检查

用户提供新实例入口并要求连接测试。SSH登录成功，现场是RTX3080 **10GB**（nvidia-smi10240MiB），driver595.91.07、compute8.6、BF16 supported。现有绝对路径 `/root/miniconda3/bin/python` 为Python3.12.3/Torch2.8.0+cu128/CUDA12.8，无需更换基础Torch/CUDA。

实际执行FP16和BF16的CUDA矩阵乘法，同步后校验输出有限且等于预期值，两项PASS。此检查是基础CUDA正确性冒烟，包含首次初始化开销，**不是SoulX推理、性能基准或模型READY**；未安装/执行FlashAttention，仅compute8.6符合固定版本架构要求。

持久盘50GiB且初始为空，未发现原lab/七个权重；FlashAttention、PyAV、transformers/diffusers缺失。没有安装依赖、下载模型、训练、启动Worker或切换生产Provider。尚需首次恢复固定依赖/权重，才可执行真实模型短时验收。

测试Python进程退出后nvidia-smi回到与连接时相同的1MiB，没有受控Worker进程残留；未关机或删除实例。进程内释放测试tensor后仍有CUDA库内部工作区（allocated8519680/reserved20971520bytes），不能把进程内allocator计数误报为零；退出后上下文已释放。证据：`gpu_worker/evidence/rtx3080-connection-20261010.json`及同名`.log`。不把下文2080Ti CPU模拟PASS或4090D专项PASS沿用为3080推理PASS。

历史阶段：2026-10-09。**非GPU服务回归 PASS；2080Ti服务器安装/CPU模拟 PASS；该2080Ti真实GPU推理 BLOCKED（固定FlashAttention2.8.3不支持该卡且模型/依赖缺失）；尚未商用发布。** 用户最初要求暂缓，随后明确提供SSH并要求一次安装/日常直接启动。该阶段没有下载模型；后续3080首次准备已获授权，见上文。

## 后续安装包与2080Ti部署演练

现场只读检查：RTX2080Ti11264MiB、compute7.5、driver580.105.08，数据盘50GiB、初始为空。基础环境在PATH之外的 `/root/miniconda3/bin/python`，Python3.12.3/Torch2.8.0+cu128/CUDA12.8已有；FlashAttention、PyAV、transformers/diffusers、原lab/模型缺失。先前“没有Python”的初步发现仅指PATH；此次已纠正为绝对路径复用。

| 检查 | 实际结果 |
| --- | --- |
| 本地部署新增测试 | 4条PASS：幂等/秘密文件权限/清单篡改拒绝，一条命令READY与restart/cache，停机前升级拒绝/原子code切换/旧版保留，缺组件不创建Worker/架构gate |
| 本地全部Worker测试（含新增） | 19条PASS、22.707s；真实子进程/CPU模拟/旧录像短段解码，不是GPU推理 |
| 服务器代码包install | PASS；自动生成独立私有config/token/state、版本目录、固定launcher；升级保留既有配置和token |
| 服务器GPU `start` | 预期拒绝：preflightPassed=false、exit78，缺模型/source/依赖且compute7.5不兼容；没有创建supervisor/control socket或下载模型 |
| 服务器CPU `start / status / restart / stop` | PASS；`mode=simulation`、READY、重启epoch改变、cacheId相同、metadataRestored=true；allocated/reserved=null |
| 服务器原服务测试5条 | PASS，20.496s：PCM/FORCE/PTS/cache、鉴权/Session/消息上限、SIGKILL/新epoch/cache恢复、消费credit耗尽健康可响应/取消恢复、管理鉴权/正常Stop |
| 收尾 | 测试进程全部退出、GPU0MiB；没有关机/删除实例或更改月租套餐 |

只为独立CPU验证venv安装PyAV17.1.0（35.4MB），复用已有基础Torch/Python；未给基础环境安装包，未安装FlashAttention/下载权重/更改模型。部署目录在持久盘，测试与GPU配置隔离；管理/推理均loopback，没有新增公网推理端口或接入生产Provider。

首次使用macOS系统tar打包时携带AppleDouble文件，严格清单校验拒绝安装（RELEASE_FILE_SET_MISMATCH），未绕过校验。已改为Python tarfile跨平台归档重新构建，之后实际安装/验证通过。记录于安装包说明，非GPU失败不改写成模型失败。

该2080Ti阶段证据：`gpu_worker/evidence/remote-deployment.json`、`remote-deployment-setup.log`、`remote-deployment-validation.log`、`deployment-cpu.log`、`production-deployment-cpu.log`。日志按原*.log忽略规则保留本地；远端SSH密码未写入代码、配置或日志。该阶段发布物是**代码包**；后续3080导出离线增量包，见最新部署说明，不能宣称已交付包含基础CUDA/Torch的自包含GPU镜像。

3060 12GB兼容当前architecture gate，是低成本待测候选；旧显存占用支持容量可能足够的判断，但尚无3060 FPS/块耗时/尾延迟数据。24GB不是测得的最低要求，32GB系统内存也只是余量建议。按单Worker单房间短时测量连续语音每960ms块特征/推理/编码能否跟上、队列不持续累积，FORCE、idle/talking、掉线与cleanup后，再决定月租。显存容量足够不等同实时验收。

## 原验收的使用范围

保留原Pinned报告：同Session连续3600.781s、音画同步专项PASS、正常Stop/Cleanup PASS；不改原结论，不删末约五分钟LLM鉴权失败的全业务限制。新的3080直接Worker数据见上文；不把旧的18.46新帧/s、4.33/5.34GiB峰值作为新产品服务测量值。

## 本轮命令与证据

| 命令 | 实际结果及边界 |
| --- | --- |
| `gpu_worker/.venv-tests/bin/python -m unittest discover -s gpu_worker/tests -p 'test_*.py' -v` | 15条PASS：新服务真实子进程/CPU模拟、认证/隔离、PCM/FORCE/PTS、崩溃/cache、新Session job、业务Session保活/fallback、背压健康、正常控制Stop、重复启动和有限retry、日志脱敏、登记授权、模型/Manifest SHA校验、取消Ready等待cleanup、paired underflow、旧录像decode |
| `gpu_worker/.venv-tests/bin/python gpu_worker/tests/run_legacy_regression.py` | 原36条PASS；CPU mock CUDA barrier，保留原断言，包括取消在途推理、旧结果拒绝、消费credit、streaming EOF、resample、降级、原Mac音频故障证据、paired clock/cadence |
| `PYTHONPATH=runtime gpu_worker/.venv-tests/bin/python -m unittest discover -s runtime/tests -p 'test_*.py'` | 最终本轮workspace快照113条，102执行通过/11skip；包括同时进行的其他模块已有测试。skip不计真实服务验收 |
| `(cd backend && go test ./...)` | PASS；增加本机认证probe、64KiB/worker identity、字段投影、cookie、scope Profile与物理Worker ACL测试。Postgres环境相关测试按原条件skip，没有声称数据库集成PASS |
| `node astralive-avatar-lab/streaming/test_browser_audio_health.js` | 12条PASS：固定输出设备、真实播放健康、设备变化/恢复等原逻辑 |
| `node astralive-avatar-lab/streaming/test_final_player_gate.js` | 10条PASS：ready/fallback/refresh原Gate |
| `bash -n .../start-cached-soulx-worker.sh gpu_worker/deploy/run-worker.sh`、`git diff --check` | PASS；部署脚本语法/空白检查不是GPU启动验证 |

可检查摘要及环境锁保存在 `gpu_worker/evidence/summary.json` / `cpu-environment.txt`，sanitized CPU/命令日志本地保存在同目录（*.log按现有Git规则忽略）；测试源码保留于 `gpu_worker/tests/`。CPU环境：Python3.12.13、Torch2.14.1、av17.1.0、numpy2.5.3；与固定GPU环境严格区分。没有修改GPU的Python/PyTorch/CUDA安装。共享workspace测试在执行期间新增了personal-processor用例，首次复跑因独立测试venv缺jsonschema而失败；只在CPU测试venv补齐依赖后，113条/11skip通过，未修改该模块或断言。Go相关package另以 `go test -race ./internal/userconfig ./internal/httpapi` 通过。最后服务边界补强后，客户端cleanup及service7条、READY1条、supervisor2条聚焦检查均PASS；日志和摘要保留两轮证据。

## 实际覆盖

- 启动READY、三块CPU warmup和实际H264 encoder/decoder，model load count1；进程crash后的新epoch、相同cache identity元数据恢复及重新预处理。
- 实际CPU service私有socket增量PCM、非零sample origin的40ms PTS、FORCE后新代际完成；四帧消费信用耗尽时queue保持24帧/32000样本边界，健康继续可响应，FORCE可恢复。
- 正常Unix控制Stop与socket清理；第二Supervisor拒绝；故意不匹配素材导致初始+一次配置retry后EXHAUSTED，退出70，无无限重启/云动作。
- 实际Runtime SessionManager使用新Provider和**测试消费sink**，Worker子进程SIGKILL后同一业务Session保持LIVE、Mock PCM仍达到源样本数、Lightweight输出、utterance完成、正常ENDED和移除Session。该sink模拟消费计数，不代表真实浏览器/RTMP播放验收。
- 同Pinned录制文件的只读前15秒decode：native250 audio/372 video frames，canvas251 audio/285 video frames；音频PTS连续性通过。仅短段解码和原证据断言，不是新小时音画测量。
- 拒绝坏token、跨Session控制；恢复的新epoch不沿用原连接；状态API不允许caller-owned Profile引用外用户的physicalWorker ACL来读取数据。

## 待执行的短时真实GPU检查

在用户提供的兼容实例（4090D已有基线，3060 12GB待测）上执行；不购买/自动开机。不得沿用4090D结果冒充3060通过。

| 项目 | Gate / 应保留证据 |
| --- | --- |
| 启动 | 七文件SHA256、固定环境/source、model load一次、三warmup、编码器READY、epoch |
| cache复用 | 相同avatar两次Prepare/多generation不重新加载；restart新epoch、cache identity匹配、元数据恢复与预处理重建 |
| 增量语音 | 真实逐20ms source PCM而非预生成视频；单调sample/PTS、首帧、真实新生成/发布FPS、allocated/reserved/device memory分别记录 |
| FORCE | 运行中切代际，旧计算/transport拒绝、cancel状态、新IDR；承认已在媒体缓冲的旧画面限制 |
| Idle/Talking | 同人物静音/说话/恢复idle视觉抽查和逐帧源标识，不将cached/held帧算新推理 |
| Worker停机/恢复 | 同业务Session继续源音频/Lightweight；新epoch准备后仅未来job提升，无旧工作replay |
| 断线 | 隧道/worker健康超时触发fallback、队列有界，恢复失败仍Session LIVE |
| 正常Stop | API→ENDED、Runtime会话/队列cleanup、FFmpeg/peercleanup，之后停止Worker，显存释放及无受控残留 |

3080已完成上文所列直接Worker项目。此表为短测阶段计划；本页最新章节补充WebRTC/测试RTMP及API正常Stop结果。完整GPU恢复/独立隧道故障仍未验收，严格原生录像PTS尚有记录项，不把整表写为PASS。

## 发布限制与后续完整回归

本次迁入可选 `stream_audio` hook及新的版本化服务/恢复管理；正式媒体路径集成有变化。启用对应绑定时需要完整的真实WebRTC/RTMP、FORCE、掉线/恢复、PTS/播放健康和正常Stop回归，不能把旧专项PASS当新编排已验收。该回归不等于重新跑未变化的一小时模型性能基准。

既有Go Session路径尚未接入Agent 1 Binding capture/resolve；提供 `bound_factories` 消费接口和本地RuntimeSession回归，不伪造授权身份或default已生效。纯RTMP无WebRTC peer的消费确认也仍有集成gate。CPU模拟不证明GPU环境部署、真实avatar视觉或发布就绪。原有效媒体修复、默认Provider、实验文件/录像/权重保持其既有状态。
