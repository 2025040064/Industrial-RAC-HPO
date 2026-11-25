# RAC-HPO 提交说明（v8-B，2026-11-25）

## 本次变更

仅关闭 B 任务的 EMA 平均（对应 S2 消融的 G2 策略：EMA off + lr 下限 3e-3），
A、C 任务及所有其他搜索算法、代理模式、PyTRIO Sampler、候选接纳机制均保持 v6 不变。

1. **关闭 B 任务 EMA**（`rac_hpo/contest/continuation.py`）。
   - `fit_epochs` 中 `averaged` 条件由 `task == "regression"` 改为
     `task == "regression" and profile != "B"`。
   - 效果：B 任务走 `model.fit`（无 EMA 平均），C 任务仍走 `_fit_averaged`（保留 EMA），
     A 任务（分类）本就不走 EMA，三者行为与 v6 相比仅 B 改变。
   - 其余 4 个运行时文件（contest_submission.py、rac_policy.py、sampler.py、
     stage3_controls.py）与 v6 逐字节一致，lr 下限 3e-3 保留。

## 实验依据（严格等 CPU 预算对照，5 搜索种子 42/2024/7/11/99）

- G2（EMA off + lr 3e-3）= 630.28 ± 7.62；G3（EMA on + lr 3e-3，即 v6 现状）= 653.44 ± 6.33。
- 配对差值 −23.16，95% CI [−27.24, −19.07]，不跨零（5 种子方向全部一致为负）。
- 两者算法 CPU 比值 1.035，等预算成立（收益非来自额外 CPU）。

## 已知边界与诚实声明

- 收益口径为**公开验证集 RMSE**；公开验证改善**不保证**传导到隐藏集。
- v6 的 B 隐藏集 −25.7% 收益，其来源尚未定位，可能正与 EMA 相关；关闭 B 的 EMA
  存在隐藏集反而不如 v6 的风险。本提交用于正式评测验证该方向，风险已知。

## 镜像

- 镜像 ID：`sha256:bec89fcfb75ac7ac6a06dcc0caf97694badd8181b6e8c81af68cee123a82a0e7`
- 父镜像：`sha256:877248e2e7bb98757748b0cf2ab51817cf71605cb554438f4fcc9b69b77b9a38`（v6）
- 归档 SHA-256：`965092bde0b090ba0dbdd487921c6359b9e15bfc4d89a3cd6194124e46950f9d`
- 归档字节：150,343,680（143.38 MiB）
- 唯一改动文件 `continuation.py` SHA-256：`0f7f4b8c8e6181b3526e4f5ca4a7be69401245e742cf221ee3903ecd49e6b72d`

## 回归测试

- 竞赛测试 69 项（68 通过、1 跳过），含新增「B 任务关闭 EMA」测试。
- A/B/C 三任务行为核验：A/C 与 v6 完全一致，仅 B 关闭 EMA。
