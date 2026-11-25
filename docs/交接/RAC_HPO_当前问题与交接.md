# RAC-HPO 当前问题与交接

> 交接整理时间：2026-11-25，北京时间。本文根据仓库现有记录和工作区状态整理，供队友接手；平台规则、剩余次数和最新状态仍需到平台核实。文中的路径均相对仓库根目录。

## 1. 先看结论

目前最紧急的问题不是继续调参，而是 **v8-B 虽已完成正式评测并得到 52.24 分，却因两项门禁未通过，无法进入排名**。具体缺少什么材料、哪些实验记录不符合要求，现有报告没有说明。

另一个核心问题是 **无法从已保存的 v8-B 正式评测 API 报告中看到 A/B/C 的隐藏集最终指标**，因此不能判断这次对 B 任务的改动是否优于 v6。已有公开验证结果和历史试运行结果，但二者不能混为同一口径。

接手建议顺序：**先核对门禁要求与缺失项 → 查正式评测详细报告和剩余次数 → 固定版本与证据链 → 再决定是否修改算法或重新评测**。不要在原因和次数未确认前假定重新提交一定能通过门禁。

## 2. 正式评测与排名门禁

### 2.1 本次正式结果

| 项目 | 记录值 |
| --- | --- |
| 版本 | v8-B，平台提交版本显示为 v8 |
| 提交 ID | `cfd94428c4d325e00cc00921927994b9` |
| 运行 ID | `83d226c33445ca8176ec66cf29885916` |
| 运行类型、状态 | 第 1 次正式评测（formal），`completed` |
| 创建、出分时间 | 2026-11-25 18:08:21、18:57:44（北京时间） |
| 正式成绩 `score` | **52.24** |
| `objective_score` | **11.77**（与 `score` 是报告中的不同字段，不能当作同一指标） |
| 主数据集 / 主指标 | A / 分类 `macro_f1`，越高越好 |
| 排名资格 | **`eligible_for_ranking = false`** |

报告中的客观评分组件还包括：`mean_gain = 3.223`、`recovery = 3.373`、`resource_efficiency = 0`、`retention = 5`、`worst_stage = 0.176`。**资源效率为 0 是值得核查的现象，但当前没有证据说明其原因或它与门禁失败存在因果关系。**

来源：[`RAC_HPO_V8B_FORMAL_RESULT.md`](../RAC_HPO_V8B_FORMAL_RESULT.md)；[本地保存的平台报告](../../experiments/platform-runs/83d226c33445ca8176ec66cf29885916-report.json)。

### 2.2 两项未通过门禁

| 门禁 | 结果 | 当前可确认内容 |
| --- | --- | --- |
| `complete_materials_and_reproducibility` | `false` | 平台判定材料与可复现性门禁未通过；具体缺项和判定规则未知 |
| `experiment_records_complete` | `false` | 平台判定实验记录完整性门禁未通过；具体缺项和判定规则未知 |

另外三项 `autonomous_completion_on_time`、`not_below_static_baseline`、`three_traceable_decision_cycles` 均为 `true`。这不代表材料与实验记录的具体要求已满足；也不能据此推断两项失败一定是同一个原因。

**接手需要查清：**

1. 平台对两项门禁的原文要求、逐项检查清单、适用的提交入口和截止时间。
2. 当前提交关联了哪些说明书、源码、镜像、依赖、训练回执与实验记录；哪些缺失、不可访问、版本不匹配或不符合格式。
3. 材料补齐后是否可在原提交上更新或申请复核，还是必须创建新提交、重新评测；两种方式分别消耗什么机会。
4. 保存平台规则、缺失项说明、补交回执与复核结果，并记录时间、提交 ID 和运行 ID。

上面是待查清的方向，**不是已确认的缺失项**。本地 Git 有未跟踪文件也不能直接证明平台门禁因此失败。

## 3. 隐藏集指标不可见，版本收益无法判定

### 3.1 已知信息与缺口

已保存的 v8-B 正式评测 API 响应中，顶层 `report` 为 `null`；记录中可见总成绩、客观分与公开验证轨迹，但没有 A/B/C 的隐藏集最终指标。因此目前不能判断 v8-B 的 B 隐藏集结果与 v6 相比是改善还是退步，也无法单独分析 A、C 的正式隐藏集表现。

