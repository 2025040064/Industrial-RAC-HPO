# RAC-HPO 调用链与父链审计（S1）

> 日期：2026-11-25
> 阶段：S1（调用链、父链、验证数据协议审计）
> 依据：v6 平台运行 report（`82522846a0d57928a16292b2c4ad183a-report.json`）+ 源码

---

## 1. 真实调用链

```
平台 Harness
  └─> contest_submission.train(rnd)                 # official_submission/contest_submission.py:166
        ├─ 校验任务契约 (CONTRACTS / Unsupported frozen task contract)
        ├─ 读父检查点 parent = rnd.parent.path(...)  # 校验 parent_sha256 一致
        ├─ load_model(parent) → model                # 24→32→1 / 833 参数
        ├─ read_dataset(train_path, validation_path) # 固定 expected_paths=父 paths
        ├─ projection_groups → train_groups / validation_groups  # 按 unit/bearing/batch 分组
        ├─ evaluate_diagnostics(model, validation) → baseline       # 父模型公开验证诊断
        ├─ ContestRACPolicy(...) → policy           # rac_policy.py
        │     └─ policy.propose(meta, records, transfer_records, round_index)
        │           ├─ 组装同父历史 history（校验 round < current、去重）
        │           ├─ RACSearchPolicy({search_config, seed}, space)  # 鲁棒 TPE
        │           ├─ policy.propose(history) → params, trace
        │           └─ 异常/重复 → tpe_fallback
        ├─ selection_messages(...) → messages       # 决策合同 payload
        ├─ rnd.model(messages, temperature=0)       # PyTRIO Qwen3.5-4B 决策
        ├─ parse_decision(raw_answer) → action ∈ {rac, conservative}
        │     └─ action != rac → 用 conservative alternative
        ├─ fit_epochs(model, train_set, epochs, proposal, train_groups)  # continuation.py
        │     └─ 回归: _fit_averaged (EMA decay=0.6) / 分类: 原路径
        ├─ evaluate_diagnostics(model, validation) → candidate_diagnostics
        ├─ policy.score(...) → robust_objective (J = 0.7 avg + 0.3 worst)
        ├─ model.save(candidate_path) → load_model → 校验 mean/scale/paths 不变
        └─ rnd.submit_candidate(candidate_dir, ...)
              └─ 平台测量主指标 → improved?
                    ├─ 是 → 接纳，父检查点 = 候选（下一轮 parent 指向它）
                    └─ 否 → 保留原父
```

---

## 2. 父检查点传递机制（关键核验）

- 每轮 `parent = rnd.parent.path(checkpoint_name(rnd.parent.descriptor["checkpoint_paths"]))`，并校验 `parent_sha256` 与声明一致。
- 接纳条件（`accepted`）需同时满足：
  1. 平台主指标 `improved`（方向按任务）
  2. `parent_matches`（平台父指标 == 本地重算，相对 1e-7）
  3. `candidate_matches`（平台候选指标 == 本地重算）
  4. `locally_improved`（本地候选优于本地父）
  5. `bearing_gate`（仅 B，逐轴承门槛，`accept_candidate`）
  6. `objective_improved`（J 目标改善）
- 拒绝/异常时保留父模型，下一轮 parent 仍指向上一轮实际接纳的模型。

**v6 平台逐轮 decision 证据（`rounds[].decision`）**：

| 任务 | promote 轮次 | keep 轮次 | 最终父链 |
|---|---|---|---|
| A | 1,2,3,6,7,8,9 | 4,5,10 | baseline → model-82（持续 promote/keep 同一 model-82） |
| B | 1,2,4,9 | 3,5,6,7,8,10 | baseline → model-82 |
| C | 1 | 2-10 | baseline → model-82 |

> 注意：所有任务 selected_artifact_id 恒为 `model-82`，说明平台只维护单一"当前已接纳模型"槽位，`promote` 表示该轮候选被接纳、`keep` 表示保留原模型。

---

## 3. 公开验证与隐藏集分析（已修正，2026-11-25）

### 3.1 修正后的正确表述

