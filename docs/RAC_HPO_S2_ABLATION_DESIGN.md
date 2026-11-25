# S2 析因消融实验设计（B 任务：EMA × lr 下限）

> 日期：2026-11-25
> 阶段：S2（B 任务训练侧改动析因消融）
> 性质：实验方案 + 验收协议，结论必须由真实实验支撑

---

## 1. 消融目标

v5→v6 引入了两个训练侧改动，B 任务隐藏集 RMSE 654.00→486.08（−25.7%）。本次消融将这两个因子**析因分离**，回答：

1. EMA 权重平均（`EMA_DECAY=0.6`）对 B 任务公开验证 RMSE 的独立贡献。
2. 回归学习率下限（`REGRESSION_LEARNING_RATE_LOW=3e-3`）的独立贡献。
3. 两者的交互效应。

**硬约束**：所有结论口径 = 公开验证集 RMSE，**不使用隐藏集成绩做超参拟合**。公开验证改善不保证传导到隐藏集（S1 审计已证伪其传导性）。

## 2. 两个因子的权威定义（从镜像核实，非假定）

### 因子 A：EMA 权重平均

| 版本 | 实现 | 位置 |
|---|---|---|
| v5 | `fit_epochs` 直接 `model.fit(x, y, epochs)`，**无 EMA** | `continuation.py:24-28` |
| v6 | `fit_epochs` 对回归走 `_fit_averaged`，`EMA_DECAY=0.6` | `continuation.py:31-55` |

### 因子 B：回归学习率下限

| 版本 | `learning_rate.low` | 位置 |
|---|---|---|
| v5 | `1e-5`（所有任务统一，**无回归特判**） | `rac_policy.py:98` |
| v6 | `1e-5 if task=="A" else 3e-3`（回归任务 3e-3） | `rac_policy.py:104` |

> 原始 lr 下限 **1e-5** 已从 v5 镜像 `experiments/rebuild-selection-v5-20261124/context/app/rac_hpo/contest/rac_policy.py` 第 98 行逐字核实，**不是自行假定**。

## 3. 2×2 析因设计

| 组 | EMA | lr 下限 | 等价版本 |
|---|---|---|---|
| G0 | off | 1e-5 | v5 原始 |
| G1 | on | 1e-5 | v5 + EMA |
| G2 | off | 3e-3 | v5 + lr 下限 |
| G3 | on | 3e-3 | **v6（完整）** |

- EMA 开启时 `decay` 固定 0.6。
- **lr 由 RAC-HPO 动态搜索，不固定、不强制四组相同**（用户明确要求）。
- 四组相同：初始父模型、数据划分、验证方式、搜索策略、随机种子、其他超参。

## 4. 实验协议

### 4.1 完全复现 v6 平台逐轮决策机制

本地 harness 忠实镜像 `contest_submission.train()` 的核心循环：

```
for rnd in 1..rounds:
    parent = 当前已接纳模型
    proposal, trace = ContestRACPolicy.propose(...)   # RAC-HPO 动态搜索 lr
    recommended_lr = trace.params.learning_rate        # 裁剪前
    alternative = {lr/2 夹取到下限, epochs=1}          # conservative
    action = PyTRIO(selection_contract, temperature=0)  # 真实 Sampler 调用
    final_lr = recommended_lr if action==rac else alternative.lr   # 裁剪后
    fit_epochs / fit_plain (按 EMA 开关)
    accepted = 六门验收（主指标改善 + 匹配 + bearing + J）
    model = best if accepted else rollback
```

### 4.2 PyTRIO 决策

- 真实调用 PyTRIO Sampler 服务（`trio://run_1fei9lfkoj70/sampler_weights/industrial-harness-lora-selection-v3-20261124`）。
- 决策合同 = `selection_messages`（`{selected_option, reason_codes, risk}`），temperature=0，seed=42。
- 本地已实测连通（返回合法决策）。

### 4.3 阶段划分

| 阶段 | 种子 × 组 × 轮 | 续训次数 | 用途 |
|---|---|---|---|
| 冒烟（本阶段） | 3 × 4 × 3 | 36 | 验证协议 + 初判趋势 |
| 正式（冒烟通过后） | 3 × 4 × 10 | 120 | 结论 + 等 CPU 预算对照 |

## 5. 记录项（每轮）

| 项 | 字段 |
|---|---|
| 裁剪前 lr | `recommended_lr` |
| 裁剪后 lr | `final_lr` |
| 下限触发 | `floor_triggered`（final_lr ≤ low + 1e-12） |
| 搜索方法 | `search_method`（checkpoint_reference / tpe_fallback / rac_acquisition / global_exploration） |
| 代理预测 | `predicted_overall_mae` / `predicted_cost_seconds` |
| 门禁 | `surrogate_activation_reason` / `forward_validation` |
| 候选数 | `candidate_count` / `eligible_candidate_count` |
| 决策 | `action` / `reason_codes` / `risk` |
| 接纳 | `accepted` / `bearing_gate` / `objective_improved` |
| 成本 | `train_cpu_seconds` / `wall_seconds` / `process_cpu_seconds` |
| 规模 | `epochs` / `samples` |

## 6. 验收指标（须全部输出）

- 各组 RMSE 均值 ± 标准差（3 种子）
- 最差轴承误差（`bearing` 分组内最差 RMSE）
- 各随机种子独立结果
- EMA 独立贡献 = mean(G1−G0, G3−G2)
- lr 下限独立贡献 = mean(G2−G0, G3−G1)
- 交互效应 = (G3−G2) − (G1−G0)
- CPU 成本与单位成本收益（RMSE 改善 / CPU 秒）
- 逐轮真实训练与模型接纳记录

## 7. CPU 预算协议

### 7.1 等轮数 vs 等 CPU 预算

- **冒烟阶段**：等轮数（3 轮），记录 CPU 成本作为基准。
- **正式阶段**：预先规定硬 CPU 预算（以 v6 平台 B 任务实测 695.89 CPU 秒为锚，按本地硬件折算），**不能事后截取日志宣称等预算**。

### 7.2 记录项

| 项 | 说明 |
|---|---|
| 搜索 CPU 时间 | `search_cpu` |
| 训练 CPU 时间 | `train_cpu` |
| 代理拟合/预测 CPU | 在 `search_cpu` 内细分 |
| 验证 CPU 时间 | `validation_cpu` |
| 总 CPU 时间 | `process_cpu_seconds` |
| Wall-clock | `wall_seconds` |
| 实际 epochs | `epochs` |
| 样本处理量 | `samples` |
| 候选接纳率 | accepted/rounds |

## 8. 交付物

1. `experiments/s2-ablation-b-20261125/ablate.py` — 消融脚本
2. `experiments/s2-ablation-b-20261125/results/ablation-results.json` — 原始数据
3. `docs/RAC_HPO_S2_ABLATION_REPORT.md` — S2 实验报告
4. 独立 git 提交（不含时序产物/数据/密钥）
5. 根据结果决定 S3 搜索空间扩展方向

## 9. 关键事实修正（审计发现）

- **B 任务输入是 34 维**（`paths` 长度 34），不是此前认知的 24 维（24 维是 C/FD001 任务）。
- **B 父检查点参数 865 个**（`parameter_count=865`），已训练 15 epoch、825 steps。
- **父检查点 `learning_rate=0.003`**，恰等于 v6 的回归 lr 下限 3e-3（`checkpoint_reference` 分支的 clamp 起点）。
- v5 平台 B 末轮公开验证 RMSE 644.77，v6 末轮 647.95（公开验证反而 +0.49%），但隐藏集 −25.7%——**收益是纯隐藏集现象**。