平台网页“查看训练记录”或“查看报告”、其他报告字段、导出入口或平台支持渠道都值得检查，但**目前不能保证这些入口提供所需指标**。查到后请保留原始回执，区分正式评测与试运行、公开验证与隐藏测试，并按运行 ID 分开记录。

### 3.2 v8-B 公开验证轨迹

以下是同一次 v8-B 运行中首轮到末轮的公开验证变化，**不是隐藏集指标，也不是 v8-B 与 v6 的直接对照**：

| 任务 | 首轮 | 末轮 | 末轮决策 |
| --- | --- | --- | --- |
| A 分类 | accuracy 0.8826 / macro-F1 0.7166 | accuracy 0.9674 / macro-F1 0.9551 | `keep` |
| B 回归 | MAE 545.86 / RMSE 656.35 | MAE 539.09 / RMSE 635.09 | `promote` |
| C 回归 | MAE 38.45 / RMSE 52.09 / NASA 3.67e9 | MAE 38.43 / RMSE 52.13 / NASA 8.76e9 | `keep` |

B 的 RMSE 首轮到末轮下降约 3.2%；C 的末轮 RMSE 和 NASA 指标高于首轮。不同轮次的候选、选中模型与评测指标需要按报告定义核对，不能只凭首末两行断言最终隐藏结果或改动因果。

### 3.3 为什么不能把公开改善当成隐藏改善

历史 v5、v6 平台**试运行**记录显示：v5 → v6，B 隐藏集 RMSE 约 654.005 → 486.083，而 C 隐藏集 RMSE 约 56.320 → 56.522、MAE 约 41.176 → 41.508。v6 在 C 公开验证上的改善没有对应为这次隐藏集的改善。它说明存在外推风险，但不同数据集之间的差异与变化原因仍需核查，不能仅据此断言某个机制或分布差异是根因。

v6 同时修改了回归 EMA 与学习率下限，不能把 B 的隐藏集收益单独归因于 EMA。v8-B 关闭 B 的 EMA 后可能改善，也可能损失 v6 的隐藏集收益，当前均属待验证。

## 4. 版本、实验方向与尚未解决的技术问题

### 4.1 v6、v7、v8-B 的关系

| 版本 | 核心内容 | 已知结果或状态 |
| --- | --- | --- |
| v6 | B/C 回归使用 decay 0.6 的 EMA；回归学习率下限 3e-3 | 试运行 `82522846a0d57928a16292b2c4ad183a`；隐藏结果见上。Git 基线为 `baseline-v6-20261125`，提交 `2c3f6ad` |
| v7 | 在 v6 基础上尝试 C 的 OOF 时序软标签蒸馏，并将 EMA decay 调为 0.4 | 状态文件记录提交 `da5f98ed998983cc0a10c523bec9d6b6`、试运行 `93386be28a70bdbf3f76dacfcbec5214`；本次未核实其最终报告和隐藏收益 |
| v8-B | 从 v6 构建，仅关闭 B 任务 EMA；A/C 沿用 v6 路径，回归学习率下限 3e-3 保留 | 正式评测已完成，但没有排名资格；Git `candidate/v8-B` 当前提交 `8c54c9e` |

**v8-B 不是基于 v7 的增量版本**：它没有带入 v7 的 C 软标签和 decay 0.4；当前源码中 C 的 EMA decay 为 0.6。这是版本分支选择造成的差异，不应在没有对照验证的情况下直接称为性能回退或误删。

历史基线审计曾发现 `rac_policy.py` 的 epochs 下限与 v6 镜像不一致；同一审计后续记录已恢复 `low = 1` 并冻结基线，当前源码也是 `low = 1`。审计文档前后保留了不同阶段结论，阅读时要按时间和后续处置判断，不要把早期“待修复”当成当前状态。

### 4.2 B 任务的改动有公开验证依据，但正式收益未知

v8-B 发布报告记录了 G2（B 的 EMA off）与 G3（EMA on，v6 路径）的本地对照，均为公开验证口径：5 个**搜索种子**下最终 RMSE 均值约 630.28 对 653.44，配对差值 −23.16，报告给出的 95% CI 为 [−27.24, −19.07]；平均算法 CPU 分别为 0.329 秒和 0.341 秒。训练种子保持 42。五个结果方向一致、测得 CPU 接近，但样本量只有 5，不能当作隐藏集或正式成绩提升的证明。

