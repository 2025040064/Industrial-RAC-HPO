# RAC-HPO 基线审计（S0）

> 日期：2026-11-25
> 阶段：S0（规则、v6 基线及 v7 残留审计）
> 性质：可追溯审计记录，非实验报告

---

## 1. 审计结论摘要

| 事项 | 结论 |
|---|---|
| v6 镜像身份 | 完整可追溯（见 §2） |
| v7 软标签残留 | 已清理，4/5 核心文件与 v6 一致 |
| 代码与镜像一致性 | **发现 1 处不一致**：`rac_policy.py` 含未入镜像的 epochs 下限改动（见 §3） |
| Git 提交锚点 | **缺失**：v6 无独立 git 提交，需补冻结（见 §4） |
| 官方规则 | 从 `RAC-HPO_项目文档总汇.md` 原文 001/002 恢复（见 §5） |

---

## 2. v6 镜像身份（冻结）

| 字段 | 值 |
|---|---|
| image_tag | `industrial-rac-hpo:selection-v6-20261124` |
| image_id | `sha256:877248e2e7bb98757748b0cf2ab51817cf71605cb554438f4fcc9b69b77b9a38` |
| parent_image_id（v5） | `sha256:51de921fbb41c042437317756df9f35b4b9b1b94bf5c995df9d88c72b022d6f5` |
| archive_sha256 | `b7526832252200c13b6f98829a3309d1e7bf77e1dbecb115ed245aef05f57a67` |
| archive_bytes | 150,312,960 |
| overlay_layer_sha256 | `sha256:c81edaabc4df355e38fd658952038ca72442e97adc36056e1c838ae251cf3067` |
| sampler_path | `trio://run_1fei9lfkoj70/sampler_weights/industrial-harness-lora-selection-v3-20261124` |
| training_record_url | `https://swanlab.cn/@2025040064/industrial-harness-sft/runs/ax998s81` |
| 平台运行 ID | `82522846a0d57928a16292b2c4ad183a`（trial，completed） |

v6 平台实测（隐藏集，从 `/runs/{id}/report` 的 `report.workspace_report.datasets` 提取）：

| 任务 | 指标 | v5 → v6 |
|---|---|---|
| A | macro_f1 | 0.860822 → 0.860822（持平） |
| B | mae / rmse | 455.50 / 654.00 → **353.81 / 486.08（−25.7%）** |
| C | mae / rmse | 41.176 / 56.320 → 41.508 / 56.522（+0.36% / +0.81% 退步） |

v6 变更内容（notes）：`epoch-averaged continuation + regression learning-rate floor`，即：
1. `continuation.py`：`fit_epochs` 对回归任务做 epoch 末权重 EMA（`EMA_DECAY=0.6`）。
2. `rac_policy.py`：回归任务学习率下限 `REGRESSION_LEARNING_RATE_LOW = 3e-3`。

---

## 3. 代码与镜像一致性核验

逐文件 `diff` 当前 `src/` / `official_submission/` 与 v6 镜像 `context/app/`：

| 文件 | 与 v6 镜像 | 说明 |
|---|---|---|
| `official_submission/contest_submission.py` | 一致 | v7 软标签已移除 |
| `src/rac_hpo/contest/continuation.py` | 一致 | EMA_DECAY 已恢复 0.6 |
| `src/rac_hpo/contest/sampler.py` | 一致 | — |
| `src/rac_hpo/contest/stage3_controls.py` | 一致 | — |
| `src/rac_hpo/contest/rac_policy.py` | **不一致** | 见下 |

### 3.1 `rac_policy.py` 的不一致（未入任何镜像）

当前源码比 v6 镜像多出：

```python
REGRESSION_EPOCHS_LOW = 4   # 回归任务 epochs 下限 1 → 4
...
"epochs": {"type": "int", "low": 1 if task == "A" else REGRESSION_EPOCHS_LOW, "high": 5},
```

v6 镜像里 `epochs` 的 low 恒为 1。这个改动产生于 v6 提交后的本地 epochs 迭代，**从未构建进任何提交镜像**。

**影响**：本地当前源码与 v6 平台实测代码在 epochs 搜索空间上不一致。任何后续消融必须以 v6 镜像实际代码（epochs low=1）为基准，或在明确记录差异的前提下重新验证。

---

## 4. Git 状态与冻结（已完成，2026-11-25）

### 4.1 完整可复现性核验结论（逐字节 SHA 比对）

对 v6 镜像 `build-validation.json` 内 `source_files` 记录的**全部 21 个核心源码文件**逐一重算 SHA-256 并与工作区对应文件比对，结果：**21/21 一致，0 不一致**。

| 范围 | 文件数 | 核验结果 |
|---|---|---|
| `src/rac_hpo/contest/`（continuation/rac_policy/sampler/stage3_controls/policy/packages/bearing_feasibility/surrogate_evidence/transfer_gate/__init__） | 10 | ✅ 全一致 |
| `src/rac_hpo/domain/`、`src/rac_hpo/optimization/`、`src/rac_hpo/__init__.py`、`_io.py` | 10 | ✅ 全一致 |
| `official_submission/contest_submission.py` | 1 | ✅ 一致 |

**不属于本次源码改动、无需冻结的**（平台提供模板/SDK/许可，非我们改动）：
- `app/baselines/{model,data,__init__}.py`、`app/harness.py`：平台提供 baselines 模板，权威源在 `workspace/verification/submission-optimization.d4qVhmUe/release/context/` 与 `训练集/cpu-a-guide-20261110-v1/baselines/`，两者 SHA 与镜像内一致。
- `app/RAC-HPO-LICENSE`、`Dockerfile`、`requirements.lock`、`sdk/contest_harness/*`：平台 SDK 与锁定依赖。

