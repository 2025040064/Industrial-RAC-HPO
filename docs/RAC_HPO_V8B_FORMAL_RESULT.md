# v8-B 正式评测结果（第 1 次正式评测）

## 基本信息

| 字段 | 值 |
|---|---|
| 运行 ID | `83d226c33445ca8176ec66cf29885916` |
| 提交版本 | **v8**（submission_id `cfd94428c4d325e00cc00921927994b9`） |
| 运行类型 | **正式评测（formal），第 1 次** |
| 状态 | completed（已完成） |
| **正式成绩（score）** | **52.24** |
| 时间 | 2026-11-25 18:08:21（GMT+8）创建，18:57:44 出分 |
| 数据集族 | uci-gas-drift |
| 主指标 | macro_f1（方向 higher），主数据集 = **A** |

## 提交内容（v8-B 唯一改动）

- 仅关闭 **B 任务** EMA 平均（`continuation.py`：`averaged = task==regression and profile != "B"`）
- A（分类）、C（回归）保持不变，lr 下限 3e-3 保留
- 其余 4 个运行时文件与 v6 逐字节一致

## 客观评分分解（objective_result）

| 组件 | 值 |
|---|---|
| **objective_score** | **11.77** |
| mean_gain | 3.223 |
| recovery | 3.373 |
| resource_efficiency | 0 |
| retention | 5 |
| worst_stage | 0.176 |

### 门禁（gates）

| 门禁 | 结果 |
|---|---|
| autonomous_completion_on_time | ✅ true |
| **complete_materials_and_reproducibility** | ❌ **false** |
| **experiment_records_complete** | ❌ **false** |
| not_below_static_baseline | ✅ true |
| three_traceable_decision_cycles | ✅ true |

**`eligible_for_ranking = false`**（不可进入排名）

## 各任务公开验证指标（validation_metrics，首轮 → 末轮）

| 任务 | 首轮 | 末轮 | 末轮决策 |
|---|---|---|---|
| **A**（classification） | acc 0.8826 / f1 0.7166 | **acc 0.9674 / f1 0.9551** | keep |
| **B**（regression） | mae 545.86 / rmse 656.35 | **mae 539.09 / rmse 635.09** | promote |
| **C**（regression） | mae 38.45 / rmse 52.09 / nasa 3.67e9 | mae 38.43 / rmse 52.13 / nasa 8.76e9 | keep |

## 决策与动作分布（10 轮/任务）

| 任务 | 决策分布 | 动作分布 |
|---|---|---|
| A | promote 7 / keep 3 | rac 10 |
| B | promote 4 / keep 6 | rac 5 / conservative 5 |
| C | promote 1 / keep 9 | rac 5 / conservative 5 |

## 关键结论

1. **正式成绩 52.24**，但 `eligible_for_ranking = false`——**不可进入排名**。
2. **两道门禁未通过**：`complete_materials_and_reproducibility`（材料与可复现性不完整）、`experiment_records_complete`（实验记录不完整）。
3. **隐藏集逐任务最终指标（A/B/C 的 accuracy/RMSE/MAE）在平台 API 报告里未直接暴露**（`report` 字段为 null），只能看到总成绩 52.24 和 objective_score 11.77，以及各任务公开验证集的逐轮轨迹。
4. **B 任务（v8-B 唯一改动对象）**：公开验证 RMSE 从 656.35 → 635.09（改善 −3.2%），末轮 promote。但这是公开验证口径，隐藏集口径未知。
5. 主数据集判定为 A（classification/macro_f1），而 v8-B 的改动只影响 B（regression），因此 **v8-B 对"正式成绩主指标"的实际影响有限**。

## 待补充（发给 Codex 时需注明）

- 隐藏集 A/B/C 的最终指标（accuracy / macro_f1 / MAE / RMSE / NASA）未在 API 报告中暴露，需要从平台网页"查看训练记录"或"查看报告"入口获取。
- 两道未通过门禁（材料完整性、实验记录完整性）的具体缺失项，需要对照平台规则补齐。

---

## 追加取证（2026-11-25 21:52，平台 API 实测）

上一节"待补充"两项已分别查清，取证方法与字段位置见 [`docs/PLATFORM_API_FIELDS.md`](PLATFORM_API_FIELDS.md)。

### 1. 两道门禁为何不通过（重大修正）

不是"上传的文件不齐"，而是**平台从未审核 v8**：

| 字段（`GET /api/v1/submissions`） | v8 实测值 |
|---|---|
| `compliance_status` | `unreviewed` |
| `compliance_reason` | `""`（空） |
| `materials_complete` | `null`（未评审） |
| `base_model_confirmed` | `false` |

- `experiment_records_complete=false` **与记录是否跑完无关**：`training_records` 中 A/B/C 三项均为
  `record_complete=true`、各 10 轮。最可疑来源是 `workspace_suite.datasets` 的
  `label_status`：**A=draft、C=draft**（B=approved）。
- `complete_materials_and_reproducibility=false` **与少交文件无关**：`materials_complete=null` 且
  `compliance_status=unreviewed`，未审核状态下该门禁默认不通过。
- 平台历史上唯一给出文字拒稿的是 v7（`da5f98ed…`）：「当前提交不符合赛题续训要求。请基于官方
  baseline 及平台提供的父检查点实现真实续训，修改后重新上传镜像并提交新版本；不得从头训练
  另一套模型替代 baseline。」——人工复审对 v8 同样适用，风险高于材料问题。

### 2. 隐藏集逐任务指标：确认 API 不存在

`report` 字段为 `null`；`training_records[].rounds[].validation_metrics` 仅含公开验证集指标。
追加探测 `/runs/{id}/metrics`、`/records`、`/result`、`/score`、`/report/A`、`?task=A` 均 404 或
返回同一份报告。结论：只在平台网页「查看报告」或评审后台可见。

### 3. 新增发现：一个零分分项

`objective_components`：`mean_gain=3.223`、`recovery=3.373`、`retention=5`、
`worst_stage=0.176`，而 **`resource_efficiency=0`**。这是唯一为零的分项，可能口径为镜像体积
（143.3 MB）或 CPU 用时，是最容易补分的方向。

原始响应已存档：`experiments/platform-runs/submissions-list.json`、
`experiments/platform-runs/83d226c33445ca8176ec66cf29885916-report-full.json`。
