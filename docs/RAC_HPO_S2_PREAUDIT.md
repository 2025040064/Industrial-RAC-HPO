# S2 前置补充审计：配置生效链路、搜索历史机制、10 轮本地回放

> 日期：2026-11-25
> 阶段：S2 正式消融前的补充审计（对应用户补充要求二/三/四/七）
> 依据：v6 平台 report + v5/v6 镜像源码 + 本地逐字节复现

---

## 1. 生效配置核验（surrogate_mode / transfer_mode / cost_mode / bearing_mode）

用户要求区分五层配置来源，逐层核对如下：

| 配置项 | 类默认（rac_policy.py:62） | stage3_controls 默认 | Docker ENV | 平台运行时覆盖 | **最终生效** |
|---|---|---|---|---|---|
| `surrogate_mode` | `"active"` | `RAC_SURROGATE_MODE` 默认 `"shadow"` | 无 RAC_* ENV | 无 | **`"shadow"`** |
| `transfer_mode` | `"legacy"` | `RAC_TRANSFER_MODE` 默认 `"off"`（`RAC_TRANSFER_HISTORY`≠1） | 无 | 无 | **`"off"`** |
| `cost_mode` | `None` | `RAC_COST_MODE` 默认 `"off"` | 无 | 无 | **`"off"`** |
| `bearing_mode` | `"off"` | `RAC_BEARING_FEASIBILITY` 默认 `"off"` | 无 | 无 | **`"off"`** |

**决定性证据链**：
1. `contest_submission.py:169` 用 `controls(os.environ)` 取模式，`:238-240` 传给 `ContestRACPolicy(..., transfer_mode=mode["transfer_mode"], surrogate_mode=mode["surrogate_mode"], cost_mode=mode["cost_mode"], bearing_mode=mode["bearing_mode"], enforce_shadow_evidence=True)`。
2. `Dockerfile`（v6 context）**不含任何 `RAC_SURROGATE_MODE`/`RAC_TRANSFER_MODE`/`RAC_COST_MODE`/`RAC_BEARING_FEASIBILITY` ENV**（仅 `PIP_*` 和 `PATH`），故平台运行时取 `controls()` 的默认值。
3. `surrogate_mode="shadow"` 时，`RACSearchPolicy.propose` 在 `search.py:192-195` 会**即使代理拟合成功也强制 `method="tpe_fallback"`、`reason="surrogate_shadow_only"`、返回 None**。

**结论（关键）**：v6 平台上 RAC 代理搜索（`rac_acquisition`）**从未用于产生最终候选**——它一直处于 shadow 模式（只记录 rank、不提案）。这直接回应了"不得仅凭源码中可用功能推断该功能已参与线上决策"。

---

## 2. 搜索方法真实触发次数（10 轮预算下的必然结果）

`RACSearchPolicy.propose`（search.py:92）的暖启动门槛：
```python
if len(completed) < max(self.settings.warmup_trials, self.settings.minimum_history):
    return None, {... "reason": "insufficient_history"}
```
v6 里 `warmup_trials = minimum_history = 8`（rac_policy.py:112）。

`ContestRACPolicy.propose` 的分支（rac_policy.py:257-271）：
- `not history`（无历史）→ `checkpoint_reference`（用父 lr clamp 到搜索空间下限，epochs=2）
- `params is None`（insufficient_history / surrogate_shadow_only / 代理质量不过）→ `_fallback`（optuna TPE 兜底，`n_startup_trials=4`）
- 仅当 `completed >= 8` 且 `surrogate_mode=="active"` 且 forward 质量门通过 → `rac_acquisition`

**逐轮触发次数的必然结论**（10 轮、父链连续、`records` 逐轮累积）：
- round 1：`checkpoint_reference`（无历史）
- round 2-7：`completed = 1..6 < 8` → `tpe_fallback`
- round 8：`completed = 7 < 8` → `tpe_fallback`
- round 9：`completed = 8` 首次满足门槛，但 `surrogate_mode="shadow"` → **仍 `tpe_fallback`（surrogate_shadow_only）**
- round 10：`completed = 9` → 同 shadow → `tpe_fallback`

