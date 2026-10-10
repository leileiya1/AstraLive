# SoulX GPU Worker 运维

## 2026-10-10 已部署实例

RTX3080 10GB完成直接Worker短测及3714.792s真实媒体连续运行/同步检查；按用户要求结束追加测试，当前已正常停止Worker和隔离应用/测试接收器，云实例仍保持开机。固定模型、venv、私有配置和缓存元数据保存在持久盘，不需要再次安装下载。日常操作入口：

```bash
/root/autodl-tmp/astralive-services/soulx-lite-01/bin/astralive-worker start
/root/autodl-tmp/astralive-services/soulx-lite-01/bin/astralive-worker status
/root/autodl-tmp/astralive-services/soulx-lite-01/bin/astralive-worker stop
```

首次编译时校验开始到READY262.474s，缓存仍在本机的进程重建69.994s；完整崩溃到客户端重新准备72.400s。主机重启/编译缓存清除后可能重新编译，需要重新确认READY，**这不等于重新下载权重**。停止释放显存，模型文件保留；服务停止不会自动关闭云实例或停止平台计费。目前证明单Worker短测及一次独立小时连续链路可用，暂无多房间或月租SLA承诺。严格原生录像1个相等视频PTS与未完成的GPU恢复详见验收文档。

一体/分离安装均使用同一生命周期入口和固定Manifest；应用模块与GPU模块分开升级。平台用户不获得SSH命令入口、GPU系统控制权限或权重路径。完整应用一体安装包、正式Session绑定与跨主机媒体恢复尚有后续gate，详见部署和验收文档。

## 状态与探针

所有GPU探针需要独立management token，且只监听loopback：

| 路径 | 含义 |
| --- | --- |
| `/livez` | HTTP进程可响应；不代表模型已加载或推理健康 |
| `/readyz` | 校验、模型、预处理、三块预热、编码器Gate完成且健康；否则503 |
| `/v1/status` | 状态快照，包括准备期ready=false |

业务前端只调用Go `GET /api/v0.3/config/profiles/{profileId}/worker-status`，复用现有安全cookie和tenant+user校验，并检查操作员物理worker ACL。该GET仅观察，不启停GPU、不修改default/verification。原Profile的60s stale health规则继续保留；本状态接口是即时probe，不把probe结果写成LLM/配置验证成功。

状态提供：ready、health、modelRevision、avatarCacheStatus、gpuAllocatedBytes/gpuReservedBytes、trueGeneratedFPS、modelComputeFPS、generatedFrames/publishedFrames、queueDepth、lastError、workerEpoch、generationCancelStatus、diskFreeBytes/diskTotalBytes、GPU utilization/temperature/device memory、mode。Go只投影允许字段；processPid仅供本机supervisor识别子进程，不发往前端。