证据与脚本：[`release-report.md`](../../experiments/rebuild-selection-v8-B-20261125/release-report.md)、[`equal_budget.py`](../../experiments/v8-B-equal-budget-20261125/equal_budget.py)、[`ablation-results.json`](../../experiments/v8-B-equal-budget-20261125/results/ablation-results.json)。

### 4.3 主指标与优化对象不一致

正式评测记录的主数据集是 A、主指标是 `macro_f1`，但 v8-B 唯一运行时改动针对 B 回归任务。B 的改进可能影响综合评分的某些部分，但是否影响、影响多少，需要先核对平台评分公式和正式报告；不能仅凭主指标就断定总分一定不变或收益一定有限。

### 4.4 C 任务与时序路线仍有边界

- 历史记录中 C 的公开验证与隐藏结果存在落差；v6 的 C 隐藏 MAE/RMSE 较 v5 变差，NASA 等尾部指标也需要单独核对。
- 已有本地窗口特征/TCN 与蒸馏实验。历史审计指出：现有预测请求只包含 `{task, inputs}`，不保证可取得 unit/cycle 或历史窗口，父检查点输入结构也固定；TCN 还涉及当前竞赛依赖中没有的 PyTorch。上述结论应在**当前平台合同**下重新确认，不能直接把离线实验作为可提交方案。
- v7 的蒸馏和 decay 0.4 已有本地实验及 trial 标识，但其最终平台收益在本次整理时未核实；不要把历史文档中的“尚未构建 v7”当作现状。

### 4.5 算法机制收益仍需独立证明

历史阶段三固定预算对照中，代理、迁移、成本机制的实际触发次数记录为 0。该实验不能证明这些机制带来收益，也不等于证明它们在所有条件下无效。若要写入成绩归因或对外材料，应先记录触发与候选排序变化，再固定起点、数据投影、预算、种子和选模规则做多种子对照。

### 4.6 已处理的问题与仍缺的诊断证据

历史 v3 平台运行出现 30/30 无效回复；后续 v4/v5 的受控试运行记录显示无效回退消失，v5 的两类决策均可达。v8-B 正式记录也给出 A/B/C 的 RAC 与 conservative 动作分布。**不要把旧版的 30/30 无效回退当作当前已确认故障**；若怀疑复发，应针对具体运行重新核验。

旧问题的原始模型回复、逐轮 `finish_reason` 和逐次 token 等证据仍有缺口，历史根因不能仅凭总 token 数或本地回放定论。更多证据见 [`experiments/platform-runs/README.md`](../../experiments/platform-runs/README.md)。

## 5. 工作区、复现与交付风险

以下是整理时本机 `git status` 的快照，不代表这些文件都属于 v8-B 的正式镜像，也不表示应直接删除或提交：

- 当前分支 `candidate/v8-B`，HEAD 为 `8c54c9e`；v6 标签 `baseline-v6-20261125` 指向 `2c3f6ad`。
- 已跟踪但未提交：`RAC-HPO_参赛作品说明书.docx`、`src/rac_hpo/data/temporal_window.py`、`src/rac_hpo/training/tcn_trainer.py`、`tests/test_tcn_smoke.py`。
- 未跟踪内容包括正式结果文档、平台运行报告、多个版本的构建与本地实验目录、`datasets/`、`official_submission/decision_contract.md`、时序特征代码与测试。正式评测报告也位于未跟踪目录中。
- v8-B 的 `release-report.md` 已被 Git 跟踪；构建 context、`build-validation.json`、提交脚本和说明等未跟踪；`harness-selection-v8-B.tar` 被 Git 忽略。**仅交付 Git 提交或发送分支，队友可能拿不到这些证据和镜像。**
- 不应把所有未提交内容都判为无关：其中有时序实验、参赛说明书和关键平台证据，需先逐项核对来源与用途，再决定归档、共享或提交。

v8-B 发布记录中的本地镜像归档：`experiments/rebuild-selection-v8-B-20261125/harness-selection-v8-B.tar`，大小 150,343,680 字节，记录的 SHA-256 为 `965092bde0b090ba0dbdd487921c6359b9e15bfc4d89a3cd6194124e46950f9d`。交付或复现前应重新计算摘要，核对平台归档、提交和运行之间的关联；平台未提供摘要时，不能仅凭文件大小宣称字节一致。

