# SoulX GPU Worker 部署

更新2026-10-10。已有安装包和独立CPU部署演练；在用户新租RTX3080实例上完成固定环境/权重首次恢复及真实Worker短测，见验收文档。同一实例后续通过安装入口直接启动，复用数据盘环境与模型。

## 当前交付范围

**独立GPU组件已可安装复用，完整商业一体／分离部署产品尚未交付。** RTX3080真实链路连续3714.792s与六个同步检查点通过；用户要求停止追加测试，资源已正常停止并保留。严格原生WebM录像有1个相等视频PTS，完整恢复尚未验收，见验收文档。

现有服务器固定环境/权重已预置，日常 `start/restart` 与升级代码不触发下载。换新主机时仍需传输离线包；约7.73GiB包依赖匹配基础镜像，不能承诺任意裸机无需准备。新空主机恢复未实测，完整应用组合安装器、服务端正式绑定和一体／分离模式自动编排尚未完成。当前不是“只提供服务器即可装好整套产品”的最终安装交付。

下一步交付应固定基础镜像与版本清单，用同一安装入口选择应用+GPU一体或仅GPU分离模块，复用持久模型缓存；首次传输与日常升级分开，缺失/损坏才恢复相应资产。该目标未实现的部分不能以模型能跑替代。

## 一次安装，日常直接启动

已提供可执行安装包构建器 `gpu_worker/release.py`、`deploy/install.sh`、安装器和固定生命周期入口。代码包采用文件 SHA256 清单及由清单派生的 releaseId；它验证传输完整性，不替代操作员可信分发渠道/签名。包只收录 Worker 代码/模板/固定示例头像，不收录本地 venv、测试日志、业务凭据或其他模块。Python tarfile 生成跨 Linux/macOS 的归档，不携带 AppleDouble/xattr。

```bash
# 在代码工作区构建；不是每次启动时执行。
python -m gpu_worker.release --out /tmp/soulx-worker-release --archive /tmp/soulx-worker-release.tar.gz
# 在目标服务器解压这个可信包，首次安装。
./install.sh
# 使用安装命令打印的完整路径；无需再 export 环境变量或填 token。
/root/autodl-tmp/astralive-services/soulx-lite-01/bin/astralive-worker doctor
/root/autodl-tmp/astralive-services/soulx-lite-01/bin/astralive-worker start
/root/autodl-tmp/astralive-services/soulx-lite-01/bin/astralive-worker status
/root/autodl-tmp/astralive-services/soulx-lite-01/bin/astralive-worker restart
/root/autodl-tmp/astralive-services/soulx-lite-01/bin/astralive-worker stop
```

首次安装自动创建私有配置、两个独立随机 token、state/cache/log 目录、版本目录、稳定 launcher；不会启动模型或切换 Provider。bootstrap 自动寻找 `/root/miniconda3/bin/python`，再找 PATH 的 python3（要求≥3.12），不会因 AutoDL 的 PATH 缺失而误报完全没有 Python。`--root /绝对路径` 支持多 Worker；首次可设置 `--worker-ref`、端口、`--lab-root`、`--python`，均是操作员侧参数。已安装配置原样保留，路径冲突明确拒绝，不静默改配置或轮换认证。

安装布局：`config/worker.json`、`secrets/`、`state/`、`releases/{releaseId}/`、`current`、`previous`、`bin/astralive-worker`。重复安装幂等；升级先stop，再对新包运行install；原配置/token/cache保留，原代码通过previous保留。服务活跃时拒绝升级，安装和生命周期命令共享排他锁，current原子切换。安装器不会删除旧版本或原模型数据；回滚先stop，再安装保留的旧可信包。无需平台用户填写 shell 命令。

`doctor` 只读校验 SHA256、固定环境/源码、GPU架构和磁盘，不加载模型，探测子进程30s截止。`start` 先执行doctor，缺少组件/不兼容返回78、不启动supervisor；之后等待真实warmup/listener READY（有界截止），超时停止本次启动。此入口比低层 `cli start` 多一个 READY 等待。`run` 是容器前台入口，SIGTERM由原supervisor处理。

## 新空服务器的离线环境和权重

### 首次联网准备与日常复用