**此前 §3 的结论存在两处错误，已修正：**

1. **"量纲不同"是错误推断**。公开验证集 RMSE（B: 665.71）与隐藏集 RMSE（B: 486.08）数值不同，**不代表量纲不同**——两者都是同一物理量（RUL 预测误差，同单位），数值差异完全可以用"两套集合的样本分布/难度不同"解释，无需假设量纲差异。

2. **"公开验证改善 2.7% vs 隐藏集改善 25.7%" 比较基准不同，不可直接相提并论**：
   - **公开验证 −2.7%**（665.71→647.95）是 **v6 内部逐轮变化**（第 1 轮 vs 第 9 轮，同一版本内）。
   - **隐藏集 −25.7%**（654.00→486.08）是 **v5 到 v6 的版本间变化**（两个不同提交的最终隐藏成绩）。
   - 二者一个衡量"同一版本的轮内进展"，一个衡量"跨版本的最终效果"，**根本不是同一件事，之前把它们并列对比是错的**。

### 3.2 正确口径下的对比（v5 vs v6，相同公开验证集、末轮口径）

从 report 提取 **v5 与 v6 在相同公开验证集、相同评价口径下的末轮 `validation_metrics`**：

| 任务 | 指标 | v5 末轮公开验证 | v6 末轮公开验证 | Δ（公开验证） | v5 隐藏集 | v6 隐藏集 | Δ（隐藏集） |
|---|---|---|---|---|---|---|---|
| B | rmse | 644.766 | 647.954 | **+0.49%（变差）** | 654.005 | 486.083 | **−25.68%（变好）** |
| C | rmse | 51.881 | 51.852 | −0.06%（持平） | 56.320 | 56.522 | +0.36%（变差） |
| A | macro_f1 | 0.955135 | 0.860822* | — | 0.860822 | 0.860822 | 持平 |

> *A 任务的 `validation_metrics` 与隐藏集 `metrics` 口径不同（公开验证是子集 F1），此处仅 B/C 的回归 RMSE 可直接对齐。

**修正后的核心结论（重要）：**

1. **v6 相对 v5，在公开验证集上 B 任务不但没改善，反而 +0.49% 变差**（644.766→647.954），C 基本持平。
2. 但 **v6 的隐藏集 B 任务 −25.68% 大幅变好**（654→486），这个收益**在公开验证集上完全不可见，甚至方向相反**。
3. 这比此前"公开验证 −2.7%"的误读更极端：**v6 的 B 收益是纯隐藏集现象，公开验证无法预判**。

**这对 S2 消融的意义**：任何"本地/公开验证 RMSE"上的增益或损失，都**不能**用来推断隐藏集方向。S2 的析因消融只能回答"EMA/lr 下限在公开验证口径下各自贡献多少"，而"它们对隐藏集的真实贡献"本质上是不可本地观测的——这必须在最终提交时用 1 次正式评测机会验证。

### 3.3 硬约束（S2 消融必须遵守）

1. **不使用隐藏集成绩做任何超参数拟合或反复选择**。隐藏集只在最终提交时由平台评测一次。
2. S2 消融的结论口径 = **公开验证集 RMSE**（末轮 + 逐轮），并明确标注"公开验证改善不保证传导到隐藏集，甚至方向可能相反"。
3. v5 与 v6 的任何对比，必须先把两者放到**相同公开验证集、相同评价口径（末轮 validation_metrics）**下对齐，禁止跨口径比较。

---

## 4. v6 逐轮参数轨迹（RAC-HPO 是否真实工作？）

| 任务 | lr 范围 | epochs | batch_size | 观察 |
|---|---|---|---|---|
| A | 恒 0.003 | 恒 2 | 恒 128 | 搜索完全未探索（10 轮同参数） |
| B | 0.003 ~ 0.00493 | 1~2 | 34~469 | 探索范围极窄 |
| C | 0.003 ~ 0.00410 | 1~2 | 18~469 | 探索范围极窄 |