历史文档的时间状态也需要注意：v8-B `release-report.md` 是正式评测前的快照，其中“未提交正式评测”和旧次数统计已经过时；`platform-runs/README.md` 的 v6 “试运行中”描述也被后续结果和已保存报告覆盖。**当前剩余 trial / formal 次数以平台实时显示为准。**

测试数存在不同记录：v8-B 发布报告写 68 项（67 通过、1 跳过），提交说明写 69 项（68 通过、1 跳过）。它们可能对应不同测试阶段，但现有文字不足以确认，交接时不要当作同一次验证；应查看对应日志或在固定环境下重跑后记录命令、时间、版本和结果。本次仅整理资料，未重跑测试。

## 6. 建议队友按顺序处理

1. **核对排名门禁**：取得平台判定规则及逐项缺失说明；列出材料、实验记录、责任人、补交入口、截止时间和验证方式。确认能否复核及是否消耗评测次数。
2. **获取评测明细**：围绕正式运行 `83d226c33445ca8176ec66cf29885916` 查找 A/B/C 隐藏指标、选中模型、评测口径及资源效率为 0 的解释；无法获取时标记为 unknown。
3. **补齐版本与实验台账**：按运行 ID 建立 v5/v6/v7/v8-B 的提交、镜像、代码 SHA、Sampler、数据口径、训练参数、逐轮轨迹和结果对应表；特别核对 v7 trial 最终状态。
4. **整理交付包**：先备份并核对本机未提交和未跟踪内容，确保队友能取得报告、构建上下文、实验结果和需要的镜像；数据、密钥和大文件按团队约定安全交付，不要盲目加入 Git。
5. **再做算法决策**：平台规则和次数明确后，以 v6 为清晰基线，分别评估 A 主指标、B EMA 消融和 C 方向；公开验证与隐藏结果分开报告，保持同预算、同种子和相同选模协议。
6. **同步参赛材料**：按照已核实的事实更新说明书与实验记录，不把历史公开验证收益写成正式隐藏收益，不把局部实验写成已证明的整体算法收益。

## 7. 重要入口

| 用途 | 文件 |
| --- | --- |
| v8-B 正式成绩、门禁、公开验证轨迹 | [`docs/RAC_HPO_V8B_FORMAL_RESULT.md`](../RAC_HPO_V8B_FORMAL_RESULT.md) |
| v8-B 正式评测 API 原始保存 | [`experiments/platform-runs/83d226c33445ca8176ec66cf29885916-report.json`](../../experiments/platform-runs/83d226c33445ca8176ec66cf29885916-report.json) |
| v8-B 变更、本地对照和镜像身份 | [`experiments/rebuild-selection-v8-B-20261125/release-report.md`](../../experiments/rebuild-selection-v8-B-20261125/release-report.md)、[`submission-note.md`](../../experiments/rebuild-selection-v8-B-20261125/submission-note.md) |
| v6 试运行完整报告 | [`experiments/platform-runs/82522846a0d57928a16292b2c4ad183a-report.json`](../../experiments/platform-runs/82522846a0d57928a16292b2c4ad183a-report.json) |
| v7 提交与 trial 标识 | [`experiments/rebuild-selection-v7-20261124/platform-state-v7.json`](../../experiments/rebuild-selection-v7-20261124/platform-state-v7.json)、[`submission-note.md`](../../experiments/rebuild-selection-v7-20261124/submission-note.md) |
| v6 基线冻结与历史不一致 | [`docs/RAC_HPO_BASELINE_AUDIT.md`](../RAC_HPO_BASELINE_AUDIT.md) |
| 历史运行与诊断 | [`experiments/platform-runs/README.md`](../../experiments/platform-runs/README.md)、[`RAC-HPO_问题解决与验证方案.md`](../../RAC-HPO_问题解决与验证方案.md)；须注意内部保留的历史状态 |
| 调用链与合同 | [`docs/RAC_HPO_CALLCHAIN_AUDIT.md`](../RAC_HPO_CALLCHAIN_AUDIT.md)、[`official_submission/decision_contract.md`](../../official_submission/decision_contract.md) |

以上部分文件尚未纳入 Git 或被忽略，交接前应确认队友实际能访问。
