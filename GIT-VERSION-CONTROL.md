# AstraLive 本地版本控制

2026-10-09：现有 Git 仓库没有任何提交。已建立根目录 `.gitignore`。按下述规则纳入源码，并保存本地原始源码基线；v0.3配置模块与清理记录随后单独提交。没有添加远程或推送。

| 分类 | Git 管理 | 内容 |
| --- | --- | --- |
| 正式源码 | 是 | Go Backend、React/TypeScript Frontend、Python Runtime |
| 契约与架构 | 是 | contracts、architecture、CCR、迁移与接口规范 |
| 测试与工具 | 是 | 单元/集成/浏览器测试、部署脚本、Dockerfile、Compose、服务模板 |
| 依赖定义 | 是 | go.mod/go.sum、package.json/bun.lock、requirements 文件 |
| 配置模板 | 是 | `.env.example`，仅占位符或明确本地测试值 |
| 实验代码 | 是 | lab/experiments 自己编写的脚本、适配器、隔离 Runtime 源码 |
| 可读验收结论 | 是 | Markdown 报告、素材 manifest/hash、复现实验配置 |
| 原始素材和生成媒体 | 否 | 视频、音频、研究肖像素材、H.264/H.265 输出 |
| 大模型及依赖安装包 | 否 | 模型、权重、wheelhouse、下载包、第三方仓库副本 |
| 机器环境和缓存 | 否 | node_modules、.venv、dist、Python 缓存、编辑器/OS 文件 |
| 私密配置 | 否 | `.env` / `.env.*`（模板除外）、`.private`、密钥、SSH 连接记录 |
| 原始运行数据 | 否 | evidence、日志、实验输出、浏览器 profile、backups、network 采样 |
| 可再生成的前端实验 bundle | 否 | `cpu_product_preview.js`，由保留的 TSX 和构建脚本生成 |

正式 API 生成代码目前保留在 Git，便于查看接口差异；node_modules、构建输出不保留。源码中的现有本地测试 token 不等于正式凭据，部署时必须使用独立的注入值。

被忽略的文件仍原样留在本机。Git 不会备份这些素材、模型、数据库、运行证据或私密文件；需要另外保存在受控磁盘/对象存储，并使用现有 manifest/hash 校验。新增真正需要版本控制的小型测试图片或音频时，可针对确切路径调整规则；不要强制添加整个素材目录。

## 查看与保存版本

```sh
git status --short
git diff --cached --stat
git diff --cached
git log --oneline
git commit -m "feat: describe the next verified change"
```

已保存本地初始提交，后续功能单独提交。暂存只代表准备加入下一次提交，执行 `git commit` 后才形成新的可恢复历史版本。

## 后续维护

每完成一个可验证功能，提交一次源码与对应测试/规范。大型素材仅记录来源、用途、路径与 hash。真实密钥不要放入模板、源码、URL、报告或提交消息。已提交的文件不受后续 `.gitignore` 自动保护，因此新增规则后仍需检查暂存区。
