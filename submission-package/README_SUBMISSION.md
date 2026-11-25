# 项目源代码包说明（RAC-HPO v8-B）

项目：砺衡 — 融合工况感知与成本代理的自适应超参数寻优算法
团队：叁序（2025040064）
打包日期：2026-11-25

## 一、包内结构

```
.
├── src/rac_hpo/                  核心算法库
│   ├── contest/                  竞赛运行时（策略、续训、采样、门禁）
│   ├── optimization/rac_hpo/     搜索器（TPE 暖启动、代理、采集函数）
│   ├── domain/                   指标与鲁棒目标
│   ├── training/                 训练内核
│   └── data/                     数据读取与预处理
├── official_submission/          平台提交入口
│   ├── contest_submission.py     提示构造 / 解析 / 训练主循环 / 父链维护
│   ├── decision_contract.md      决策回复合同（唯一约定）
│   └── tests/                    提交侧测试
├── tests/                        测试套件（竞赛 69 项）
├── configs/                      示例配置
├── scripts/                      训练与工具脚本
├── datasets/                     公开数据来源说明与示例数据
├── docs/                         审计与实验报告（Markdown）
├── experiments/                  关键可复现实验脚本（不含数据与结果）
├── requirements-contest.txt      竞赛运行时依赖（固定版本）
├── requirements-contest-sampler.txt  采样器依赖
├── Dockerfile.harness            Harness 镜像构建文件
├── LICENSE                       Apache License 2.0
└── THIRD_PARTY_LICENSES.md       第三方组件与许可证声明
```

## 二、环境与运行

```bash
# 竞赛运行时依赖（无 torch）
pip install -r requirements-contest.txt

# 采样器依赖（仅训练决策采样器时需要）
pip install -r requirements-contest-sampler.txt
```

运行方式详见《系统运行说明文档》。核心入口：

- 本地实验：`python experiments/s2-ablation-b-20261125/ablate.py`
- 等 CPU 预算对照：`python experiments/v8-B-equal-budget-20261125/equal_budget.py`
- 平台提交：由 Harness 调度 `official_submission/contest_submission.py`

## 三、测试

```bash
PYTHONPATH=src python -m unittest discover -s tests/contest -p "test_*.py"
```

预期：69 项（68 通过、1 跳过）。

## 四、许可证与合规

- 主体代码：Apache License 2.0（见 `LICENSE`）
- 第三方组件与许可证：见 `THIRD_PARTY_LICENSES.md`
- 本包**不包含**：账号密钥、隐藏测试集、违规离线拟合产物、平台锁定架构改动

## 五、关键配置要点（v8-B）

| 项 | 值 |
|---|---|
| 决策采样器 | `trio://run_1fei9lfkoj70/sampler_weights/industrial-harness-lora-selection-v3-20261124` |
| 基座模型 | Qwen/Qwen3.5-4B |
| 回归学习率下限 | 3e-3 |
| EMA 权重平均 | 仅任务 C（decay 0.6）；任务 B 已关闭（v8-B） |
| 搜索空间 | lr [3e-3,1e-2]（B/C）、batch [16,512]、epochs [1,5]、sampling_level [1,2] |
| 鲁棒目标 | J = 0.7·E_avg + 0.3·E_worst |
| 多工况门禁 | 总体 ≤1.02×、单工况 ≤1.05× |

## 六、镜像归档

镜像 tar（143.3 MiB）超出平台单文件限制，单独以网盘链接提交，详见《Harness 系统镜像说明》。

- 镜像 ID：`sha256:bec89fcfb75ac7ac6a06dcc0caf97694badd8181b6e8c81af68cee123a82a0e7`
- 归档 SHA-256：`965092bde0b090ba0dbdd487921c6359b9e15bfc4d89a3cd6194124e46950f9d`
