# 平台试运行证据台账

建立日期：2026-11-24。用途：把平台试运行的**展示值、完整报告与可核验回执**分开记录，避免不同日期的截图被合并成同一运行的结论。

## 填写规则

1. 字段缺失一律写 `unknown`，**不得**用时间接近、归档大小相近或本地回放结果推断填充。
2. 每次运行独立一行；不同运行的轮次编号不得互相引用或合并。
3. 报告文件只证明报告内字段；原始模型回复、`finish_reason`、逐次 token 未入库前，不得把「回退根因」写成已确认。
4. 本台账只追加，不覆盖历史行；更正用新行并注明更正原因。

## 固定字段

`运行ID | 日期时间 | 镜像ID | 归档SHA-256 | Sampler版本 | 原始回执路径 | 逐轮finish_reason | 逐次token | 决策分支计数 | 采用轮次 | 结论状态`

## 平台元数据（2026-11-24 经 Safari 登录态只读取得）

来源：平台 API `/api/v1/runs`、`/api/v1/runs/<id>/report`、`/api/v1/submissions`、`/api/v1/image-archives`。存档文件：

- `platform-submissions.json`
- `platform-image-archives.json`
- `{f71ad4f459a130095c627bfe34018cba,893a9207497b2b184ca6dafefbdcbcb1,cd90fe2cbad1e6879d6191d6eb5e6858,e232566cb84833575df1f66981067679}-report.json`

| 提交版本 | submission_id | image_archive_id | 归档大小（字节） | 模型指针 | 对应运行 |
| --- | --- | --- | --- | --- | --- |
| v1 | `06cde0d286688bd7d6b7823ce6801959` | `1cbe47e47e3f7c7bd640b7110d3c1ee6` | 150,192,128 | `trio://run_5gztncfv7ijs/sampler_weights/rac-hpo-lora-v2` | `f71ad4f4…`（11-17） |
| v2 | `0627ffb02bea019ce27a012b5e81a9bd` | `428bde81fdd8d5757c8c9ed4323925d6` | 150,210,048 | `trio://run_2wehwhow3d8t/sampler_weights/rac-hpo-lora-20261117` | `cd90fe2c…`（11-18 18:27Z）及可行性试运行 |
| v3 | `9dbc2b977ebcd3aa76c76f13fa988d7f` | `d8708751a35df2a8aedb594c7b29eae5` | 150,218,752 | `trio://run_2wehwhow3d8t/sampler_weights/rac-hpo-lora-20261117` | `e232566c…`（11-23 08:17） |
| v4 | `e601e62637960a06a30dbc1d8c2dfd8a` | `3eebd66f7541ab707ea56c0b3d00eaf6` | 150,251,520 | `trio://run_p9j56scwclzo/sampler_weights/industrial-harness-lora-selection-20261124` | `d084054c…`（11-24 受控复验，已完成） |
| v5 | `1407e09bf46aa798f23fde44fa77ba4e` | `b982d566db383214c174b8ceab66bb9c` | 150,272,000 | `trio://run_1fei9lfkoj70/sampler_weights/industrial-harness-lora-selection-v3-20261124` | `3bf441ab…`（11-24 第二次受控复验，已完成：两类可达） |
| v6 | `07d126ada6e9ef1d2733ceda0036edf2` | `730e2392439ba35765e43a049eaeb137` | 150,312,960 | `trio://run_1fei9lfkoj70/sampler_weights/industrial-harness-lora-selection-v3-20261124` | `82522846…`（11-24 训练侧优化试运行） |

**关键更正**：旧稿把 `428bde81…` 写成 11-23 镜像；实际它是 v2/11-18 镜像。11-23 使用的 v3 镜像是 `d8708751…`，其大小与本地修复包 `experiments/pytrio-diagnostics-20261122-02/harness-parser-fix.tar`（SHA `6b00156891e086784da163efc317687b22672c941ab3dfe31d03a094de0df414`）**完全一致**。平台 API 不返回归档 SHA-256，因此只能记为大小级关联，不能写成字节级一致。

## 已登记运行

### R-20261117（v1，Sampler 工作正常）

