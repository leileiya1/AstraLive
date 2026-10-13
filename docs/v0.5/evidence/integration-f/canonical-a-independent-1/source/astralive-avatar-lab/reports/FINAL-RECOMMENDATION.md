# AstraLive GPU 实验结论

Verdict：`READY — SOULX LITE ONLY`

两模型实际推理、视频、独立600秒持续测试均完成并通过。用户盲看同源短片选择B（SoulX Lite）“最自然好看”，并确认soulx-long与soulx-soak-end“能接受很自然”。SoulX为下一阶段实验Worker首选；MuseTalk保留对照，不作为本次选定集成模型。此状态不表示正式直播链路验收，也不授权改生产服务。

Benchmark JSON保留生成时的“待视觉验收”状态作为原始记录；最终人工确认和Verdict以visual-acceptance.json及本报告为准。

## 用户要求的十三项回答

1. **真实环境**：GPU是NVIDIA RTX4090D，24564MiB，SM8.9；不是普通4090。Driver580.105.08，Driver API支持CUDA13.0，Toolkit12.8.93。原base Python3.12.3、Torch2.8.0+cu128、torchvision0.23.0+cu128，实测CUDA可用。MuseTalk另建Python3.10/Torch2.0.1+cu118环境；SoulX独立venv复用原Torch2.8/cu128。
2. **保留与新增**：保留系统驱动、Toolkit、base Torch/CUDA。新增隔离环境、MuseTalk官方MMLab运行依赖、SoulX的版本约束运行依赖/FlashAttention2.8.3、签名Ubuntu FFmpeg等CPU库。原base freeze、隔离freeze/conda export、pip check、CUDA验证均保存；具体修复见依赖报告。
3. **MuseTalk是否真跑通**：是，V15官方Normal真实生成22.48秒MP4；中文10/30/60秒及连续/静音/同源图片实验均有实际MP4，完整解码、音轨匹配通过。图片Normal有导出后的上游清理错误，已明确保留证据，不视作零错误命令。
4. **MuseTalk有效FPS**：缓存后包含编码封装为35.907/34.952/36.058FPS，音频/模型/VAE/合成估算45.891–48.276FPS，核心UNet242.702–270.894FPS；封装25FPS不是推理速度。冷启动Normal端到端仅4.788FPS。
5. **MuseTalk自然度**：抽样未见严重五官畸变，动态嘴型/牙齿/唇缘/闪烁/循环连接仍待人工观看，不填主观评分。其眨眼和头部动作主要来自源视频，图片输入不自主生成头部运动。官方Sun仅证明人物外观，未确证真人拍摄或商业肖像授权。
6. **SoulX Lite是否成功**：是，官方stream生成65.92秒/1648帧MP4，中文10/30/60秒真实输出并完整解码；只运行Lite，不运行Pro或训练。
7. **SoulX有效FPS**：预热常驻包含编码61.223/63.197/64.551FPS；核心去噪CUDA159.411–166.174FPS，模型+VAE92.247–96.204FPS，范围定义不同不能与MuseTalk核心直接排名。全冷官方端到端7.862FPS、首GPU块179.285秒；预热短任务首CPU块300–327ms，另有实际流式0.96秒音频积累。
8. **谁更适合**：用户已选择同源B并接受长片和长期末段，结合实测吞吐与自主动作能力，SoulX Lite为下一阶段Worker首选；MuseTalk保留对照/视频缓存方案。高FPS不等于更快TTS首字响应，不宣布生产系统就绪。
9. **谁更稳定**：MuseTalk600.112秒与SoulX600.319秒均通过，各真实生成15,000帧，零丢帧/超40ms迟到。没有证据据此宣布谁在多小时/多日更稳定。
10. **长期效果**：SoulX 600秒末段抽样未见明显身份漂移，并有开始/中段/末尾实际生成视频；用户已接受末段的动态效果。MuseTalk存在缓存动作循环限制；没有依据宣布一小时/多日质量赢家，也不声称逐帧人工审阅了完整600秒。
11. **单卡够一个房间吗**：本4090D的实测预热算力对一个25FPS头像Worker有余量。只测单模型进程，不承诺多房间，也不把本地帧消费测试当成公网传输/WebRTC/RTMP/业务直播链路验收。
12. **3080 10/12GB值得吗**：值得做下一轮隔离短测，12GB优先；本次显存用量提示可能有空间，但3080实际FPS/峰值未测，不能保证25FPS。先验证SM8.6的扩展ABI、batch/预处理显存，再测相同音频；不自动租新卡或购买服务。
13. **如何接Worker**：先审阅私有接口设计，再实现实验Worker，不改冻结公共API。模型加载一次、缓存、epoch+generation ID、PTS由音频采样计数派生、bounded credit queue、FORCE立即失效旧帧、健康/重启、H264低延迟传输；Runtime持有Session及Lightweight降级。增量TTS、取消/旧帧拒绝、idle连续性、网络A/V同步和真实长期媒体验收仍必须单独做。

## 安全与交付边界

没有修改school-linux正式Runtime/WebRTC/RTMP，没有部署直播平台，没有训练、换驱动、重装OS、增购GPU或开放公网服务端口。school-linux只读素材检查和独立结果目录写入。

结果备份目录：本机 `astralive-avatar-lab`，school-linux `~/AstraLive/experiments/real-avatar/results/rtx4090d-2026-10-08/`。模型缓存、安装轮包、SSH私钥与完整环境变量不作为实验成果同步。最终完整性清单见备份验证报告。

云服务器仍在计费。请在观看结果、确认备份完整后由用户手动释放实例；Agent不会自动释放。此前在聊天中发送过的密码应轮换。
