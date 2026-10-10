# AstraLive v0.3 — 个人 Avatar 素材安全

日期：2026-10-09。**本文是待落地的安全设计及验收条件，不能作为私有存储/上传系统已上线的证明。** 本轮实现媒体校验、受限decoder入口、内部processor客户端及个人Voice解析/临时文件清理；没有私有资产HTTP或存储实现。沿用Agent 1身份、配置与资产契约，不新建身份体系。

## 1. 上传授权与用途

第一版仅接受用户本人照片及声音。上传前分别确认：“这是我本人的形象/声音，我有权将其用于本系统数字人预览及我授权的直播；我已了解素材处理用途及删除方式。”未勾选不能开始服务端上传、音色准备或推理。录音也需同样确认；麦克风授权不等于数字人用途授权。

用途说明必须具体：格式检查/裁剪、人脸与声音质量检查、预训练推理的条件缓存、试听、预览和用户主动启动的直播；无默认基础模型训练/微调，无营销复用、公开素材集或额外用途。不得把用户勾选解释为允许任意第三方上传。记录授权文本版本、本人范围、来源、时间及撤销，存入Agent 1定义的授权结构；不是可信浏览器单独布尔值。

同意声明不是身份真实性证明。真实产品仍需要风险处理、举报和撤销流程，不能声称通过FACE检查便证明“照片就是账户本人”。未经同意克隆他人不可用。第三方授权仅设计扩展：由权利人独立确认具体素材、用途、受益人、期限/撤销并留审计证据，完成前第一版入口保持不可用；不接受上传者一句“我有授权”绕过。

托管服务需先核验具体provider/service的数据处理条款、模型和声音使用权，告知数据流向和留存并取得该用途授权。本轮未选托管服务、未上传任何用户素材到第三方。自托管worker也需处于已授权部署范围；资产由私有服务通道交付，不把任意用户URL转给模型下载。

## 2. 权限和路径边界

所有列表、写入、读取、试听、预览、默认选择、禁用、删除及worker任务都以Backend已认证tenantId **和** userId过滤。同租户不同用户也必须隔离。跨范围ID一律404；不接收浏览器tenant/user headers、JSON身份或“知道assetId便能读取”的逻辑。

遵循当前v0.3 HttpOnly/Secure/SameSite=Strict cookie、HTTPS同源、mutation Origin检查和no-store。cookie当前Path=`/api/v0.3/config`，新增路由必须由Agent 1明确纳入该认证边界。内部GPU/资产接口使用独立服务身份，不复用浏览器cookie或把Runtime Tool token当用户登录。

旧v1.1 Avatar/Voice元数据API未迁移成私人资产权限，不允许作为个人照片/声音落点。原有binding解析可返回服务端provider凭据，素材组件不得接收这个响应；由Backend/Runtime可信编排分别解析档案、凭据及资产租约。

资产使用服务端opaque ID，对象键与路径由AssetStorage生成；不得由姓名、原始文件名或浏览器路径拼接。跨租户禁止全局哈希去重/哈希存在性查询，避免推断谁上传了同一声音。所有关联表/Job/cache必须维护复合ownership，不能只在列表过滤而在download/delete忽略。

## 3. 存储和原始素材

使用Agent 1 AssetStorage，必须交付私有对象存储实现后才能称安全存储已完成。桶关闭匿名访问、目录列表和公开ACL，不置于静态站点/CDN源目录；照片与参考音频没有公共URL。API只返回opaque素材ID、状态、必要质量提示，不返回bucket key、文件路径、GPU地址、SSH信息或签名原始素材URL。

用户上传期间的本地预览可用短生命周期blob URL，卸载/替换时撤销。v0.3.1只允许本人认证读取READY规范化或生成预览；原始照片/参考声音的preview返回409 ASSET_NOT_READY，不能提供原始素材inline读取。服务端响应no-store/nosniff，单Range受限，不带公开重定向；正式上线前验证浏览器、代理和日志无缓存/泄露。

传输HTTPS或受控私有服务TLS。processor客户端要求HTTPS及显式trust_env=False，禁止继承环境代理，所有请求禁止重定向；运维注入的客户端仍需正确证书校验和受控网络部署。静态加密由对象存储KMS或AssetStorage受控AEAD实施，密钥只在服务/secret manager，轮换保留必要旧key；配置凭据加密不能替代素材加密。最小权限服务账号限定资产命名空间，worker仅获得指定任务、素材版本、有效期的读取租约，无桶管理员权限。

worker工作目录权限0700，素材文件0600，不可变任务文件，拒绝symlink/路径穿越，排除Git、日志、公共备份及监控采样。临时解密副本在任务结束/取消后清理；worker和进程内模型引用必须在删除确认前回收。现有实验素材/公开示例不应与真实用户资产混用。

## 4. 输入和资源限制

服务端以解码内容判断格式，不能信任扩展名/MIME。拒绝SVG、动画、多流视频、超尺寸照片、无参考文本、坏音频、超长/静音/明显削波音频。规范化照片输出新建RGB PNG，清除EXIF/GPS/ICC/文本；参考声音生成仅含PCM的新WAV，不携带用户元数据。