- 运行ID：`f71ad4f459a130095c627bfe34018cba`
- 日期时间：2026-11-17T15:25:42Z（北京时间 11-17 23:25）
- 提交/镜像：v1 `06cde0d2…` / `1cbe47e4…`
- 镜像归档SHA-256：`unknown`
- Sampler版本：`sampler:ckpt_0a2nfnm0acy3`
- 原始回执路径：`f71ad4f459a130095c627bfe34018cba-report.json`（完整报告，不含原始模型文本）
- 逐轮 `finish_reason`：`unknown`；逐次 token：`unknown`；汇总输出 token 90 = 30×3
- 决策分支计数：A/B/C 各 10 轮：`rac` 27、`conservative` 3、无效 0
- 采用轮次：A 第 9 轮 / B 第 2 轮 / C 第 10 轮（报告中最后 `promote`）
- 隐藏测试展示值：A Accuracy 0.865330 / Macro-F1 0.860822；B MAE 505.104177 分钟 / RMSE 712.417220 分钟；C MAE 40.700931 循环 / RMSE 56.120468 循环
- 结论状态：`平台报告已核验；根因回执仍缺`

### R-20261118-feasibility（v2，可行性试运行）

- 运行ID：`893a9207497b2b184ca6dafefbdcbcb1`
- 日期时间：2026-11-18T12:53:00Z（北京时间 11-18 20:53）
- 提交/镜像：v2 `0627ffb0…` / `428bde81…`
- 报告内容：只有 `status` 与 `steps`，`model_identity` / `costs` / workspace rounds 均不存在
- 结论状态：`已存档；不产生选模或回退结论`

### R-20261118-late（v2，29 无效 + 1 有效）

- 运行ID：`cd90fe2cbad1e6879d6191d6eb5e6858`
- 日期时间：2026-11-18T18:27:21Z（北京时间 11-19 02:27）
- 提交/镜像：v2 `0627ffb0…` / `428bde81…`
- 镜像归档SHA-256：`unknown`
- Sampler版本：`sampler:ckpt_vs1dihxehcgu`
- 原始回执路径：`cd90fe2cbad1e6879d6191d6eb5e6858-report.json`
- 逐轮 `finish_reason`：`unknown`；逐次 token：`unknown`；汇总输出 token 3,754（≈29×128 + 42，推断未证实）
- 决策分支计数：无效 29、`conservative` 1、`rac` 0
- 采用轮次：A 第 8 轮 / B 第 4 轮 / C 第 6 轮
- 隐藏测试展示值：与 R-20261123 相同（A 0.731273 / 0.661861；B MAE 496.277472 / RMSE 718.078290；C MAE 41.185423 / RMSE 56.290969）
- 结论状态：`平台报告已核验；根因回执仍缺`

### R-20261123（v3，最新试运行，08:17）

- 运行ID：`e232566cb84833575df1f66981067679`
- 日期时间：2026-11-23T00:17:27Z（北京时间 11-23 08:17）
- 提交/镜像：v3 `9dbc2b97…` / `d8708751…`（此前记为 `428bde81…` 属误记，已更正）
- 镜像归档SHA-256：`unknown`；大小 150,218,752 字节，与本地修复包等大
- Sampler版本：`sampler:ckpt_vs1dihxehcgu`（与 R-20261118-late 相同，未重训）
- 原始回执路径：`e232566cb84833575df1f66981067679-report.json`
- 逐轮 `finish_reason`：`unknown`；逐次 token：`unknown`；汇总 `prompt_tokens=26,886`、`completion_tokens=3,840`（恰好 30×128）、`total_tokens=30,726`
- 决策分支计数：A/B/C 各 10 轮，共 30 轮全部 `conservative_invalid_response`；有效 `rac` 0、有效 `conservative` 0
- 采用轮次：A 第 8 轮 / B 第 4 轮 / C 第 6 轮（报告中最后 `promote`）
- 隐藏测试展示值：A Accuracy 0.731273 / Macro-F1 0.661861；B MAE 496.277472 分钟 / RMSE 718.078290 分钟；C MAE 41.185423 循环 / RMSE 56.290969 循环；不计入正式成绩
- 结论状态：`平台报告已核验；平台回退未解决；原始回复与逐轮 token 仍缺`

### R-20261124-controlled（v4 受控复验，已完成）