2026-10-10 用户授权在新RTX3080实例首次部署固定模型/环境。基础Python3.12.3、Torch2.8.0+cu128和CUDA12.8原样复用，额外依赖安装到独立venv。`deploy/prepare-soulx-once.sh` 是操作员显式执行的首次准备入口，配套 `constraints-pinned.txt` 来自上一轮固定环境锁、`requirements-soulx.txt` 记录实际所需依赖；它校验原FlashAttention wheel SHA，采用有界安装超时，支持已校验wheelhouse离线安装。不会由start/restart调用，不改基础Torch、不使用上游会替换Torch的未审阅安装命令。

准备前必须将固定FlashAttention wheel和七文件Manifest/模型源码/批准素材置于约定持久路径；下载器只恢复既有Manifest版本，完整SHA通过才允许启动。环境脚本自身不下载模型。不把首次联网准备描述成完整自包含镜像：基础镜像、源码、权重和可信依赖来源仍是首次安装的输入。

模型文件和venv属于持久数据，Worker代码属于可升级release；正常停止/重启、重复安装或升级代码保留数据目录，无pip或下载。新服务器、模型文件缺失/损坏或操作员明确更换版本才重新准备相应文件。首次新GPU的PyTorch编译/预热可能耗时较长，不能误判为反复下载权重；启动仍受READY截止约束。

### 一体或分离部署

同一Linux/NVIDIA主机可放应用模块与GPU模块，应用端登记loopback Worker。分离部署时应用主机保留前端/Backend/Runtime/业务存储，GPU主机仅安装本模块，登记安全隧道端点。两者复用同一协议和配置，GPU端无独立业务账户库，也不保存LLM/TTS业务Key。已有 `infra/compose.yaml` 是开发集成栈，仍含Mock配置，不能作为已验收的商用一体安装包；完整组合安装及Windows/macOS支持需要后续实现和验证。

**已构建并安装代码包，3080上已导出包含七个权重、venv及源码的离线增量包；它仍不是完整基础镜像。** 新空服务器需要匹配基础镜像，之后恢复离线包；启动时不下载。导出方式：

```bash
python -m gpu_worker.release --out /persistent/soulx-offline-release \
  --archive /persistent/soulx-offline-release.tar.gz \
  --with-lab-config /private/worker.json
# 目标采用相同基础镜像，且lab目录尚不存在。
./install.sh --restore-lab
```

离线导出先完整preflight/SHA检查，收录固定源码（含必要Git对象）、venv、worker-deps、七个权重文件和批准头像，排除实验日志/结果/业务状态/凭据。包恢复只接受常规文件、拒绝路径穿越/链接，先在同盘暂存再原子迁入；拒绝覆盖已有lab。允许为已停机且lab仍缺失的代码安装补充 `--restore-lab`，保留原配置/token。

旧venv使用 `--system-site-packages`，因此离线增量包**仍依赖基础镜像**中的 `/root/miniconda3` Python3.12.3/Torch2.8.0+cu128/CUDA12.8，不能当作任意Linux的自包含venv。保持固定lab绝对路径 `/root/autodl-tmp/astralive-avatar-lab`，不尝试直接重定位旧venv。基础镜像和离线增量包组合用于一次预置；导出已执行，新空主机完整恢复仍未验证，不能标为自包含镜像交付PASS。服务不会自动重新执行pip/setup脚本。

本次GPU主机的包目录：`/root/autodl-tmp/soulx-offline-rtx3080-fast-20261010/`，payload约7.73GiB，外层releaseId `c104ae5f077feac37cbe8f5676db3b06163ea4bbca955f8b69529ff2d5f85e7b`。迁移时复制整个目录（包括MANIFEST），在符合基础环境且lab目录为空的目标执行 `./install.sh --restore-lab`。它保留在GPU数据盘，未将大型权重复制到Mac。

整包SHA、gzip完整性、11183个常规文件的安全路径及七权重/Manifest/头像九项SHA独立检查PASS，receipt见验收证据。该检查不替代新空主机安装、READY和短时推理演练；base镜像仍是必需输入。

## GPU选型与月租

