# 备份与清理

按用户费用安排，本次不执行一小时测试。GPU推理已停止，已取回最终代码、阶段A/B/浏览器真实日志、原版本和增强版本ready信息、环境包版本、官方代码commit、权重版本/SHA、实际输入与代表性可播放视频。不备份访问token、SSH私钥、LLM密钥、整个GPU虚拟环境或15GB完整权重。

Mac保留：streaming全部源代码/协议/实验Runtime副本、reports、原始时间戳与性能JSONL、阶段A两段60秒、GPU待机切换片、10分钟接收末段、真实LLM/TTS MP4、浏览器正常/FORCE/断线WebM及失败证据。唯一244MB已验证FlashAttention2.8.3 wheel保留，便于恢复已验环境，避免再次长时间CUDA编译；普通可重新下载轮包和下载残片已清理。

已从Mac删除134个冗余文件，2142378776字节（约2.14GB）：不完整Torch下载、权重拼接tail、普通Linux wheel缓存、弃用的本地MuseTalk权重、重复模型视频与中间H264/WAV、600秒完整视频本地副本。逐文件SHA/大小/理由在STREAMING-CLEANUP-MANIFEST.json。代码、报告、关键输入、性能/失败日志不删。

school-linux的前期结果档案仍保留完整169文件/25MP4，本次实际重新校验0缺失/0不匹配；完整600秒Worker视频也保留。Mac保留其10秒末段和全部PTS日志。历史RESULT-SHA256SUMS是当时完整档案的清单，Mac清理后不能再宣称其169项全部存在；需到school档案检验历史全量证据。新收尾归档使用独立manifest。

云GPU不再需要复制的内容：虚拟环境本体、CUDA/系统缓存、15GB全部模型权重、MuseTalk环境和权重、轮包目录、重复输出。通过官方指定commit和权重manifest可重新恢复SoulX Lite，保持Torch2.8/cu128和FlashAttention2.8.3。关机/销毁后不假定实例文件仍存在，下一次必须重新检查。