**关键观察**：learning_rate 下限 `REGRESSION_LEARNING_RATE_LOW=3e-3` 生效（B/C 的 lr 都 ≥0.003），但 lr 的上界几乎没被探索（最高只到 0.0049，而 space high=0.01）。epochs 只在 1~2 之间（space high=5）。**RAC-HPO 的搜索在 v6 中实际只探索了搜索空间的一小片**，这解释了为什么之前 v5→v6 的收益需要做析因消融——因为"搜索是否贡献"本身存疑。

## 4A. 代码级结构化追踪：搜索空间收缩定位（S1 核心补充）

> 用户要求：不能仅凭"最终超参数分布集中"就认定 RAC-HPO 没发挥作用，必须逐环节定位收缩发生位置。以下按源码逐环节追踪（`rac_policy.py` / `search.py` / `surrogate_evidence.py` / `contest_submission.py`），并说明每环节的追踪字段（已写进 `selection-audit.jsonl`）。

### 4A.1 搜索链路各环节与追踪字段对照

| 环节 | 代码位置 | 追踪字段（audit jsonl） | v6 实际表现 |
|---|---|---|---|
| ① PyTRIO Sampler 原始输出 | `contest_submission.py:277-284` `rnd.model()` | `decision.raw_answer` / `normalized_response` / `reason_codes` / `risk` | temperature=0，返回 `{selected_option, reason_codes, risk}` |
| ② 参数裁剪前（推荐） | `trace["params"]` → `recommended_params` | `decision.recommended_params` | RAC-HPO 搜索出的候选 |
| ③ 参数裁剪后（最终） | `action != rac` → `alternative` | `decision.final_params` | conservative 时 lr 减半、epochs=1 |
| ④ TPE 候选及数量 | `search.py:136-142` 候选池 | `trace.candidate_count` / `eligible_candidate_count` | 池默认 128，门禁后可能 0 |
| ⑤ 暖启动历史样本 | `rac_policy.py:139-160` 筛选 `records` | `history_usage.same_parent_used_rounds` / `excluded_history` | 仅同父、`round<当前`、去重 |
| ⑥ 跨父迁移筛选 | `rac_policy.py:185-256` `filter_transfer` | `history_usage.transfer_used_rounds` / `transfer_gate` | v6 默认 `transfer_mode=off`，未启用 |
| ⑦ 性能/成本代理预测 | `search.py:144,168-170` `surrogate.predict` | `trace.predicted_regime_mae` / `predicted_overall_mae` / `predicted_cost_seconds` | 仅当 forward 验证通过才 fit |
| ⑧ 代理不确定性与质量门禁 | `search.py:104-115` `forward_check` + `surrogate_evidence.py` | `trace.forward_validation` / `surrogate_activation_reason` | 代理不合格 → `surrogate=None` |
| ⑨ 候选排序与选择原因 | `search.py:163-196` `acquisition_scores` → `argmax` | `trace.acquisition` / `method` / `reason` | `rac_acquisition` / `tpe_fallback` 等 |
| ⑩ 实际执行超参数 | `contest_submission.py:290-295` `fit_epochs` | `configuration.params` / `final_params` | 平台最终执行值 |
| ⑪ Checkpoint 父链与接纳 | `contest_submission.py:331-360` 六门验收 | `gates` / `accepted` / `selected_sha256` | 父链 SHA 连续 |

### 4A.2 搜索空间收缩的根因定位（B 任务为例）

v6 B 任务参数分布集中的**根因不是"RAC-HPO 没被调用"，而是搜索启动门槛过高**，收缩发生在**环节 ④/⑧ 之前的"暖启动门槛"**：

1. **门槛一（决定性）：`insufficient_history`**（`search.py:92-93`）
   `len(completed) < max(warmup_trials=8, minimum_history=8)` 时，`RACSearchPolicy.propose` 直接返回 `None`，`method=insufficient_history`，**TPE 候选池根本不生成**。
   - v6 B 任务 10 轮里 promote 只有 4 轮（round 1,2,4,9），大量 keep 导致 `completed`（有效历史）长期 < 8，**绝大多数轮次走 `_fallback`（纯 TPE 无代理）或 `checkpoint_reference`**。
   - 这就是 lr 集中在 0.003、epochs 集中 1~2 的直接原因：`checkpoint_reference` 用父检查点 lr（0.002）被 clamp 到下限 3e-3，epochs 固定 2。