CUDA allocated/reserved是该进程的PyTorch分配器计数；device memory是nvidia-smi单卡采样，二者不可混同。GPU采样5s一次、命令截止2s；多GPU或采样失败时设备指标为null，不能冒充0。CPU模拟的显存始终null。磁盘低于默认1GiB使ready=false并触发有限恢复。日志使用Python标准RotatingFileHandler，当前文件+有限备份均有大小上限。[Python轮换语义](https://docs.python.org/3/library/logging.handlers.html#rotatingfilehandler)。

## 常见操作

安装完成后使用安装器打印的 `.../bin/astralive-worker start|stop|restart|status|probe|doctor`，无需每次设置环境变量。此 `start` 校验环境并等待模型READY才成功；返回78表示首次资源/环境缺失或不兼容，返回70表示启动未就绪/重试用尽。安装成功本身只说明代码/配置已就位，不代表模型就绪。

若需要容器启动自动运行，将固定的 `.../bin/astralive-worker run` 配置为现有容器启动入口；本轮没有代替用户修改云平台启动设置，不依赖systemd。仅有detached start无法跨容器重启自动复活；平台前台入口配置一次后才能提供该能力。第一次选择相同基础镜像、预置离线模型环境，之后恢复持久盘配置/cache。

升级先正常业务Stop，再Worker stop，对新可信包运行install；不重复pip或下载权重。安装锁/监督器锁拒绝运行时升级。回滚可以安装保留的上一可信包，配置和token沿用；故意修改配置/token前先停机并协调Backend/Runtime登记。`previous`仅保留上一代码指向，不能用历史PID文件控制进程。

1. 新部署先运行 `cli check`，再 `start`，等待 `probe` 成功。启动阶段模型只加载一次，不能重发Begin绕过READY。
2. 修改素材/model identity、token或路径：停止服务后更改操作员配置，再restart；不能热替换当前业务generation的avatar。
3. Token轮换需协调两个服务器的私有文件并restart GPU服务；旧token不得输出日志，Worker管理token与推理token分开。
4. 正常业务收尾先调用原Go Session Stop，等待ENDED和媒体cleanup，再调用Worker `cli stop`。测试直接终止Worker仅用于故障注入，不代替Session Stop。
5. `cli restart`通过安全控制socket停止监督器后重新启动。不要直接信任历史PID；state文件仅提供观察，不提供任意系统控制能力。

## 故障处置

| 现象 | 检查与动作 |
| --- | --- |
| STARTING持续 | 查看只读supervisor状态/轮换日志中的WeightsVerified、ModelLoadStart、WarmupBlock；核对本地权重和固定环境；不自动下载 |
| UNHEALTHY / INFERENCE_STALLED | 保留当前Session本地fallback，检查GPU计算进度、队列、驱动；旧CUDA工作完成前禁止复用模型 |
| 连接断开 | 确认loopback探针、已有SSH隧道和主机密钥；client围栏失效epoch，当前source PCM继续Lightweight |
| video队列满且进程健康 | 检查实际消费/credit；这可能是正常播放背压，不增大队列/超时 |
| DISK_LOW | 检查持久盘和应用轮换日志。只清理明确归属的过期产物，保留原证据/权重 |
| EXHAUSTED | 初始+最多3次重启已用尽；修复原因后操作员显式restart；没有自动购机/无限循环 |
| worker-status 401/404 | 使用现有登录cookie；404包括跨scope Profile/物理Worker，不能通过新建自己的Profile绕过 |
| worker-status 409 | logical worker未登记；不能虚报UP |
| worker-status 502 | 探针超时、token/响应/端点不符合要求；错误为静态文字，无私钥/IP/source URL |

Supervisor连续三次ready后探针失败才重启；startup最多300s，停止最多40s。恢复失败业务仍保持Lightweight，可在未来新Session重新准备。客户端在默认300s窗口内最多24次恢复尝试（退避上限15s），只在当前故障轮次执行，成功候选只在新语音边界提升；恢复不意味着回放失效的generation。

FORCE的`PUBLICATION_FENCED`表示旧音频/帧发布资格已取消、队列清除，CUDA kernel可能仍在运行；它不等于物理解码器/RTMP缓冲中零旧画面。原接收端fence与已验证的在途残留限制保留，不能把cancel ACK解释成硬抢占GPU。

## 日志与磁盘

Worker、supervisor、Runtime avatar、paired clock使用固定逻辑文件名及轮换上限，不按utterance保存PCM/视频。只保留数值/标识/事件/静态错误码；过滤token、原始exception/traceback、URL及媒体payload。子进程也不继承LLM/TTS/商家Key，库stdout经supervisor有界读取和脱敏写入。

`avatar-cache.json`只记录经校验的identity；`supervisor.json`记录生命周期及本机PID，`worker-last-exit.json`记录允许的静态启动失败码；`supervisor.lock`/`control.sock`仅在私有state目录。重启后检查epoch已改变、metadataRestored、preprocessingRebuilt，以及model load count每进程1。不得恢复旧队列、旧decoder、未确认pose或旧Session业务权限。

## 发布与回滚

Worker服务可以独立部署/观察，生产默认Avatar Provider不改。Agent 1的业务Session绑定接入尚有明确gate，UI default选择不代表Runtime已经使用SoulX。显式绑定集成使用 `bound_factories`，并由现有Backend负责绑定expiry/release。

RTX3080已完成直接短测与隔离实时链路的小时连续/同步检查；完整严格录像项和恢复验收未全部通过。正式Session Binding及整套一体/分离安装器仍待交付，后续优先补安装交付，不默认反复追加推理测试。回滚时恢复上一版本的可选绑定/工厂和部署配置，业务继续使用Lightweight；实验代码、原素材、旧验收证据保持可用。不要因本地单元测试或直接Worker通过就切换全局Provider。

## 验收操作端与服务器部署

本次lab隧道经过Mac，用户合盖导致一次中断；该尝试保留FAILED，不归因为GPU崩溃。临时 `caffeinate` 只保护driver运行期间，不能阻止合盖睡眠，已随测试结束退出。长期分离部署应由应用服务器直接维护到GPU的授权隧道，避免依赖客户Mac；这是完整部署编排待补项，不把lab连接方式作为商用部署承诺。
