# 选择合同 Sampler 重训与镜像重建说明（2026-11-24）

本次提交针对 2026-11-23 平台试运行 `e232566cb84833575df1f66981067679` 的 30/30 `conservative_invalid_response` 回退问题。

## 已确认证据

- 平台完整报告显示 11-23 运行 30 轮全部回退，汇总输出 token 恰好 3,840 = 30×128；11-18 运行为 29 无效 + 1 有效、3,754 token；11-17 运行为 27 `rac` + 3 `conservative`、90 token。
- 11-17 与 11-18/11-23 使用的 Sampler 身份不同：`ckpt_0a2nfnm0acy3` 与 `ckpt_vs1dihxehcgu`。后两次运行沿用同一旧 Sampler，但它的训练目标是超参数提案 JSON，而线上提示要求选择 JSON。
- 11-23 使用的 v3 镜像归档 `d8708751…` 大小为 150,218,752 字节，与本地解析器修复包等大；换镜像未换 Sampler，未消除回退。

## 本次修改

1. 统一训练与推理决策合同：训练 completion 改为 `{"selected_option","reason_codes","risk"}` 选择 JSON；提示模板、解析器、审计字段共用同一约定；非法回复仍走保守分支并给出机器可读原因码。
2. 重训 Sampler：20 条训练样本（A/B）、10 条留出样本（C），留出集 base 与 LoRA 均为 10/10 合法选择回复；SwanLab 记录见下方训练 URL。
3. 重建 linux/amd64 镜像归档：在已验证父镜像上叠加新的运行时源码，更新 `source-files.json`；归档 SHA-256 与镜像 ID 见构建验证记录。

## 边界

原始模型回复文本、逐轮 `finish_reason` 与逐次 token 仍未取得，因此根因仍属强假设；本次受控试运行用于验证新 Sampler 是否消除回退，不代表正式成绩或收益结论。

- 训练记录：https://swanlab.cn/@2025040064/industrial-harness-sft/runs/vcjb4v90
- 源码：https://github.com/2025040064/Industrial-RAC-HPO.git