2. **门槛二：代理 forward 质量门禁**（`search.py:104-129` + `surrogate_evidence.py`）
   即使历史 ≥ 8，还需 `forward_check().performance_validation.passed == True` 才 fit 代理；否则 `surrogate=None` → 返回 `None`（走 fallback）。
   - `shadow_evidence` 要求 ≥3 个匹配 shadow trial 且 Spearman rank ≥ 0 且 MAE ≤ 1.25×naive，**在 10 轮内极难满足**（尤其 surrogate_mode=shadow 时）。

3. **门槛三：候选退化门禁**（`search.py:171-175`）
   128 候选经 `allowed`（`predicted_overall <= baseline*(1+0.1)` + 历史去重）筛选，可能全被拒 → `no_candidate_passed_predicted_overall_guard`。

**结论**：v6 中 RAC-HPO 的**代理搜索（rac_acquisition）几乎从未真正启动**，实际走的是 `checkpoint_reference` / `tpe_fallback` 兜底路径。这不是"搜索失效"，而是**在 10 轮 × 大量 keep 的预算下，暖启动门槛（8 条有效历史）无法跨越**。这为 S2 消融提供了关键背景：EMA 与 lr 下限的收益，是在"代理搜索基本未启动"的前提下取得的，需分离"训练侧改动贡献"与"搜索贡献"。

### 4A.3 父检查点 SHA 连续性核验（v6 B 任务）

平台 report `rounds[]` 的 `parent_artifact_id` / `selected_artifact_id` 连续性（B 任务）：

| 轮 | parent | selected | 连续？ |
|---|---|---|---|
| 1 | baseline-cpu-b-rul | round-01-1（promote） | ✅ |
| 2 | round-01-1 | round-02-1（promote） | ✅ 父=上轮选中 |
| 3 | round-02-1 | round-02-1（keep） | ✅ |
| 4 | round-02-1 | round-04-1（promote） | ✅ 父=round2 选中 |
| 5-8 | round-04-1 | round-04-1（keep） | ✅ |
| 9 | round-04-1 | round-09-1（promote） | ✅ |
| 10 | round-09-1 | round-09-1（keep） | ✅ |

父链完全连续，无断裂。**注意**：平台 report 只暴露 `artifact_id`（如 `model-...-B-round-04-1`），不含逐字节 SHA；真正的 `parent_sha256`/`candidate_sha256`/`selected_sha256` 连续性核验依赖 `selection-audit.jsonl`（已随容器销毁），**本地复现时需重建**（见 S2 的复现脚本）。

---

## 5. 验证数据协议（本地消融须遵守）

- 训练/验证只来自公开 train/validation JSONL（`read_dataset`），不碰隐藏集。
- 分组：A 按 `source_batch`，B 按 `bearing`，C 按 `source_subset/unit`。
- 父检查点可能已见过全部公开训练数据（平台冻结的父检查点），故本地分组验证只能衡量**续训过程的相对泛化**，不能宣称严格未见设备评估。
- J 目标：`0.7 * E_avg + 0.3 * E_worst`（归一化组误差）。

---

## 6. 结论与进入 S2 的前置

1. 调用链完整、父链机制清晰，RAC-HPO 确实参与每轮决策（不是空壳）。
2. **但搜索空间在 v6 中几乎未被有效探索**（lr 集中在 0.003、epochs 集中 1~2），这是 S2 消融必须首先分离的混杂因素。
3. 公开验证与隐藏集背离是硬约束，S2 消融的结论须以"公开验证集"为统一口径，并明确标注其局限性。

**S2 前置阻塞项（待用户确认）**：
- git 基线冻结范围（见 S0 审计 §4）。
- 消融的 CPU 预算协议（平台每任务 10 轮、单线程 CPU；本地须等预算）。
