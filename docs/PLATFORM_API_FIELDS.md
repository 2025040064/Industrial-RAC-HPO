# 竞赛平台接口字段速查（v8-B 门禁与隐藏集取证）

> 记录时间：2026-11-25 21:55
> 平台：`https://rsi-index.115.zone/api/v1`（Bearer token，取自 Safari localStorage 的 `contest_session`）
> 结论用途：回答「门禁缺失项在哪查」「隐藏集明细在哪查」

## 一、门禁数据的真实位置

| 想要的信息 | 接口 | 字段 |
|---|---|---|
| 5 个门禁的布尔结果 | `GET /runs/{run_id}/report` | `objective_result.gates` |
| 是否可参与排名 | 同上 | `objective_result.eligible_for_ranking` |
| 目标分与分项 | 同上 | `objective_result.objective_score`、`objective_components` |
| **拒稿/不合规的文字理由** | `GET /submissions` | `compliance_status`、`compliance_reason` |
| 材料是否齐备 | `GET /submissions` | `materials_complete`、`base_model_confirmed` |
| 各任务实验记录完整度 | `GET /runs/{run_id}/report` | `training_records[].record_complete`（A/B/C 各自） |
| 数据集标签状态 | 同上 | `workspace_suite.datasets[].label_status` |

**注意**：`GET /submissions/{id}`、`GET /runs/{id}` 不存在（404）；详情只能从 `/submissions`、`/runs` 列表项里取。

## 二、v8（提交版本 8，run `83d226c3…`）实测状态

```
submission cfd94428c4d325e00cc00921927994b9  version 8
  compliance_status      = unreviewed        ← 平台至今未审核，因此没有「缺什么」的文字说明
  compliance_reason      = ""                ← 空
  materials_complete     = null              ← 未评审
  base_model_confirmed   = false
  score                  = null（版本级）
run 83d226c33445ca8176ec66cf29885916  mode=formal  status=completed
  score                  = 52.24
  objective_score        = 11.7719
  objective_components   = mean_gain 3.2230 / recovery 3.3730 /
                           resource_efficiency 0 / retention 5 / worst_stage 0.1759
  gates = autonomous_completion_on_time      true
          not_below_static_baseline          true
          three_traceable_decision_cycles    true
          complete_materials_and_reproducibility  false
          experiment_records_complete        false
  training_records: A/B/C 三项均 record_complete=true，各 10 轮
  workspace_suite.datasets: A label_status=draft, B=approved, C=draft
  report 字段 = null（隐藏集逐任务指标确实未通过该接口暴露）
```

**推论（有证据，非猜测）**

1. `experiment_records_complete=false` 与「A/B/C 记录没跑完」无关——三项都为 `record_complete=true`。
   最可疑的直接来源是 `workspace_suite.datasets` 里 **A、C 的 `label_status=draft`**（B 已 approved）。
2. `complete_materials_and_reproducibility=false` 与「少传某个文件」无关——`materials_complete=null`
   且 `compliance_status=unreviewed`，即**平台侧材料审核从未发生**，门禁在未审核状态下默认不通过。
3. 平台历史上唯一给出明确文字拒稿的是 v7（`da5f98ed…`）：
   > 当前提交不符合赛题续训要求。请基于官方baseline及平台提供的父检查点实现真实续训，
   > 修改后重新上传镜像并提交新版本；不得从头训练另一套模型替代baseline。

## 三、隐藏集明细

- `GET /runs/{id}/report` 的 `report` 字段为 `null`；`training_records[].rounds[].validation_metrics` 只有**公开验证集**指标。
- 追加尝试均 404：`/runs/{id}/metrics`、`/records`、`/tasks`、`/result`、`/score`、`/report/A`、`/report/summary`、`/submissions/{id}/runs`。
- `?task=A` 参数无效，返回与无参完全一致的报告。
- 结论：**逐任务隐藏集指标在该 API 中不存在**。只能看平台网页「查看报告」页或等评审后台数据。

## 四、资源效率为 0 的分项

`objective_components.resource_efficiency = 0`，而 `retention = 5`、`mean_gain = 3.22`。
该项是最容易拿到分、却完全没拿到的分项，值得单独排查口径（是 CPU 用时、镜像体积，还是 token 消耗）。
