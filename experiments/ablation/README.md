# 离线消融实验

`run.py` 驱动 SDK 1.0.2 的真实回调，以本地替身宿主测量公开验证数据；模型回复固定为 `RAC`，不访问收费模型或赛事平台。默认串行运行 A/B/C、G0/G1/G2/G3、搜索种子 42、每组 10 轮，单进程限制 1 线程。G0 固定使用初始 checkpoint 的学习率和 batch size、2 epoch、uniform 采样；G1 关闭跨父迁移和成本惩罚；G2 开启迁移但不使用成本惩罚；G3 与 G2 一致，只开启两处成本惩罚：迁移 TPE 的权重 0.05 和 RAC acquisition 的成本指数 0.5。G1/G2 的两项均为 0。为保持原有代理安全门槛和对照一致，G1/G2/G3 均保留相同成本代理前向质量门槛，因此不能将 G1/G2 描述为完全不依赖成本信息，也不能单凭 G2/G3 差值分别归因两处惩罚。所有组使用相同 SDK 选模门槛。训练随机状态继承初始 checkpoint；搜索种子只改变搜索随机性。

前提：工程内 `.venv-contest`、`训练集/cpu-{a,b,c}-*.zip` 和 `workspace/verification/contest-p4.HzWSoucE/context-v2/sdk` 已存在。脚本逐文件验证公开包，实验输出目录必须是 `experiments/ablation/` 下尚不存在的新路径。每次运行都记录输入和源码 SHA，保留所有候选、状态与逐轮结果；训练仅使用公开训练分区，验证仅用于搜索和选模。

```sh
PYTHONDONTWRITEBYTECODE=1 .venv-contest/bin/python experiments/ablation/run.py --seeds 42 --rounds 10 --output experiments/ablation/NEW-SMOKE
.venv-contest/bin/python experiments/ablation/analyze.py experiments/ablation/NEW-SMOKE
```

后续若明确执行三种子，用新目录并加 `--seeds 42 71 103 --allow-multiseed`。`--cpu-budget SECONDS` 在每轮前检查当前进程累计 CPU，已开始的轮次可能超过预算；脚本同时给出固定轮次与共同 CPU 时间的事后完整轮次前缀。它不代表硬性限时对照。总体 CPU 统计从数据预载之后开始，包含搜索、训练、公开验证和宿主回调；进程 CPU 另含初始化。峰值内存是每次独立进程的 `ru_maxrss`，单位字节；训练耗时包括 wall 和 process CPU。不能将不同 CPU 预算的最终指标直接作为优势证据。

C 的平台 NASA Score 具体公式尚未核实，数值为 `null`，不得将其他版本的指标冒充官方分数。`analysis.json` 在只有一个种子时将标准差标为 `null`，不得用冒烟结果代替多种子比较。