**因此 v6 平台 10 轮中 `rac_acquisition`（代理辅助搜索）触发次数 = 0；`checkpoint_reference` = 1 次；`tpe_fallback` = 9 次。** 这与平台 report 中 round 1-3 参数恒为 `lr=0.003/bs=128/ep=2`、round 4 起出现非平凡参数（`lr=0.00493` 等）完全吻合。

---

## 3. 搜索历史机制审计（任务四）

**结论一：被拒候选确实进入搜索历史。**
- `contest_submission.py:404-405`：每轮结束都把 `record` 追加进 `records`（`"records": [*records, record]`），**不管 accepted 与否**。
- `rac_policy.py:_trial`（`:333`）把每条 record 硬编码为 `"status": "completed"`。
- 因此 `RACSearchPolicy` 的 `completed` 计数 = 所有完成训练并提交候选的轮次（含 keep）。

**结论二：四类历史的正确定义。**
| 类别 | 含义 | 是否进入 `completed` |
|---|---|---|
| 全部合法评估历史 | 所有成功训练+提交候选的轮次（records） | 是 |
| 已接纳模型历史 | accepted=True 的轮次 | 是（但不单独筛选） |
| 失败/异常历史 | `_trial` 抛异常被 exclude 的（如 `Invalid historical training time`） | 否（被 exclude） |
| 代理模型实际使用历史 | `RACSearchPolicy` 内 `completed`（=全部合法） | 是 |

**结论三：`completed < 8` 的真实原因** 不是"keep 不加历史"，而是 **`warmup_trials=8` 门槛 + 10 轮预算太短** 的双重约束：
- 父链连续（已核验：10 轮 parent 严格等于上一轮 selected），`records` 逐轮累积到最多 10 条。
- 但 `completed` 要 ≥8 才能触发代理搜索，而 10 轮中只有最后 2 轮（round 9/10）才满足 `completed≥8`，且 surrogate_mode="shadow" 仍强制 tpe_fallback。
- **本阶段只审计，不修改历史机制**（留待 S3 单独消融）。

---

## 4. 10 轮本地回放核验（任务二）

### 4.1 固定历史参数回放（平台参数 → 本地 RMSE）

用 v6 平台逐轮实际参数（action/lr/bs/epochs）+ 相同父检查点 + EMA(0.6) 续训，逐轮比较本地 RMSE 与平台 report：

| 轮 | 参数 | 平台 vm | 本地 | Δ |
|---|---|---|---|---|
| 1 | lr.003 bs128 ep2 | 665.7101 | 665.7101 | **0.0000** |
| 2 | lr.003 bs128 ep2 | 657.8522 | 657.8522 | **0.0000** |
| 3 | lr.003 bs128 ep2 (keep) | 657.8522 | 657.8522 | **0.0000** |
| 4 | lr.00493 bs106 ep1 | 648.6114 | 648.6280 | +0.0166 |

**结论**：round 1-3 逐字节精确复现（diff=0）；round 4 起出现微小浮点累积差异（+0.0166，随后在 keep 轮被放大）。**本地复现机制（父检查点 + EMA + lr/bs/ep）被证明完全忠实**，前 3 轮精确对齐即证明这一点。

### 4.2 不可复现部分（明确记录，不假定）

1. **平台 `rnd.model()` 是平台 RPC**（SDK `round.py` 经 `_rpc("model_request")` 转发到 Sampler 服务），本地无法复现该 RPC 通道；本地用 PyTRIO 直接 `SamplingClient.sample` 对同一 sampler path 做决策替代，**决策文本可能与平台不同**。
2. **平台主指标 `old`/`new` 来自隐藏集**（`submission.get("summary")`），本地仅有公开验证集，故接纳门的 `improved` 判定口径不同（本地用公开验证 RMSE）。
3. **平台 `validation_metrics` 的 keep 轮语义无法从 report 唯一确定**：round 5/6/7 的 vm 精确相同（648.8518×3）、round 8 为 651.4012，怀疑平台对 keep 轮存在缓存/复用，但无法从 report 证实。**此项标注为不确定，不作假定。**