- 运行ID：`d084054c2124b19a36dae7e86fdccb99`
- 日期时间：2026-11-24T04:14:40Z（北京时间 12:14）提交；报告状态 `completed`
- 提交/镜像：v4 `e601e626…` / `3eebd66f…`
- 镜像归档SHA-256：`ff8b4fdd5f4f1a670fef83f72526649c14922c9dddadd2ce7edd2811e5354c4c`（本地导出时计算，平台上传回执记录了同一归档 ID）
- Sampler版本：`sampler:ckpt_26vkcgd09miv`（新重训，选择合同）
- 训练记录：`https://swanlab.cn/@2025040064/industrial-harness-sft/runs/vcjb4v90`
- 原始回执路径：`d084054c2124b19a36dae7e86fdccb99-report.json`；运行中快照 `-report.partial.json`
- 汇总 token：`prompt_tokens=26,391`、`completion_tokens=660`（30×22，**不再打满 128**）、`total_tokens=27,051`；`training_seconds=3023.4`
- 决策分支计数：A/B/C 各 10 轮，`conservative` 30、`rac` 0、无效 0 —— **回退已消失，但 RAC 分支从未触发**
- 采用轮次：A 第 8 轮 / B 第 4 轮 / C 第 6 轮
- 隐藏测试展示值：A Accuracy 0.731273 / Macro-F1 0.661861；B MAE 496.277472 分钟 / RMSE 718.078290 分钟；C MAE 41.185423 循环 / RMSE 56.290969 循环
- 与 R-20261123 的关系：三项任务指标**逐位相同**（A 0.7312730249693 等）。原因已定位：`action != rac` 时参数固定取 `alternative`，两轮均为「非 RAC」路径，轨迹完全确定
- 结论状态：`解析回退已解决；决策策略退化（30/30 conservative）成为新的阻塞项`

监控脚本：`experiments/rebuild-image-20261124/platform_submit.py`；状态与 API 响应：`experiments/rebuild-image-20261124/platform-state.json`、`*-response.json`、`platform-trial.log`。报告落地后按固定字段回填本行。

### R-20261124-selection-v5（v5 第二次受控复验）

- 运行ID：`3bf441ab0f7dd7b3f3c15a46a3df0ac0`
- 提交/镜像：v5 `1407e09bf46aa798f23fde44fa77ba4e` / 归档 `b982d566db383214c174b8ceab66bb9c`（150,272,000 字节）
- 镜像归档SHA-256：`e232d0ec2dcce7a018ad3246898b0bb9c470bde222096ea8fad792103fd692fc`
- 镜像 ID：`sha256:51de921fbb41c042437317756df9f35b4b9b1b94bf5c995df9d88c72b022d6f`（父镜像 v4 `3ffc6236…`）
- Sampler版本：`trio://run_1fei9lfkoj70/sampler_weights/industrial-harness-lora-selection-v3-20261124`
- 训练记录：`https://swanlab.cn/@2025040064/industrial-harness-sft/runs/ax998s81`
- 与 v4 的差异：训练/推理共用 `selection_payload`；训练样本改为「反事实配对」（18 RAC : 18 conservative，72 步）；训练后两类可达守卫必须通过
- 本地守卫生效：留出 C 2 RAC / 8 conservative；改善历史 4/4 RAC；被拒历史 0/4 RAC；10/10 回复合法
- 原始回执路径：`experiments/platform-runs/3bf441ab0f7dd7b3f3c15a46a3df0ac0-report.json`
- 平台结果（completed）：`completion_tokens=660`、`prompt_tokens=22485`、`training_seconds=3705`，`model_identity=sampler:ckpt_d6gjdn7qetuw`
- 动作分布：A `rac 10 / conservative 0`；B `rac 5 / conservative 5`；C `rac 6 / conservative 4`（**两类均可达，无 `_invalid`**）
- 隐藏指标：A `accuracy 0.865330 / macro_f1 0.860822`（与 v1 逐位相同）；B `mae 455.502 / rmse 654.005`；C `mae 41.176 / rmse 56.320 / nasa 8.51e10`
- 结论状态：`决策塌缩已解决；A 恢复到 v1 水平，B 优于 v1/v4，C 基本持平`

### R-20261124-train-kernel-v6（v6：训练侧优化）