### 4.2 v6 从未有干净 git 提交（关键历史事实）

- v6 `source-files.json` 记录的 `git_head = e62f58e7082ede8bfc636c3361580c50dc0d44e9`，但该 commit 上的核心文件 blob SHA 与 v6 镜像**完全不同**（`contest_submission.py` 为 `b5a35c1e` 而镜像为 `333aeed4`；`stage3_controls.py` 在该 commit 上甚至不存在）。
- 结论：**v6 镜像打包时 `git_head` 字段陈旧，真实源码是当时未提交的工作区状态**。v6 的权威源码身份只存在于 `experiments/rebuild-selection-v6-20261124/context/` 与 tar 归档中，git 层面无对应提交。
- 因此必须**新建 `baseline-v6` 提交 + tag** 作为可复现锚点。

### 4.3 冻结范围（最小化，已执行）

**纳入 baseline-v6 提交的（v6 核心源码 + 配套测试 + 审计）：**

- 核心源码（与 v6 镜像逐字节一致，5 文件 + 决策合同重构 5 文件）：
  `official_submission/contest_submission.py`、`src/rac_hpo/contest/continuation.py`、`rac_policy.py`、`sampler.py`、`stage3_controls.py`、`policy.py`、`packages.py`、`bearing_feasibility.py`、`surrogate_evidence.py`、`transfer_gate.py`
- 配套测试（v6 决策合同/lr 下限/EMA 配套）：
  `tests/contest/test_contest_sampler.py`、`test_rac_history.py`、`test_stage3_controls.py`、`test_continuation_ema.py`、`official_submission/tests/test_sdk_callbacks.py`
- 采样器训练脚本（决策合同重构配套）：`scripts/train_contest_sampler.py`
- 审计文档：`docs/RAC_HPO_BASELINE_AUDIT.md`、`docs/RAC_HPO_CALLCHAIN_AUDIT.md`
- `.gitignore`（新增 `.venv-temporal` 排除，防止时序环境被误提交）

**明确排除（时序/路线A 产物、数据、密钥、无关文件）：**
- 时序源码：`src/rac_hpo/data/temporal_window.py`、`temporal_features.py`、`src/rac_hpo/training/tcn_trainer.py`、`tests/test_tcn_smoke.py`、`tests/test_temporal_features.py`
- 数据与实验产物：`datasets/`、`experiments/`（含全部 rebuild-*、local-ab-*、platform-runs）
- 文档与密钥：`*.docx`、`RAC-HPO_问题解决与验证方案.md`、`RAC-HPO_项目文档总汇.md`、`项目现状报告-*.md`、`harness.tar`、`.venv*`

### 4.4 epochs 下限处置（决策 1A）

- **当前 `rac_policy.py` 的 `epochs low = 1`**（与 v6 镜像一致），已保留。
- **`REGRESSION_EPOCHS_LOW = 4`（epochs 下限 1→4）为 S3 待验证候选**，仅记录不启用，代码中无残留（全文 grep 确认）。
- 该候选的潜在影响在 S2 消融后、进入 S3 搜索空间扩展时再评估，不得在 S2 前启用。

---

## 5. 官方规则要点（从仓库文档恢复）

来源：`RAC-HPO_项目文档总汇.md` 原文 001（AGENTS.md / RAC-HPO 工程规则）、原文 002（ARCHITECTURE.md 竞赛记录）。

- 训练与搜索只用 train / validation；显式最终评估才读 test。
- 工况由**推理前可获得的元数据**定义，不得用未来/身份字段。
- 代理树离散度与前向残差重采样仅作**未校准的搜索近似**；最终 J 固定，代理不合格明确回退 TPE。
- 竞赛 SDK 开关：`RAC_TRANSFER_MODE=off|legacy|gated`、`RAC_SURROGATE_MODE=off|shadow|active`、`RAC_COST_MODE=off|transfer|acquisition|both`、`RAC_BEARING_FEASIBILITY=off|shadow|active`，默认 off/shadow/off/off。
- 跨父历史默认关闭（`RAC_TRANSFER_HISTORY=0`），显式开启才用相对 J 暖启动；历史实验未支持该方案。
- 候选接纳：平台主指标严格改善 + 固定 J + B 逐轴承门槛同时生效；父/候选平台主指标须与本地重算在相对 `1e-7`/绝对 `1e-8` 内一致。
- 父链：连续轮次宿主父摘要与上一轮选中摘要一致，否则停止本轮。
- 依赖锁定：`requirements-contest.txt` = numpy 1.26.4 / optuna 4.5.0 / scikit-learn 1.7.2 / scipy 1.16.3；不可改。

---

## 6. 可复现项 / 无法复现项

| 可复现 | 说明 |
|---|---|
| v6 镜像与归档 | tar 文件在 `experiments/rebuild-selection-v6-20261124/harness-selection-v6.tar`，SHA 见 §2 |
| v6 平台报告 | `experiments/platform-runs/82522846a0d57928a16292b2c4ad183a-report.json` |
| v6 逐轮审计 | 平台报告内 `report.workspace_report.datasets[].rounds`（需 S1 提取核对） |

| 无法复现 / 待核验 | 说明 |
|---|---|
| v6 完整逐轮训练日志 | 需从平台 report 的 rounds 字段提取，尚未逐轮核对 |
| git 提交锚点 | 缺失，见 §4 |
| `rac_policy.py` epochs 下限 | 与镜像不一致，待定版本 |

---

## 7. 下一步（进入 S1）

1. 与用户确认 `rac_policy.py` 的冻结版本（回退 epochs low=1 或保留 4）。
2. 建立 v6 基线 git tag。
3. S1：输出真实调用链、父链、验证数据协议，提取 v6 平台逐轮日志。