当前helper具备输入字节、像素、音频样本/流数量上限和demux URL协议禁用；新增Linux bubblewrap启动器配置独立网络/PID/IPC、最小只读挂载、256MiB临时存储、512MiB地址空间、60秒CPU/墙钟和终止进程组。**本机macOS没有实际运行该Linux沙箱，参数/拒绝路径单测不能作为恶意文件隔离已通过的证明。** 不支持隔离时明确失败。上线还需ingress/body限制、租户配额、实际Linux sandbox probe与对抗素材测试，不能仅在decode完成后查时长。

拒绝任意模型路径、权重URL、pickle/checkpoint上传和任意provider参数。缓存只由服务端从校验素材与固定模型产生，用户不能上传可执行的spk2info或模型文件。不允许用户素材触发AutoModel自动下载/训练。

## 5. 删除、撤销和缓存回收

页面分别提供重传、禁用和删除，按已冻结v0.3.1执行：当前档案、defaults、Job或未到期binding引用素材时删除返回409 ASSET_IN_USE，界面指导用户先停播/release、取消任务、禁用或删除引用档案。不能向用户宣称档案tombstone会立即销毁仍获租约授权的素材。

没有活引用后，AssetStorage在owner锁下处理source与派生引用计数，进入DELETING，驱逐人物/声音conditioning及运动缓存，等worker租约退出或回收隔离worker，再删除原始照片、参考音频、标准化副本、embedding、试听、预览、缩略图和临时文件。删除缓存不能只删数据库行。

长任务回报携带ownership、素材/profile版本和撤销版本；旧Job完成不得复活已删资产。删除Job可重试且幂等，错误用静态码；全部成功和worker确认之前只显示删除中/失败，不显示“已彻底删除”。卡住的native CUDA调用可能超过0.5秒关闭上限，Voice桥接会隔离provider，但仍有活线程；资源回收不是仅await aclose就证明完成。

v0.3.1已定义不可变personal binding及24h租约/renew，profile变更/禁用/tombstone只阻止新capture，活租约继续pin原版本；ASSET_IN_USE阻止在该期间宣告素材删除完成。过期/released binding立即不能读取，即使GC尚未清理。元数据tombstone保留30天，DELETED时活存储字节必须已删除。授权撤销如需强制中止所有活租约，应由后续明确契约定义，不能单方面改变当前immutable保证。

对象版本、备份及灾备同样纳入删除：记录online删除完成与backup清除期限，停止恢复被撤销对象，必要时使用对应资产密钥销毁。保留期由部署政策明示，不能未经实现就承诺立即消除所有备份。当前尚无该政策或真实删除验证。

## 6. 日志和运维

日志只记录opaque任务/档案ID、版本、阶段、静态错误码和耗时，不记录照片、PCM、参考文本、生成全文、文件路径、URL、cookie、Authorization或provider响应。按v0.3.1 Asset定义，SHA256仅在本人授权元数据和内部完整性proof中返回，不提供匿名可检索素材指纹接口。

`CosyVoiceTTSProvider`屏蔽native异常文本，但上游CosyVoice内部默认可能记录合成文本，部署必须关闭其敏感日志；桥接无法替代worker日志策略。生产禁用CAPTURE_TTS_TEXT_EVIDENCE等实验全文采集开关。GPU SSH/API Key由运维/可信编排管理，普通数字人管理组件只看到可用状态和logical worker/profile ID。

## 7. 必须执行的安全验收

| 测试 | 必须看到的结果 | 本轮状态 |
| --- | --- | --- |
| 同tenant不同user / 不同tenant访问所有asset/Job/cache操作 | 404，无对象泄露 | 未实现资产API，未执行 |
| 无cookie、伪造身份、跨站Origin、过期/撤销session | 拒绝，无worker任务 | 现有配置机制存在；新资产路径待测 |
| 原始素材URL/桶列表/静态路径/签名链接 | 不能匿名读取，API无原始URL | 私有AssetStorage待交付 |
| EXIF/GPS/文本元数据 | 标准化照片无metadata | 合成fixture检查通过 |
| 恶意格式/超限/音频视频混流/URL demux | 拒绝，无外部读取 | helper部分覆盖，进程/HTTP gate待做 |
| 删除与正在prepare/preview/stream的竞争 | 旧结果不复活，无残留worker/cache | 待契约与真实服务 |
| 密钥轮换、对象版本及备份撤销 | 加密可用，撤销对象不可恢复使用 | 待存储实现与部署验证 |
| native挂起与取消 | 有界关闭、provider隔离，真实worker回收另确认 | 模拟桥接控制测试通过 |
| Linux decode进程隔离 | 无host network/私有HOME挂载、硬资源限额、超时/取消清理 | 参数及macOS拒绝路径测试通过；真实Linux待测 |
| 日志/trace/browser bundle检查 | 无素材/文本/凭据/SSH信息 | 本轮新代码不写素材；上游部署待测 |

发布前逐项提供请求/响应与存储/worker最终状态证据，不把安全设计文档或单测当作SaaS隔离验收。
