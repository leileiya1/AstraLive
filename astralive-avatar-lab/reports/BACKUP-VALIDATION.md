# 最终备份验证

日期：2026-10-08。状态：三处完整性验证 PASS。

| 位置 | 实验目录 | SHA256校验文件数 | 不匹配/缺失 |
|---|---|---:|---:|
| 本机 | `/Users/sapiece/innovationProject/AstraLive/astralive-avatar-lab` | 169 | 0 |
| GPU云端 | `/root/autodl-tmp/astralive-avatar-lab` | 169 | 0 |
| school-linux | `~/AstraLive/experiments/real-avatar/results/rtx4090d-2026-10-08/` | 169 | 0 |

校验清单：[RESULT-SHA256SUMS.txt](RESULT-SHA256SUMS.txt)。逐站实际校验结果：backup-verification-local.json、backup-verification-cloud.json、backup-verification-school.json，均为PASS。

清单包含25个MP4：20个模型结果/预览文件、2个A/B副本、2个官方输入视频、1个CPU FFmpeg环境测试片。不能将25个文件数说成25次独立GPU推理；拼接预览与A/B副本也不计为额外推理。具体模型视频见[结果索引](RESULT-INDEX.md)。

保存范围：outputs、benchmarks、reports、scripts、inputs、logs。包含实际MP4、指标JSON/CSV、日志、报告、依赖锁定快照、代码commit记录、权重来源/版本/hash及必要输入。未同步SSH私钥、连接凭据、完整环境变量、模型缓存、Conda环境本体、安装轮包或整个生产仓库。云端连接专用gpu-ssh.sh未复制。结果校验文件及本报告排除在自身hash清单之外，避免自引用。

实际验证命令（各站替换ROOT与SITE）：

```bash
python3 ROOT/scripts/result-integrity.py ROOT --verify --site SITE
```

通过已有可信Host Key与SSH Key、BatchMode及StrictHostKeyChecking安全rsync；未开放公网传输端口。school-linux写入仅限上述独立实验结果目录，未修改正式Runtime/WebRTC/RTMP。

最后云端只读检查：RTX4090D，驱动580.105.08；GPU显存0MiB、利用率0%，无compute进程。所有推理已停止，但租赁实例未释放、仍在计费。用户确认本机及school-linux结果可读后可手动释放实例；不要依赖云端数据盘在实例删除后仍保留。此前聊天中暴露的密码应轮换。