- 运行ID：`82522846a0d57928a16292b2c4ad183a`
- 提交/镜像：v6 `07d126ada6e9ef1d2733ceda0036edf2` / 归档 `730e2392439ba35765e43a049eaeb137`（150,312,960 字节）
- 镜像归档SHA-256：`b7526832252200c13b6f98829a3309d1e7bf77e1dbecb115ed245aef05f57a67`
- 镜像 ID：`sha256:877248e2e7bb98757748b0cf2ab51817cf71605cb554438f4fcc9b69b77b9a38`（父镜像 v5 `51de921f…`）
- Sampler版本：与 v5 相同（`industrial-harness-lora-selection-v3-20261124`），本次未改决策采样器
- 与 v5 的差异：① 续训对 epoch 末权重做 EMA（decay 0.6，仅回归任务）；② 回归任务学习率下限 3e-3；③ 父检查点自带 lr 低于下限时夹取，避免第 1 轮报错
- 定位依据：用 v5 真实逐轮参数本地重放得 37.9069，平台报告 37.9052（差 0.0016）；本地 10 轮续训父 38.8998 → 36.7811（MAE −5.4%），接受轮次 1/10 → 9/10；按单元对半切开两半均改善
- 节点：2026-11-24T11:56Z 入队（北京时间 19:56）
- 原始回执路径：报告落地后写入 `experiments/platform-runs/82522846a0d57928a16292b2c4ad183a-report.json`
- 结论状态：`试运行中，报告未回`

## 镜像关联链（P1-1）

历史 v3 链：`运行时源码SHA → -02/source-files.json → 镜像 sha256:8ec04537… → 本地归档 6b001568…（150,218,752 字节）→ 平台归档 d8708751…（等大，SHA 未暴露）→ 提交 v3 9dbc2b97… → 运行 e232566c…`。该链只到大小级关联，归档 SHA 仍 `unknown`，历史运行若无法取得原始上传回执就标记 `无法追溯`。

新 v4 链（11-24 首次全链留痕）：`当前源码SHA → experiments/rebuild-image-20261124/context/source-files.json → 新镜像 sha256:3ffc6236… → 本地归档 ff8b4fdd…（150,251,520 字节）→ 平台归档 3eebd66f… → 提交 v4 e601e626… → 运行 d084054c…`。每一段都有本地文件或平台响应佐证；受控试运行报告待回。

## G0 门禁剩余清单

已取得：运行 ID、提交版本、镜像归档 ID、Sampler 身份、逐轮 `model_action`、汇总 token、artifact/seed/model_call_ids。

仍需索取：

1. 每轮原始模型回复文本（含结束标记，未解码）。
2. 每轮请求参数全文：`max_tokens`、temperature、seed、stop 序列、提示 payload。
3. 每轮 `finish_reason` 与逐次 `prompt_tokens` / `completion_tokens` / `total_tokens`。
4. v3 归档 SHA-256 或平台侧内容摘要。
5. 候选详情里的 checkpoint 摘要、验证投影摘要与实际选中理由（报告已给 artifact ID 与 seed，未给摘要）。

取得后按"固定字段"追加新行，并把原始回执存入本目录（文件名以运行 ID 命名），再更新 `RAC-HPO_问题解决与验证方案.md` 的 G0 状态。

## 本地回退对照（2026-11-24，非平台运行）

路径：`experiments/local-fallback-replay-20261124/replay.py`，结果：`results.json`。A/B/C 各 10 轮，共 180 轮，文本注入生产 SDK 回调，不访问平台、不采样、不计费训练。

| 注入文本 | 回退次数 | 拒绝原因 |
| --- | --- | --- |
| `-01` 真实 `RAC<\|im_end\|>` | 0/30 | — |
| `-03` 真实选择 JSON | 0/30 | — |
| 旧训练目标「参数提案 JSON」 | 30/30 | `parameter_proposal_json` |
| 截断 JSON | 30/30 | `truncated_json` |
| fenced JSON | 30/30 | `fenced_json` |
| 未知结束标记 | 30/30 | `invalid_terminal_marker` |

**不能填入上表任何平台运行行**：这是本地代码路径验证，不是平台原始回执。它只说明「若平台回复是旧格式或非法格式，本地解析器会按设计回退；若平台回复已是新合同格式，本地解析器不会回退」。
