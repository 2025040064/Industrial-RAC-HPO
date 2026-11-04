# 智训引擎：受控单轮离线闭环

日期：2026-10-31。当前在 App 0.3.0 上增量实现，包名 `rac_hpo`、RAC 算法 `rac-hpo-0.2.0`、原实验 DB Schema 1 保持兼容。本文为已批准的新方向与实现约定，不是官方评分标准。

## 数据协议

只接收已钉住 SHA-256 的作者 CNC Milling 2025 聚合 CSV，不自动下载或替换数据。

| 角色 | 物理工具 ID | 行数 |
|---|---|---:|
| 基础训练 | 2、6、105、10、7、11 | 341 |
| 固定调参验证 | 4、103 | 101 |
| 回放 | 5 → 8 | 51 + 116 |
| 一次门禁 | 9、101 | 233 |
| 原 test，完全不参与闭环评分 | 102、3 | 126 |

初始模型只用新协议训练与验证。历史最佳模型用过原 validation，不作为本协议未见门禁的冠军。旧 manifest、原固定划分和历史实验保留。

20 行一批，末批保留11/16行。回放按 NumberOfCycle、源行号稳定排序，以 FileName 和源行映射识别样本；周期号不保证全数据唯一，不补缺失周期、不制造时间戳。CycleToFailure 为后验寿命信息，整刀结束才释放；tool5释放后可加入候选训练，tool8未来信息不进入选参。tool8仅作后续观察，整刀结束后比较活动模型与初始冠军在相同行上的预测，不与其他刀具误差混比。

训练视图内容寻址并独占提交，保存 source_row_indices 和重映射 train/validation 索引。训练对象不包含门禁或 test 行；闭环实验 finalize 明确失败。读取完整源文件用于适配不等于将保留标签用于训练或评分。

## 固定策略与门禁

初始基线 + 最多一次 HPO，默认 seed=42 / RAC-HPO / 48 trials / 搜索120秒。搜索沿用六维空间、固定 J 和代理质量回退；基线另计。会话训练总预算300秒，在动作与树迭代边界检查，保存实际耗时和超时。初始登记冠军属于会话训练授权，候选模拟切换及回滚需要额外人工操作。

质量异常进入 DATA_REVIEW；无标签的特征/工况分布变化只建议观察。至少20行才计算特征告警：训练IQR归一化Wasserstein距离大于0.5的传感器比例超过20%；工况TV距离大于0.25单独告警。整刀标签释放后，同工况MAE超过初始冠军验证参考值1.2倍，形成可能退化提案，不声称归因确定。无自然触发时可显式 manual_demo。

候选冻结模型、冠军模型、协议、策略与阈值哈希后，门禁只读一次：整体MAE不超过冠军1.02倍+1e-8，各工况不超过1.05倍+1e-8，模型须可加载、哈希匹配、特征顺序一致且预测有限。门禁按源SHA和门禁行指纹全工作区唯一，不因修改会话ID、路径、预算或场景而重置。门禁中断也不允许换候选重试；成功记录只可返回原结果。工作区内已消费门禁时，新会话运行会明确拒绝，并指出原会话。

通过进入 WAITING_RELEASE，人工批准只切换本地会话槽位；可选择保留冠军。失败继续用冠军回放。tool8结束后若活动候选MAE超过初始冠军在相同行上的MAE的1.05倍+1e-8，提出回滚建议；也允许用户在已切换后主动回滚。回滚恢复初始冠军引用，核验哈希与预测。

## CLI 与 GUI

```powershell
.venv\Scripts\python.exe -m rac_hpo loop create --authorize-training
.venv\Scripts\python.exe -m rac_hpo loop run LOOP-ID
.venv\Scripts\python.exe -m rac_hpo loop show LOOP-ID
# 若无自然优化触发，可在 AWAITING_OPTIMIZATION 状态显式运行：
.venv\Scripts\python.exe -m rac_hpo loop run LOOP-ID --manual-demo
# 先 show 查看当前 revision；仅门禁通过时允许批准：
.venv\Scripts\python.exe -m rac_hpo loop promote LOOP-ID --expected-revision REVISION
.venv\Scripts\python.exe -m rac_hpo loop run LOOP-ID
.venv\Scripts\python.exe -m rac_hpo loop rollback LOOP-ID --expected-revision REVISION
.venv\Scripts\python.exe -m rac_hpo loop export LOOP-ID
```

`LOOP-ID`、`REVISION` 替换为真实值。`loop decline` 拒绝切换；`loop list` 列出会话。`create --data PATH --policy policy.json` 可显式指定原始文件和严格JSON策略；允许字段为 seed、algorithm、max_trials、timeout_seconds、training_budget_seconds、scenario。超限、未知字段/工具均拒绝。没有 `--authorize-training` 的会话不能运行。

终态失败/中断/质量异常/预算耗尽返回非零，取消返回130；门禁拒绝属于已完成的有效结果。已有命令默认行为不变。`--root WORKSPACE` 仍放在子命令之前。

GUI 保留五页并增加“自主优化”。授权前不能启动；查看其他会话不改变活动任务；全局取消针对后台任务。门禁通过后“批准模拟切换”和“人工回滚”各有明确确认，审批携带页面所见revision，过期或重复操作失败。历史面板、诊断、模型、策略和划分来自服务，缺少结果保持空态。

## 持久化与恢复

独立 `workspace/database/lifecycle.sqlite3` 保存 sessions、events、gate_uses、leases，Schema 1；旧 experiments.sqlite3 不迁移。新文件、模型、清单先原子落盘再事务提交引用；活动槽位、审批、审计在同一事务中提交。应用不覆盖原模型文件或旧试验。

同一会话执行有进程租约；死进程释放租约后，TRAINING_INITIAL / TRAINING_CANDIDATE / EVALUATING 转 INTERRUPTED，不重新执行训练或门禁。终态和待审批状态重读不重训。租约用本机进程存活判断，适用于单机桌面；不是分布式调度器。

原始回放为 REPLAY。missing_sensor、feature_shift 为 SIMULATED，扰动只作用副本，模式传播到训练视图、实验、进度、预测、会话和导出。缺失场景阻断候选训练；偏移场景按训练IQR对前30个传感器加3倍偏移。模拟数据不可宣传为真实在线漂移。

## 验证与限制

```powershell
.venv\Scripts\python.exe -m pytest --basetemp workspace/verification/controlled-loop/pytest -o cache_dir=workspace/verification/controlled-loop/pytest-cache
.venv\Scripts\python.exe scripts/verify_controlled_loop.py --native --scale 1
# 对同一验收工作区重画，不重复训练或消费门禁：
.venv\Scripts\python.exe scripts/verify_controlled_loop.py --render-root ACCEPTANCE-DIR --native --scale 2 --sizes 720x560,1280x800
.venv\Scripts\python.exe scripts/verify_controlled_loop.py --render-root ACCEPTANCE-DIR --scale 2
```

真实验收不自动批准切换。正向切换、负向门禁、事务失败、损坏模型和回滚由隔离自动化测试覆盖。1920×1080逻辑窗口在200%原生环境可能超过桌面可用尺寸，须报告实际尺寸，不以被约束窗口冒充指定尺寸通过。

门禁仅会话内隔离，历史研究已见过这些数据；各验证/门禁工况一把刀具，q=0、不输出CI。工程阈值不证明统计非退化、算法全面领先或生产可用性。本轮不接真实设备，不提供生产推理服务，不做多轮RSI、自修改代码、LLM、分类或新数据接入。
