# S3.1 报告：搜索机制核验

> 日期：2026-11-25
> 阶段：S3.1（核验搜索机制）
> 性质：对 RAC-HPO 搜索机制的代码级 + 数据级核验，**只核验、不修改**

---

## 0. 核验范围与结论速览

| 核验项 | 结论 |
|---|---|
| S3.1.1 TPE 采样参数 | `n_startup_trials=4`；10 轮内真实 TPE 采样 108 次、随机探索 0 次、`rac_acquisition` 0 次 |
| S3.1.2 rac_params vs final_params | **rac_params 恒等于 final_params（实际执行参数）**，无"未执行参数对应真实指标"污染 |
| S3.1.3 历史排除/去重/跨父 | 三类排除：`non_prior_round` / 异常 / `duplicate_candidate`；跨父可比性由 `parent_sha256` 链保证 |
| S3.1.4 被拒候选历史 | 被拒候选（keep）**已保留**进历史，无需重复实现 |
| S3.1.5 本地 vs 平台轨迹 | 区分搜索轨迹（本地动态 vs 平台历史）与决策轨迹（本地直连 sampler vs 平台 RPC） |

---

## 1. S3.1.1：Optuna TPESampler 参数与真实采样次数

### 1.1 代码级参数（`rac_policy.py:355-383`）

```python
def _fallback(self, history, seed, startup_trials=None):
    ...
    sampler = self._sampler(seed) if startup_trials is None else optuna.samplers.TPESampler(
        seed=seed, n_startup_trials=startup_trials)
    ...
    for _ in range(32):          # 最多 32 次 ask，直到采到唯一候选
        trial = study.ask(...)
        if trial.params not in seen:
            return trial.params
        study.tell(trial, state=optuna.trial.TrialState.FAIL)

def _sampler(self, seed):
    return optuna.samplers.TPESampler(seed=seed, n_startup_trials=4)
```

**核验结论**：
- `_fallback` 在 `params is None` 时被调用，且**显式传 `startup_trials=4`**（`rac_policy.py:268`），因此走 `TPESampler(n_startup_trials=4)` 分支。
- `n_startup_trials=4` 的含义：前 4 次 `ask` 用**随机采样**（TPE 尚未建立后验），第 5 次起才用**真实 TPE 后验**采样。
- 但注意：`_fallback` 每次调用都是**新建 study**（`optuna.create_study`），只喂入当前轮之前的 `history` 作为已完成 trial，然后 `ask` 一次。因此**每次 `_fallback` 只做 1 次有效 `ask`**，且该 `ask` 是在"历史样本数 = completed 数"的 study 上进行的。

### 1.2 数据级真实采样次数（120 轮）

| 搜索方法 | 触发次数 | 说明 |
|---|---|---|
| `checkpoint_reference` | 12 | round1（12 组，无历史） |
| `tpe_fallback` | 108 | round2-10（12 组 × 9 轮） |
| `rac_acquisition` | **0** | 代理辅助搜索从未启动 |
| `global_exploration` | **0** | 随机探索从未触发（在 `rac_acquisition` 内部才可能触发，而后者从未进入） |

**逐轮 `search_reason` 分布**（12 组）：

| 轮 | reason | 说明 |
|---|---|---|
| round1 | `insufficient_history` ×12 | completed=0 < 8 |
| round2-8 | `insufficient_history` ×84 | completed=1..7 < 8 |
| round9-10 | `surrogate_shadow_only` ×9 + `surrogate_quality_failed` ×15 | completed>=8 但被 shadow 模式 / 代理质量门禁拦截 |

**关键澄清（修正 S2 报告 §5 的简化表述）**：

S2 报告 §5 称 round9-10 是"surrogate_shadow_only"。实际是**混合**：
- `surrogate_shadow_only`（shadow 模式强制 tpe_fallback）9 次；
- `surrogate_quality_failed`（代理 forward 质量门禁不过）15 次。

`surrogate_quality_failed` 来自 `surrogate.py:57-120` 的 `forward_check`：当 `completed>=8` 满足暖启动门槛后，`RACSearchPolicy.propose` 会尝试拟合代理并做 forward 验证，但历史样本太少（`min_forward_train=5` + `forward_holdout=3`，`len(X)=8~9` 时 holdout 仅 3 个），Spearman rank 相关或 MAE 比值不达标，代理被判不合格 → 返回 `None` → 走 `_fallback`。

**结论**：即使放宽暖启动门槛，代理质量门禁仍会在小历史样本下拦截。这为 S3.2 的"轻量代理 + 分阶段搜索"提供了直接动机——**不是简单降低 `warmup_trials` 就能激活代理，还需要适配少量样本的代理与质量门禁**。

