# ISSUE-011 — 个人 Avatar/Voice 产品接入与真实验收缺口

日期：2026-10-09。状态：OPEN；缺少基础契约这一子项已由Agent 1 v0.3.1交付解决。负责边界：Backend/AssetStorage、Frontend、GPU Worker及本Avatar/Voice模块分别完成各自接口；本文件不修改冻结Contract。

## 已完成对接

Agent 1已交付 `AVATAR-PROFILE-CONTRACT.md`、`VOICE-PROFILE-CONTRACT.md`、`ASSET-STORAGE-CONTRACT.md`、`personal-assets/schema.json`和`backend/internal/personalconfig/contracts.go`。本模块直接消费schema，实现assigned claim、摘要input、output reservation/PUT、result、15秒heartbeat、有界deadline/旧租约取消，个人VoiceProfile到已注册本地引擎，以及Linux受限decoder启动器。共42项格式/Voice/processor/隔离控制单测通过，SIMULATION不能mark REAL readiness；实际Linux和真实引擎未验收。

## 待解决事实

- Go接口/DTO不是已部署个人素材HTTP handler、SQL表、私有AssetStorage、配额/删除reconciler的证明。
- 当前XiaoYa固定VITS speaker不能clone；可选CosyVoice桥接尚无授权链完整核验/实际本项目模型服务。
- 既有实验worker只准备固定Girl；新worker已允许operator配置asset_path，但其当前PrepareAvatar仍核对固定启动时avatarRef/assetSHA256，没有assigned JobClaim个人多人物prepare/preview接口。
- Avatar preview要求READY NORMALIZED_AUDIO且≤10秒，Voice preview生成VOICE_PREVIEW WAV。暂无将该输出按合法lineage转为NORMALIZED_AUDIO或组合“所选Voice→SoulX”的协议。禁止改purpose或伪装成重新上传的原始本人语音绕过。需Agent 1明确版本化组合边界后实现。
- 目前capability结构没有列举operator-registered CosyVoice modelRef的查询列表；普通用户选择已授权模型的网页需要明确可用列表来源，不能要求输入SSH/模型路径或猜逻辑ID。
- 真人/声音相似度确认与当前档案版本的绑定/失效行为需要Backend产品实现；Profile READY仅代表准备证据，不自动代表人工同意效果。

## 所需交付

Agent 1：解决合法Voice输出→Avatar预览组合及已注册模型列表的协议；不改单独旧接口的purpose含义，不悄悄放宽输入。

Backend/Storage：实现冻结公共/内部接口、tenant+user隔离、硬限额/加密存储、有限租约、ASSET_IN_USE与全派生删除；personal binding原子capture/renew/release和正式Session映射。

Worker：从授权资产准备SoulX Lite图像条件、人物缓存身份/隔离/切换/驱逐、版本绑定10秒preview及取消，禁止全局换图串人物。遵守DiT/依赖权重具体许可，特别是Lite VAE_LTX。

Avatar/Voice：给已实现的PersonalVoiceRenderer注册真实审核通过的本地模型工厂，部署验证IsolatedMediaValidator与人脸检查器，给processor注册SoulX个人Avatar executor，提供本人素材GPU/Voice测量；未配置时保持明确不可用。禁止启动收费GPU或用Mock完成发布验收。

Frontend：依生成类型实现完整网页向导、录音、真实试听/预览、人工确认、保存/切换/删除；缺handler/capability时显示不可用，不接收凭据/SSH/原始素材URL。

## 关闭条件

端到端经网页用本人授权素材完成，隔离/删除/取消及真实模型证据齐全，`PERSONAL-AVATAR-ACCEPTANCE.md`客观/人工指标分别有结果。不能用当前42项合成/模拟单测、官方Girl旧GPU报告或接口定义关闭本问题。