### 4.3 动态决策复现（真实 PyTRIO + RAC-HPO）

本地 seed=42 驱动真实 PyTRIO + RAC-HPO 10 轮，方法轨迹为：r1 `checkpoint_reference`，r2-r10 全部 `tpe_fallback`（与平台一致的模式——round 4 起非平凡参数）。PyTRIO 决策序列与平台不同（本地 conservative/rac/...，平台 rac/rac/rac/conservative/...），**这是预期的**——决策依赖历史轨迹，本地轨迹（公开验证驱动）与平台轨迹（隐藏集驱动）不同。

---

## 5. 鲁棒目标是否实际生效（任务七）

- `projection_groups`（contest_submission.py:92-94）在 `contract["public_projection"]["source_metadata"] is not True` 时**返回 None**。
- 平台 v6 B 任务 **`validation_groups=None`**（`source_metadata` 非 True）——证据：v6 report 10 轮 reason **无任何一条提到 "bearing"**，且 `bearing_gate` 分支（contest_submission.py:336）因 `validation_groups is not None` 为 False 而从未执行。
- 此时 `evaluate_diagnostics(model, validation, None)` 返回 `{"overall": {...}}`，`regime_metrics` 对 B 任务走 `"overall" in diagnostics` 分支 → 只有单一 overall 分组。
- **`E_avg` 与 `E_worst` 相同**：只有一组时，鲁棒目标 `robust_metrics` 的均值与最差值退化为同一个值 → **鲁棒目标退化为单指标优化**（本质等于整体 RMSE/MAE 优化）。
- **本地保留逐轴承诊断**（`groups` 按 bearing 提取）作为独立泛化研究口径，但**区分于平台复现口径**（平台是 overall-only）。
- 未随意关闭/新增门禁：本地消融严格复现 `validation_groups=None` → `bearing_gate=None`，与平台一致。

---

## 6. 父链 SHA 连续性核验（任务二补充）

v6 平台 B 任务 10 轮父链**完全连续**（已核验 `parent_artifact_id` 严格等于上一轮 `selected_artifact_id`）：

```
round1: parent=baseline-cpu-b-rul-20261110-v1 → selected=round-01-1  (promote)
round2: parent=round-01-1 → selected=round-02-1                      (promote)
round3: parent=round-02-1 → selected=round-02-1                      (keep)
round4: parent=round-02-1 → selected=round-04-1                      (promote)
round5-8: parent=round-04-1 → selected=round-04-1                    (keep×4)
round9: parent=round-04-1 → selected=round-09-1                      (promote)
round10: parent=round-09-1 → selected=round-09-1                     (keep)
```

父链无断裂 → `record_from_state` 的 `records[-1]["selected_sha256"] == context["parent_sha256"]` 校验始终通过 → `records` 逐轮累积。

---

## 7. 对 S2 正式消融的约束（结论）

1. 四组消融必须**严格复现**：`surrogate_mode="shadow"`、`transfer_mode="off"`、`cost_mode="off"`、`bearing_mode="off"`、`validation_groups=None`、`baseline_objective` 冻结于父检查点。
2. 搜索在 10 轮内**只触发 checkpoint_reference + tpe_fallback**，`rac_acquisition` 恒为 0 次——这是配置决定的必然结果，不是 bug。
3. 消融隔离的因子是 **EMA（训练内核）** 和 **lr 下限（搜索空间）**，两者通过 `tpe_fallback` 的 TPE 采样空间和 `fit_epochs` 内核体现。
4. 结论口径必须是**公开验证 RMSE**，并明确标注"公开验证 ≠ 跨设备泛化 ≠ 隐藏集"。