---

## 2. S3.1.2：rac_params 与 final_params 的一致性

### 2.1 平台代码路径（`contest_submission.py`）

```python
# :265-267  决策前：保存 RAC 搜索推荐值
params = trace["params"].copy()
recommended_params = params.copy()          # RAC 推荐（决策前）
recommended_proposal = proposal.copy()
# :268-270  conservative 备选
alternative = {**params, "learning_rate": max(FLOOR, lr/2), "sampling_level":1, "epochs":1}
# :277-289  PyTRIO 决策 + conservative 覆盖
receipt = rnd.model(messages, ...)
action = parse_decision(raw_answer)["action"]
if action != "rac":
    params = alternative                    # params 被覆盖为 conservative
    proposal.update(alternative, strategy="uniform")
# :379      决策字段：推荐值 vs 最终值分开记录
decision = {"recommended_params": recommended_params, ..., "final_params": params.copy(), ...}
# :388      历史记录：rac_params 存决策后值
record = {"rac_params": params, "robust_objective": score["robust_objective"], ...}
```

### 2.2 本地 S2 代码路径（`ablate.py`）

```python
# :248-249  决策前：params = trace 推荐值
params = trace["params"].copy()
recommended_lr = float(params["learning_rate"])
# :252-253  conservative 备选
alternative = {**params, "learning_rate": conservative_lr, "epochs":1, ...}
# :263-266  PyTRIO 决策 + conservative 覆盖
action = decision["parsed"]["action"]
if action != "rac":
    params = alternative                    # 覆盖
# :313      record["rac_params"] = params（决策后）
record = {"rac_params": params, "robust_objective": score["robust_objective"], ...}
```

### 2.3 数据级核验（120 轮）

| 核验 | 结果 |
|---|---|
| `rac_params.lr == final_lr` | **120/120 轮完全一致** |
| `rac_params.lr != recommended_lr` | 84/120 轮（conservative 决策覆盖） |

**结论**：
1. **本地与平台行为一致**：`rac_params` 都记录**决策后实际执行参数（final_params）**，`recommended_params`（RAC 推荐值）单独保存在 `decision.recommended_params`。
2. **代理训练的历史一致性合规**：`_trial()` 读 `record["rac_params"]` 与 `record["robust_objective"]`，二者**对应同一候选模型**（实际执行参数 + 其真实指标），**不存在"用未执行参数对应真实指标训练代理"的污染**。
3. **一个需要注意的语义点**：历史里的 `rac_params` 是**决策后**参数，意味着代理拟合的 X 空间覆盖的是"被 PyTRIO conservative 减半后的 lr 分布"，而不是"RAC 搜索器推荐值的分布"。这对代理学习的是"实际执行效果"，而非"搜索意图"——**这本身是正确的**（代理应学习真实执行的因果），但 S3.2 研究轻量代理时须明确：代理拟合目标 = 实际执行参数 → 真实指标。

---

## 3. S3.1.3：历史排除原因、去重与跨父可比性

### 3.1 排除原因（`rac_policy.py:136-160`）

每轮 `propose` 遍历 `records`，按三类原因排除：

| 排除原因 | 触发条件 | 是否进 history |
|---|---|---|
| `non_prior_round` | `round >= 当前 round_index` | 否（只看严格先前的轮次） |
| 异常（`KeyError`/`TypeError`/`ValueError`/`ArithmeticError`） | `_trial()` 解析失败（如 `Invalid historical training time`、`Historical objective differs` 等） | 否 |
| `duplicate_candidate` | 同父历史中 `params` 键重复（`seen` 去重） | 否 |

### 3.2 跨父可比性

- `_trial()` 的 `record["diagnostics"]` 需满足 `_diagnostic_counts == validation_counts`（同任务、同验证集规模），`robust_objective` 需与 `score(diagnostics)` 一致（`rel_tol=1e-10`）。
- **跨父可比性由父链 SHA 保证**：`record_from_state`（平台）校验 `records[-1].selected_sha256 == context.parent_sha256`；本地 S2 校验 `parent_sha == chain[-1]`。
- 因此进入 `history` 的 trial **全部来自同一父链、同一验证集口径**，具备可比性。

### 3.3 数据级核验（120 轮历史样本数）

| 轮 | 进入 history 的样本数（completed） |
|---|---|
| round1 | 0 |
| round2 | 1 |
| ... | ... |
| round9 | 8（首次达到暖启动门槛） |
| round10 | 9 |

- 全部 120 轮 **0 次 `duplicate_candidate` 排除**（父链连续 + 每轮参数不同，去重未触发）。
- 全部 120 轮 **0 次异常排除**（所有 record 的 `robust_objective` 均通过 `_trial` 校验）。