2080Ti是Turing/compute7.5，不兼容固定FlashAttention2.8.3；[该版本官方要求](https://github.com/Dao-AILab/flash-attention/blob/v2.8.3/README.md)只支持Ampere/Ada/Hopper。新gate仅判断架构（compute major8/9），不表示所有这些GPU都通过性能/容量验收。

3060 **12GB** 是可测的低价候选，其Ampere/compute8.6兼容；[NVIDIA规格](https://www.nvidia.com/en-us/geforce/graphics-cards/30-series/rtx-3060-3060ti/)也有8GB变体，不能混同。旧4090D显存记录支持“12GB可能装得下”的判断，但没有3060新测量，不能由显存使用推导实时FPS。优先短时测试连续语音每960ms块的特征/推理/编码耗时及队列趋势，再决定包月。禁止修改模型/attention实现来悄悄绕过原验收组合。

4090D24GB是现有实验链路已验证硬件；4090/3090/3060等均需新服务短时实测。初始按单Worker单房间规划：8vCPU、32GB RAM、100GB持久盘是留余量的部署预算建议（64GB/150GB可增加余量），**不是测得的最低配置**。显存容量、单块计算尾延迟、编码耗时和实际新帧率分别记录，不把idle/held/浏览器25FPS算成实时新推理能力。包月价格以平台当日实例为准，本轮没有租赁/变更套餐或自动购机。

## 已有环境复用

将 `gpu_worker/` 和必要 AstraLive Runtime 代码部署至独立代码目录，例如 `/root/autodl-tmp/AstraLive`。模型/venv 保持在已有 `/root/autodl-tmp/astralive-avatar-lab`。GPU 启动不运行 pip、安装 CUDA、下载权重或训练。保留现有 `streaming/worker-deps` PyAV 目录。原始素材与权重不改动。

复制 `gpu_worker/deploy/worker.example.json` 至操作员私有目录，模板已填入本次已验证素材与 `reports/soulx-weight-manifest.json` 的 SHA256 pin；部署时与现有数据盘再核对；配置采用绝对路径。Manifest 本身必须匹配配置 pin，七个文件逐一匹配各自 SHA256；缺失/变更直接失败。源码 HEAD、工作树和既有 Python/Torch/CUDA/FlashAttention 也有启动 gate。

为推理及管理分别建立随机 ≥32字符 token 文件，0600，父目录0700；不可复用 LLM/TTS/商家令牌。通过安全部署工具写入，勿粘贴到日志、前端或 Git。生产 state/cache/log 放在独立持久目录，不能共用实验 evidence/token。实验原 Worker 与产品 Worker 不可同时占用相同端口。

```bash
cd /root/autodl-tmp/AstraLive
export ASTRALIVE_GPU_CONFIG=/root/autodl-tmp/astralive-services/worker.json
export ASTRALIVE_GPU_PYTHON=/root/autodl-tmp/astralive-avatar-lab/environments/astralive-soulx/bin/python
"$ASTRALIVE_GPU_PYTHON" -m gpu_worker.cli check --config "$ASTRALIVE_GPU_CONFIG"
"$ASTRALIVE_GPU_PYTHON" -m gpu_worker.cli start --config "$ASTRALIVE_GPU_CONFIG"
"$ASTRALIVE_GPU_PYTHON" -m gpu_worker.cli probe --config "$ASTRALIVE_GPU_CONFIG"
"$ASTRALIVE_GPU_PYTHON" -m gpu_worker.cli status --config "$ASTRALIVE_GPU_CONFIG"
"$ASTRALIVE_GPU_PYTHON" -m gpu_worker.cli stop --config "$ASTRALIVE_GPU_CONFIG"
"$ASTRALIVE_GPU_PYTHON" -m gpu_worker.cli restart --config "$ASTRALIVE_GPU_CONFIG"
```

`start` 只表示 Supervisor 已启动；`probe` 成功才是模型及三块预热/编码器 READY。启动初期 probe 失败是预期，默认 deadline300s；不应以 PID 存活当 READY。停止通过0700目录内的0600 Unix socket 发固定 STOP，不依据过期 PID 文件杀进程。

旧脚本新增显式产品入口：设置 `ASTRALIVE_GPU_CONFIG`、`ASTRALIVE_GPU_PYTHON`、`ASTRALIVE_GPU_CODE_ROOT` 后，运行 `start-cached-soulx-worker.sh start|stop|restart|status|probe|check`。未设置 CONFIG 时仍为历史实验启动行为；新部署应显式设置 CONFIG。

## 容器 supervisor

选用项目自带 Python/POSIX Supervisor：既有容器已能运行 Python、进程、signals、socket/文件锁，不依赖 systemd 或额外 supervisord 安装。`gpu_worker/deploy/run-worker.sh` 可以作为已有容器前台启动命令，使用 exec 和 SIGTERM。也支持上述 detached CLI；不能同时用两层无限重启策略。Supervisor 文件锁阻止同一 state_dir 重复启动，探针还验证服务 PID，避免把端口上的旧服务当新进程 READY。

不创建新收费实例、不自动开机、不修改 AutoDL 账户或其他容器。容器/主机重启后的启动入口由操作员设置在现有平台；无需也不假定 systemd。磁盘 cache 元数据保留，新的 Worker epoch 不继承旧工作。

## 配置与环境变量

配置 schema 由 `Config` 明确字段，未知字段失败。固定 `mode=gpu`、model_revision 和warmup3；simulation 只能用于隔离 CPU 测试。可覆盖路径的环境变量仅：

- `ASTRALIVE_GPU_LAB_ROOT`
- `ASTRALIVE_GPU_STATE_DIR`
- `ASTRALIVE_GPU_PYTHON`
- `ASTRALIVE_GPU_TOKEN_FILE`
- `ASTRALIVE_GPU_MANAGEMENT_TOKEN_FILE`

CLI shell入口另读取 CONFIG/CODE_ROOT，不提供任何用户可编辑命令字段。策略包括端口、启动/停止/推理截止、最多3次重启、退避上下限、磁盘最低1GiB、日志10MiB×当前+5备份。多 Worker 各自使用独立 ref、state_dir、端口；同一24GB卡多模型并行容量尚未验证，不自动启用。

## 隧道和登记

GPU 推理17087/管理17088都只监听127.0.0.1。Runtime/Backend通过操作员预先建立的 SSH本地转发访问，要求 BatchMode、StrictHostKeyChecking=yes、已批准 known_hosts、ExitOnForwardFailure、ServerAlive 检查及禁止 GatewayPorts。密钥只在操作员秘密目录，不让平台用户输入 shell/SSH命令。现有隧道的生命周期由操作员维护；Worker断线时 Runtime降级，Worker supervisor不尝试控制SSH或云系统。

Runtime服务器配置参考 `deploy/registry.example.json`：一个或多个 workerRef → 本地转发port、tokenFile、avatarRef/assetSHA256、`allowedScopes`。Backend登记参考 `deploy/backend-registry.example.json`：workerRef → 本地管理转发port、管理tokenFile、同样的租户/用户ACL。两个登记表角色不同；均只存于服务端，无IP/SSH key送往浏览器。

Backend设置 `GPU_WORKER_REGISTRY_FILE`，沿用 Agent 1 的 CONFIG_PUBLIC_ORIGIN/现有cookie身份。新增授权状态路径：`GET /api/v0.3/config/profiles/{profileId}/worker-status`。只有caller-owned GPU_WORKER/soulx Profile且物理worker ACL同时匹配tenant/user才可读。探针2s、最大64KiB、不使用HTTP代理、不跟随重定向、字段投影与错误脱敏。

业务绑定由Agent 1可信resolve适配器提供给 `bound_factories(...)`。不要直接把浏览器传来的profileId/tenantId当已授权Binding。原Session路由接入gate及纯RTMP消费边界见设计文档。

## CPU回归复现

本轮在独立 `gpu_worker/.venv-tests` 安装了CPU测试依赖；未更改GPU环境。测试Python3.12.13/Torch2.14.1/av17.1.0/numpy2.5.3。实际GPU仍必须复用固定3.12.3/Torch2.8.0+cu128等组合。

```bash
gpu_worker/.venv-tests/bin/python -m unittest discover -s gpu_worker/tests -p 'test_*.py' -v
gpu_worker/.venv-tests/bin/python gpu_worker/tests/run_legacy_regression.py
PYTHONPATH=runtime gpu_worker/.venv-tests/bin/python -m unittest discover -s runtime/tests -p 'test_*.py'
(cd backend && go test ./...)
node astralive-avatar-lab/streaming/test_browser_audio_health.js
node astralive-avatar-lab/streaming/test_final_player_gate.js
```

旧录像/证据测试需要保留的 ignored `streaming/integration/` 数据；Git-only checkout若缺证据应明确缺失，不删断言或伪造录像。CUDA synchronize只在CPU模拟/旧测试wrapper中mock，不证明GPU性能。新服务不保存音频/视频录制到日志目录。
