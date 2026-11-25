# 决策回复合同（Decision Contract）

版本：2026-11-24。本文件是提交镜像中「模型回复 → 解析 → 训练参数」的**唯一约定**。提示构造（`official_submission/contest_submission.py`）、解析器（`src/rac_hpo/contest/stage3_controls.py`）、采样与训练脚本（`src/rac_hpo/contest/sampler.py`、`scripts/train_contest_sampler.py`）必须以本文件为准；任何改动必须同步更新代码常量、测试与本文件。

## 1. 回执唯一允许的形式

### 形式 A：遗留选择（legacy）

- 原文经首尾空白剥离、去掉**恰好一个**末尾 `<|im_end|>` 后，必须精确等于 `RAC` 或 `conservative`（大小写不敏感）。
- 示例有效：`RAC`、` conservative `、`RAC<|im_end|>`、`CONSERVATIVE<|im_end|>`。

### 形式 B：结构化选择（json）

- 原文经同样归一化后必须是**单个 JSON 对象**，且字段集合**恰好**为：
  - `selected_option`：字符串，`RAC` 或 `conservative`（大小写不敏感）。
  - `reason_codes`：字符串数组，0–5 项，不得重复，每项只能取 `history`、`risk`、`constraint`、`cost`、`uncertainty`、`conservative`、`other`。
  - `risk`：字符串，只能取 `low`、`medium`、`high`、`unknown`。
- 示例有效：`{"selected_option":"RAC","reason_codes":["history","risk"],"risk":"low"}`。

**除此之外的一切形式都无效**，并回退到 `conservative_invalid_response`。

## 2. 明确禁止的形式（含原因码）

解析器拒绝时必须返回原因码 `reason`，写入审计，便于区分失败模式。

| 失败模式 | 示例 | 原因码 |
| --- | --- | --- |
| 超参数提案 JSON（**训练/推理不一致的主要来源**） | `{"learning_rate":0.001,"batch_size":128,"epochs":2,"strategy":"uniform","reason":"..."}` | `parameter_proposal_json` |
| 选择 JSON 混入额外字段 | `{"selected_option":"RAC","reason_codes":[],"risk":"low","learning_rate":0.1}` | `unexpected_fields` |
| 缺字段 | `{"selected_option":"RAC"}` | `missing_fields` |
| 选项非法 | `{"selected_option":"other",...}` | `unknown_option` |
| 风险等级非法 | `{"risk":"bad",...}` | `invalid_risk` |
| 理由码非法或重复 | `{"reason_codes":["history","history"],...}` | `invalid_reason_codes` |
| fenced code 包裹 | ` ```json {"selected_option":"RAC",...} ``` ` | `fenced_json` |
| JSON 截断 | `{"selected_option":"RAC","reason_codes":` | `truncated_json` |
| 未知结束标记 | `RAC<\|unknown\|>` | `invalid_terminal_marker` |
| 重复结束标记 | `RAC<\|im_end\|><\|im_end\|>` | `extra_content` |
| 标记后附加正文 | `RAC<\|im_end\|>extra` | `extra_content` |
| 非 JSON 任意文本 | `bad` | `not_json` |

## 3. 结束标记与长度

- 生产解析器只识别 `<|im_end|>`，且只允许**一次**，必须位于末尾；`strip()` 后统一处理。
- tokenizer 的 `skip_special_tokens=True` 解码路径只能用于诊断/审计，**不得**作为生产解析的替代路径。
- 采样请求的 `max_tokens` 与 `stop` 必须被记录；`finish_reason=length` 单独记为 `truncated_json`/`truncated_text`，不得与内容不合规混为一谈。
- 平台汇总 token 恰好等于轮数 × `max_tokens` 只能作为检查线索，不构成截断证据；需要逐次 token 与 `finish_reason`。

## 4. 训练合同（必须统一）

1. 训练样本的 completion **必须**是本合同第 1 节的形式 B（或形式 A），不得使用从 `round_result["proposal"]` 生成的超参数 JSON。
2. `src/rac_hpo/contest/sampler.py` 的 `SELECTION_SYSTEM` / `selection_messages` / `parse_selection_reply` 是本合同的编程实现；旧 `SYSTEM` / `decision_messages` / `parse_action` 仅保留给本地 CLI 与显式 `--legacy-params` 路径，不得用于新 Sampler 训练。
3. `scripts/train_contest_sampler.py` 默认按本合同生成标签：历史轮次 `accepted=True` → `selected_option=RAC`、`risk=low`；`accepted=False` → `selected_option=conservative`、`risk=medium`；`reason_codes=["history"]`。参数提案 JSON 只作为历史决策的**证据**，不能作为模型输出目标。
4. 参数提案 JSON 不得以任何宽松匹配转成 `rac`/`conservative`；否则训练与推理会继续错位。
5. 2026-11-24 已用新合同 dry-run：A/B 训练样本 20 条（含接受与拒绝）、C 留出 10 条；旧合同仅有 4 条训练、1 条留出。样本仍需在重训前核对标签质量与覆盖面。
6. **v5（2026-11-24 14:00）起，提示载荷只有一处实现**：`sampler.selection_payload(context)`。训练脚本与 `contest_submission.py` 都调用它，运行时发送 `[system, user]` 两条消息，user 内容即该载荷。禁止在任一侧另写字段集合——这正是 v4 塌缩的隐藏原因之一。
7. **标签必须配对**：每轮额外生成一条「翻转历史」样本（同一轮、同一参数，只把 `accepted` 与指标轨迹取反），标签随之互换；首轮无历史样本不参与训练。除非显式 `--legacy-params`，训练完成后必须通过「两类可达」守卫（留出集 + 历史翻转探针同时出现 RAC 与 conservative，且改善历史更偏 RAC），否则不得提交。
6. 重训属于计费操作，必须单独获得授权；当前代码已改，**但尚未重训，也尚未上传新 Sampler 或镜像**。

## 5. 代码事实源对应关系

- 枚举与解析：`src/rac_hpo/contest/stage3_controls.py` 的 `SELECT_OPTIONS`、`REASON_CODES`、`RISK_LEVELS`、`ALLOWED_TERMINATORS` 与 `parse_decision`。
- 提示构造：`official_submission/contest_submission.py` 的 `prompt_payload["request"]`。
- 采样与训练：`src/rac_hpo/contest/sampler.py` 的 `SELECTION_SYSTEM` / `selection_messages` / `parse_selection_reply`（新合同）与 `SYSTEM` / `decision_messages` / `parse_action`（旧参数提案路径）；`scripts/train_contest_sampler.py` 的 `selection_label` 与 completion 生成。
- 测试：`tests/contest/test_stage3_controls.py`、`official_submission/tests/test_sdk_callbacks.py`。

若上述代码与本文件冲突，以本文件为准并立即修正代码；不得反过来用代码行为改写本文件。