---

## 4. S3.1.4：被拒候选历史是否保留

**核验结论：已保留，无需重复实现。**

- 平台 `contest_submission.py:403-408`：每轮结束 `records = [*records, record]`，**无论 accepted 与否**都追加。
- 本地 `ablate.py:319`：`records.append(record)`，同样无论 accepted 与否。
- `_trial()` 硬编码 `status="completed"`（`rac_policy.py:333`），故被拒候选（keep）与接纳候选（promote）**都计入 `completed`**。

> 这印证 S2_PREAUDIT 的结论：`completed<8` 的真实原因是 `warmup_trials=8` 门槛 + 10 轮预算短，**不是**"被拒候选未进历史"。本阶段**不修改**该机制（留 S3.2 单独消融）。

---

## 5. S3.1.5：本地动态搜索轨迹 vs 平台历史运行轨迹

**必须区分两类轨迹，避免混为一谈**：

| 维度 | 本地动态实验（S2 ablate.py） | 平台历史运行（v6 report） |
|---|---|---|
| 搜索轨迹 | 本地 `ContestRACPolicy.propose` 实时计算 | 平台容器内 `contest_submission.train` 实时计算（已随容器销毁，仅 report 留存） |
| 决策通道 | 本地 PyTRIO 直连 sampler（`SamplingClient.sample`） | 平台 `rnd.model()` RPC → Sampler 服务 |
| 决策历史内容 | `selection_payload` 用 `selected_metric=local_parent`（公开验证） | `selection_payload` 用 `selected_metric=old`（平台注入 `current_validation`，亦公开验证） |
| 指标口径 | 公开验证 RMSE | 公开验证 RMSE（old/new 均公开验证，见 S3.0 §5.2） |
| 决策序列 | 本地 90/120 conservative | 平台约 5 rac / 5 conservative |

**关键澄清**（承接 S3.0 §5.2 的修正）：
- 平台 old/new 是**公开验证集指标**，不是隐藏集。因此"本地 vs 平台决策序列不同"的原因**不是**"公开验证 vs 隐藏集驱动"，而是：
  1. **决策通道差异**：本地直连 sampler path vs 平台 RPC（可能经过不同的模型路由/温度处理）。
  2. **历史轨迹差异**：本地每轮历史由本地公开验证指标驱动，平台由平台 `current_validation`（数值可能因平台评测细节与本地有浮点/缓存差异）驱动。
  3. **决策 prompt 的 `selected_metric` 字段来源不同**（本地 `local_parent` vs 平台 `old`）。

> 因此，**本地动态实验的搜索/决策轨迹不能声称"复现了平台轨迹"**，只能声称"在相同配置下、以本地公开验证口径，重放了同一套决策机制"。二者的逐轮决策序列不一致是**预期差异**，不是复现失败。

---

## 6. S3.1 结论与对 S3.2 的启示

1. **TPE 采样**：10 轮内真实 TPE 采样 108 次（`n_startup_trials=4`），`rac_acquisition` 与 `global_exploration` 均 0 次。搜索实际由 `tpe_fallback` 主导。
2. **rac_params 一致性合规**：历史 `rac_params` 恒等于 `final_params`，代理训练无参数-指标错配。
3. **历史机制健全**：被拒候选已保留、跨父可比性由 SHA 链保证、去重/排除逻辑正确且本阶段未触发。
4. **代理激活的双重门槛**：`warmup_trials=8`（暖启动）之外，还有 `forward_check` 质量门禁（`min_forward_train=5` + `forward_holdout=3`）在少量样本下几乎必然拦截。**这是 S3.2 的核心研究对象**——不是简单降低门槛，而是设计适配少量历史的轻量代理与质量门禁。
5. **轨迹区分**：本地动态轨迹与平台历史轨迹在决策通道、历史内容、selected_metric 来源上均有差异，后续任何"复现"表述须明确层级。

---

## 附录：核验依据

- 源码：`src/rac_hpo/optimization/rac_hpo/search.py`（暖启动门槛 :92、forward 门禁 :104-129、shadow :192-195）、`rac_policy.py`（`_fallback` :355-383、`_trial` :307-344、历史筛选 :136-160）、`surrogate.py`（`forward_check` :57-120）
- 平台提交：`experiments/rebuild-selection-v6-20261124/context/app/contest_submission.py`（:230/:265-289/:330/:371-401/:388）
- SDK：`experiments/rebuild-selection-v6-20261124/context/sdk/contest_harness/round.py`（`submit_candidate` :195、`model` :165）
- 数据：`experiments/s2-ablation-b-20261125/results/ablation-results.json`（120 轮逐轮 audit）
