# SoulX 已验证环境复用与部署

同一实例正常关机、开机，复用 `/root/autodl-tmp/astralive-avatar-lab` 的环境和模型，不需要每次安装CUDA/PyTorch或下载权重。本次新实例数据盘为空，恢复缺失环境和权重仅属于首次准备。

已验证组合：Python3.12.3、PyTorch2.8.0+cu128、CUDA12.8、FlashAttention2.8.3。权重版本与7文件SHA256见 `soulx-weight-manifest.json`，额外依赖锁见最终证据中的 `environment-lock.txt`。无需强制替换为Torch2.7.1。

## 当前已保存的内容

- GPU数据盘保留完整SoulX仓库、模型、venv、Worker和原始人物素材。
- Mac与school-linux保留实现、环境锁、模型SHA清单、报告及录像；不含APIKey/SSH私钥，不需要再备份8GB权重到Mac。
- 新用户Key只在Mac `streaming/.private/deepseek-api-key`，0600权限，实验启动器优先读取此文件，并在启动前验证真实streaming LLM。
- 正式默认Avatar Provider未改变。

## 现有缓存的一条命令启动

将本次备份的 `scripts/start-cached-soulx-worker.sh` 放入GPU数据盘项目的scripts目录，再执行：

```bash
SOULX_FINAL_RUN_DIR=soulx-service-run bash /root/autodl-tmp/astralive-avatar-lab/scripts/start-cached-soulx-worker.sh
```

脚本只检查已有环境/模型、拒绝重复PID、使用setsid+nohup启动已验证Worker；没有pip install或模型下载。Worker启动时校验SHA、加载/预热一次，随后持续复用模型。它监听原有127.0.0.1:17087，仍需已有安全SSH隧道和school-linux服务配置；此脚本不是完整商业平台部署编排。此次服务器已关机，新增启动包装仅通过bash语法检查，未重新启动GPU验收。

## 新机器首次部署

新空服务器必须先获得模型和环境，不能在没有权重的机器上直接进行推理。减少人工配置的部署方式是预装镜像，或镜像含运行环境、模型置于持久卷。固定版本/Manifest，挂载已有缓存，启动时验证缺失项；不要让服务每次启动都自动重装或下载。

本次没有创建收费的新实例，没有自动构建/上传大型镜像，也没有声称已生成可移植的一键Docker商业部署包。当前代码固定GPU数据盘根目录，迁移到其他目录需明确配置或保持相同路径。

AutoDL正常关机会保留数据一段时间，并非永久保存；长期不用应保存镜像/外部模型副本。参见 [AutoDL数据保留说明](https://www.autodl.com/docs/instance_pro_data/) 和 [关机方法](https://www.autodl.com/docs/save_money/)。本次关机命令已发出、SSH关闭，控制台电源及账单状态未直接查询，需确认显示已关机。
