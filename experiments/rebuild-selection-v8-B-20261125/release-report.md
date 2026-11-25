# v8-B 候选发布报告

> 日期：2026-11-25
> 路线：独立候选 v8-B（B 任务 EMA 关闭，对应 S2 G2 策略）
> 性质：与 S3.2 代理机制研究并行，互不阻断

---

## 1. 变更内容

**唯一代码改动**：`app/rac_hpo/contest/continuation.py` 第 54 行。

```python
# v6 原逻辑（B/C 回归任务都走 EMA）：
averaged = model.meta["task"] == "regression"

# v8-B 改动（仅关闭 B 任务 EMA，C 保留）：
averaged = model.meta["task"] == "regression" and model.meta["profile"] != "B"
```

**保持不变**（与 v6 逐字节一致，已核验 SHA）：
- A/C 任务的训练内核、lr 下限 3e-3（`rac_policy.py`）、搜索算法、代理模式（`surrogate_mode="shadow"`）、PyTRIO Sampler、候选接纳机制、父链维护（`contest_submission.py`）——全部不变。
- 仅 `continuation.py` 一个文件变化，其余 4 个运行时文件（`rac_policy.py`、`contest_submission.py`、`sampler.py`、`stage3_controls.py`）SHA 与 v6 完全一致。

## 2. 训练侧改动依据：G2 vs G3 严格等 CPU 预算对照

| 指标 | G2（EMA off） | G3（EMA on，v6 现状） |
|---|---|---|
| 最终 RMSE（5 种子均值 ± 样本 sd） | **630.28 ± 7.62** | 653.44 ± 6.33 |
| 配对差值 G2−G3（5 种子） | **−23.16**（−20.23/−25.10/−21.95/−27.94/−20.57） | — |
| 95% CI（df=4，t=2.776） | **[−27.24, −19.07]，不跨零** | — |
| 算法 CPU（search+train+val，5 种子均值） | 0.329s | 0.341s |
| 算法 CPU 比值 G3/G2 | 1.035（**几乎相同，等预算成立**） | — |

**结论**：
1. G2 在公开验证口径下 5 个种子**一致且显著**优于 G3（差 −23.16，CI 不跨零），比 S2 的 3 种子结果（−22.43）更强。
2. 两者算法 CPU 几乎相同（比值 1.035），证明**等轮数 ≈ 等 CPU 预算**在本地口径下成立，G2 的收益**不是靠消耗更多 CPU 换来**。
3. 搜索种子：42 / 2024 / 7 / 11 / 99（训练种子保持父检查点 42 不变）。

> **边界声明**：以上是**公开验证集 RMSE**口径，与隐藏集收益不可混（S1/S2 已证伪其传导性）。v8-B 的隐藏集收益只能在平台试运行时观测，公开验证收益不能保证传导到隐藏集。

## 3. 回归测试与父链验证

### 3.1 A/B/C 三任务行为核验

| 任务 | v6 行为 | v8-B 行为 | 结论 |
|---|---|---|---|
| A（classification） | 无 EMA（w=1.0000） | 无 EMA（w=1.0000） | 一致，不受影响 |
| B（regression） | EMA 平均（w=1.0400） | 直接累加（w=1.0000） | **改动生效（EMA 关闭）** |
| C（regression） | EMA 平均（w=1.0400） | EMA 平均（w=1.0400） | 一致，不受影响 |

- 用 FakeModel（task+profile 组合）+ 真实 C 任务 checkpoint（`训练集/cpu-c-guide-20261110-v1/checkpoint.npz`，profile='C'）双重验证。
- C 任务真实续训通过（EMA 路径），权重单 epoch 变化符合 EMA 衰减。

### 3.2 竞赛测试套件

- 68 项测试（67 通过 + 1 跳过），与 v6 提交说明一致。

### 3.3 父链验证

- 父链维护逻辑在 `contest_submission.py`（**未改动**），v6 已验证父链 10 轮连续。
- v8-B 只改训练内核的 EMA 分支，不影响父链 SHA 传递、六门验收、Checkpoint 保护机制。

## 4. 镜像构建

| 项 | 值 |
|---|---|
| 镜像 tag | `industrial-rac-hpo:selection-v8-B-20261125` |
| **镜像 ID** | `sha256:bec89fcfb75ac7ac6a06dcc0caf97694badd8181b6e8c81af68cee123a82a0e7` |
| 父镜像 ID | `sha256:877248e2e7bb98757748b0cf2ab51817cf71605cb554438f4fcc9b69b77b9a38`（= v6） |
| **归档 SHA-256** | `965092bde0b090ba0dbdd487921c6359b9e15bfc4d89a3cd6194124e46950f9d` |
| 归档字节 | 150,343,680（143.38 MiB） |
| overlay layer SHA | `sha256:e69d97c224a20e9aa02a04f8fa95d19b8d53f2250a39404ec0b3c6770038b34c` |
| 平台 | linux/amd64 |
| Sampler | `trio://run_1fei9lfkoj70/sampler_weights/industrial-harness-lora-selection-v3-20261124`（沿用 v6，未改动） |

**运行时文件 SHA 核验**（归档内 `app/source-files.json` 与 context 一致）：

| 文件 | v8-B SHA | 与 v6 对比 |
|---|---|---|
| continuation.py | `0f7f4b8c...` | **变化（唯一改动）** |
| rac_policy.py | `896b763a...` | 一致 |
| contest_submission.py | `333aeed4...` | 一致 |
| sampler.py | `10470d42...` | 一致 |
| stage3_controls.py | `d18a1d23...` | 一致 |

## 5. 合规审计

- ✅ 不改变平台锁定模型架构（B 任务 34→24→1 / 865 参数）。
- ✅ 不加工训练标签，不打包违规离线拟合产物。
- ✅ 不使用隐藏集调参（本报告所有结论基于公开验证）。
- ✅ 不修改冻结基线（`baseline-v6-20261125` tag 未动）。
- ✅ 不自动 push、不自动提交平台。
- ✅ 不消耗正式评测机会（本路线仅准备镜像，未提交）。
- ✅ 保留 v6 作为安全回退版本。
- ✅ 依赖不变（`requirements-contest.txt` 未改，无新增依赖）。

## 6. 平台试运行机会确认

从 `experiments/platform-runs/platform-rules.json` 确认：

| 项 | 值 |
|---|---|
| 试运行（trial） | `trial_enabled: true`，**剩余 7 次**（limit 10，used 3） |
| 正式评测 | 剩余 3 次（limit 3，used 0） |

**结论**：平台存在**不占用正式评测的试运行（trial）机会**，剩余 7 次。v8-B 可走 trial 模式验证隐藏集收益，不消耗 3 次正式评测。v6 即通过 trial 模式运行（`82522846`）。

## 7. 待用户决策

- 是否将 v8-B 镜像**上传并提交平台 trial 试运行**（不占用正式评测）？
- 本报告完成后**不自动提交**，由用户决定。

---

## 附录：文件清单

- 构建脚本：`experiments/rebuild-selection-v8-B-20261125/rebuild.py`
- 构建 context：`experiments/rebuild-selection-v8-B-20261125/context/`
- 镜像归档：`experiments/rebuild-selection-v8-B-20261125/harness-selection-v8-B.tar`
- 构建校验：`experiments/rebuild-selection-v8-B-20261125/build-validation.json`
- 等预算对照脚本：`experiments/v8-B-equal-budget-20261125/equal_budget.py`
- 等预算结果：`experiments/v8-B-equal-budget-20261125/results/ablation-results.json`
- Git 分支：`candidate/v8-B`（从 `baseline-v6-20261125` 创建）
