# RAC-HPO 提交说明（v5，2026-11-24）

## 本次变更

1. **训练与推理共用同一提示构造**：新增 `rac_hpo.contest.sampler.selection_payload`，
   线上 `contest_submission.py` 与训练脚本 `scripts/train_contest_sampler.py` 均调用它，
   消除「训练看一种 payload、线上看另一种 payload」的错位。
2. **决策策略重训**：v4 运行的 30 轮全部为 `conservative`（`rac` 0/30），导致三项指标与
   全无效回复的那次逐位相同。新 Sampler 用「反事实配对」样本训练：同一轮只翻转历史是否
   被接受，标签必须随之在 RAC / conservative 之间切换，合计 18:18 平衡、4 轮 72 步。
3. **两类可达守卫**：训练后自动检查留出集与 8 条历史翻转探针；若两类不同时出现，或
   「持续改善」历史不比「连续被拒」历史更偏向 RAC，训练直接判失败、不产出回执。

## 本地验证

- 竞赛核心测试 64 项（63 通过、1 跳过）；SDK 回调测试 21 项全通过。
- 留出任务 C：10/10 合法回复，动作分布 RAC 2 / conservative 8。
- 探针：历史全部改善 → 4/4 选 RAC；历史全部被拒 → 0/4 选 RAC（全部 conservative）。
- 训练记录：https://swanlab.cn/@2025040064/industrial-harness-sft/runs/ax998s81

## 镜像

- 归档 SHA-256：`e232d0ec2dcce7a018ad3246898b0bb9c470bde222096ea8fad792103fd692fc`
- 镜像 ID：`sha256:51de921fbb41c042437317756df9f35b4b9b1b94bf5c995df9d88c72b022d6f`
- 运行时源码 SHA-256：`contest_submission.py` `f14117ae…`、`stage3_controls.py` `d18a1d23…`、
  `sampler.py` `10470d42…`，三者与归档内 `app/source-files.json` 一致。

## 已知边界

本次仍为试运行，不计入正式成绩；隐藏测试与公开验证口径不同，公开验证分数不代表隐藏分数。
