# 智训引擎 RAC-HPO 参赛源码

本目录对应已导出的 Linux/amd64 Harness 镜像。赛事宿主提供父检查点和公开数据，每轮使用 SDK 1.0.2 调用 PyTRIO 选择候选、续训并收集公开验证回执。搜索策略及公开验证结果见 [技术报告](TECHNICAL_REPORT.md)。

## 构建

准备赛事原版 `contest-harness-sdk-1.0.2.tar.gz` 和 `cpu-a-guide-20261110-v1.zip`。将下列命令中的文件路径改为实际路径，在仓库根目录运行。

```sh
python3 official_submission/prepare_context.py \
  --sdk /path/to/contest-harness-sdk-1.0.2.tar.gz \
  --baseline /path/to/cpu-a-guide-20261110-v1.zip \
  --output workspace/official-build
docker buildx build --platform linux/amd64 --load \
  --tag industrial-rac-hpo:submission-candidate-amd64 workspace/official-build
docker run --rm --platform linux/amd64 --network none --read-only \
  --user 65534:65534 industrial-rac-hpo:submission-candidate-amd64 describe
docker save --platform linux/amd64 -o workspace/official-build/harness.tar \
  industrial-rac-hpo:submission-candidate-amd64
```

构建脚本校验 SDK 归档和基线运行源码的摘要，并将本项目运行代码、锁定依赖和官方模板复制到构建上下文。提交镜像的实测源文件摘要保存在 [source-files.json](source-files.json)。其中 `git_head` 记录构建当时工作区的提交位置。校验实际构建内容时，比较两个清单的 `files` 字段。

已上传归档的 SHA-256 为 `80d5cbe88f3d191d47ac8d84ecaa34b38ea72f2840476b0f43cf0a8fb2cfd193`。重新构建后的镜像归档会包含新的构建元数据，应以文件清单核对源码对应关系。

## 本地验收

最终 AMD64 镜像在禁网、只读根文件系统和普通用户下通过 8 项 SDK 测试。使用本地赛事宿主替身，A、B、C 各完成 10 轮，逐轮核对了父检查点摘要及历史引用。真实 PyTRIO 联调使用基础模型 `Qwen/Qwen3.5-4B`，三项任务都取得有效候选回复。

源码沿用赛事 SDK 和基线运行模块。数据在训练时由平台挂载，来源及划分见 [技术报告](TECHNICAL_REPORT.md)。
