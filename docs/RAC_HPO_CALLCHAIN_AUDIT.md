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

## 3. 关键事实：公开验证与隐藏集严重背离

v6 report 里有两套指标：

| 指标位置 | 含义 | B rmse | C rmse |
|---|---|---|---|
| `datasets[].metrics` | **最终隐藏集成绩** | 486.08 | 56.52 |
| `rounds[].validation_metrics` | **每轮公开验证集** | 665.71→647.95 | 52.09→51.85 |

**结论**：
- B 在公开验证集只从 665 降到 648（**−2.7%**），但隐藏集从 654 到 486（**−25.7%**）。
- C 在公开验证集从 52.09 降到 51.85（−0.4%），但隐藏集从 56.32 升到 56.52（**+0.36% 退步**）。
- 两套指标**量纲不同、趋势不一致**，说明公开验证集与隐藏集分布差异极大，**公开验证改善不可靠地传导到隐藏集**。

这直接坐实方案文档 §2.1 的判断，并引出 S2 消融的硬约束：**任何本地"公开验证集"上的增益，都不能直接当作隐藏集收益的证据**。

---

## 4. v6 逐轮参数轨迹（RAC-HPO 是否真实工作？）

| 任务 | lr 范围 | epochs | batch_size | 观察 |
|---|---|---|---|---|
| A | 恒 0.003 | 恒 2 | 恒 128 | 搜索完全未探索（10 轮同参数） |
| B | 0.003 ~ 0.00493 | 1~2 | 34~469 | 探索范围极窄 |
| C | 0.003 ~ 0.00410 | 1~2 | 18~469 | 探索范围极窄 |

**关键观察**：learning_rate 下限 `REGRESSION_LEARNING_RATE_LOW=3e-3` 生效（B/C 的 lr 都 ≥0.003），但 lr 的上界几乎没被探索（最高只到 0.0049，而 space high=0.01）。epochs 只在 1~2 之间（space high=5）。**RAC-HPO 的搜索在 v6 中实际只探索了搜索空间的一小片**，这解释了为什么之前 v5→v6 的收益需要做析因消融——因为"搜索是否贡献"本身存疑。

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
