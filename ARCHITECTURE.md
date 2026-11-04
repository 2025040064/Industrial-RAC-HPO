# 智训引擎技术规范与实施架构

## 2026-10-31 工业数据与分类训练增量

实施计划见 `docs/INDUSTRIAL_TRAINING_PLAN.md`，真实结果见 `docs/INDUSTRIAL_TRAINING_REPORT.md`。沿用 PreparedDataset，新增数据契约在 manifest 明确 task_type、data_origin、source_files、split_fingerprint；不改变旧回归对象与 SQLite Schema。

- `data/industrial/{uci,bearings,local,common}`：AI4I / SECOM / Paderborn 各自来源和特征契约；XJTU-SY 完整寿命回归本地审计，联想/Pneumatic 带来源与授权/动作标签的本地规范化表入口。归档导入拒绝路径穿越、链接、超额数据与覆盖；按归档哈希在工程内原子建立解压缓存，复用前核对全部文件及链接，记录输入归档哈希，审计后训练不再重复解压。Paderborn 小样本显式保存官方归档字节范围和实际 MAT 哈希。
- `training/classification`：三种表格分类器、训练折中位数/独热编码、固定类别、取消和可重载模型。学习曲线来自真实boosting迭代；Random Forest明确无逐轮验证曲线。
- `evaluation/classification`：balanced accuracy、macro F1、log loss、类别计数/召回、分工况及真实轴承分组。少量类别和缺失类别显式提示；未知/合成行组不形成独立单元证据。
- `optimization/classification`：三方法同固定 J，balanced error = 1 - balanced accuracy；沿用 normalized_objective 与 RACSearchPolicy。旧策略数值字段通过内部 loss 适配，不向外保存伪 MAE。基线 trial -1 不占搜索预算；代理不合格回退 TPE，树离散度和轴承重采样仍未校准。
- `application/industrial_service`：`audit/fetch/run/list_runs/get_run/compare`，每次运行独立 `workspace/industrial_runs/IND-*`，原子配置/manifest/模型/指标/日志/曲线，失败与中断保留；死进程仅关闭状态，不自动重训。`compare` 分别给出描述可比与公平 HPO 可比证明；公平比较检查来源/划分/模型/seed/预算/资源/目标/空间。
- CLI `industrial` 和工作台第七页共用服务及既有独立任务进程。分类活动/历史结果与原回归快照隔离；工业worker不初始化原回归数据库。图表和表格只显示实际保存指标；模型参数与来源不匹配时不排名。
- `scripts/run_industrial_benchmarks.py`：真实三模型基线、三方法多种子同预算对照，完整种子与试验且条件一致才生成 fair_comparisons；不完整部分只保留描述统计。不会下载或访问 test。

当前分类服务拒绝 XJTU 回归训练；它的未来训练应复用回归评价，禁止与故障分类合并排名。1D-CNN/LSTM、新来源的漂移与连续演化尚未接入。本增量未做生产部署或发布。

统一规范为 [完整总纲](docs/RAC-HPO_Implementation_Architecture_v1.md)。该文件保留用户提供的 V1 原文。本文件记录实际实施接口与后续维护边界。

2026-10-31 新方向：以训练/HPO 为核心，增加受控单轮离线优化闭环。旧总纲是历史设计来源；新增协议与当前接口以本文件及 [CONTROLLED_LOOP](docs/CONTROLLED_LOOP.md) 为准，执行边界记录在 PLAN.md。

## 新增受控单轮闭环

- `data/loop_views` 定义固定 CNC 整刀角色、稳定回放顺序、整刀标签释放与不可变训练视图。复用 PreparedDataset，只有 train/validation，保存源行映射；门禁和 test 不传入训练器。视图摘要与源 SHA-256 均在重载时验证。
- `domain/loop_policy` 固定授权策略、预算和工具白名单；`monitoring/drift` 只计算质量/分布事件和工程门禁，不导入 Qt 或 SQLite。
- `application/loop_service` 编排初始训练、回放、后验诊断、一次 HPO、候选冻结、一次门禁、人工模拟切换及回滚；`loop_models` 校验实际模型哈希、特征顺序和有限预测，使用统一 evaluator。
- `ApplicationService.run_experiment(..., dataset_view_id=None)` 新增可选视图；原调用不变。视图实验附带 data_mode，环境同时记录工作区及实际实现源码指纹。finalize 对视图实验在准备数据前拒绝。优化目标 J 和旧训练器不改。
- `infrastructure/loop_repository` 使用独立 lifecycle.sqlite3 / Schema 1；BEGIN IMMEDIATE 事务覆盖建表/版本、状态/审批/审计/活动模型引用。gate_uses 按源文件及门禁行指纹唯一，不能靠换会话重试其他候选。先保存模型与清单，后提交引用；旧实验库 Schema 1 不迁移。
- 会话进程租约阻止同一会话并发执行，revision 阻止过期审批。中断训练/门禁标记 INTERRUPTED，不自动重训；失败、中间试验及已消费门禁保留。模型切换仅更新本会话本地槽位，无生产服务部署。
- CLI `loop` 与第六页自主优化共用服务，GUI 沿用独立进程、80ms 队列与更新合并；loop session 与原 experiment 的活动/查看状态分开。保留固定56px导航及原五页。

本轮默认回归任务、单次候选门禁、q=0；一次工程门禁不构成算法可靠性或跨机床泛化证据。新数据、分类、连续多轮、LLM 和发布未实施。

## 当前实现：阶段 0–3

`interfaces` → `application` → `data / training / optimization / evaluation`；`infrastructure` 为应用服务提供配置、SQLite 和产物存储。核心模块只通过 domain 数据结构传递信息，不导入 GUI 或数据库。

- `domain/schemas.py`：PreparedDataset、TrainingResult、OptimizationResult 与取消异常。
- `data/loader.py`：UCI 钢铁能耗适配器，验证来源、固定特征和按日时间划分。
- `data/cnc_milling.py`：作者 CNC Milling 2025 文件校验、分号/小数逗号解析、物理刀具分组与固定切深工况；`data/registry.py` 统一下载、识别和适配器分派。
- `training/lightgbm_trainer.py`：训练折拟合模型、验证折早停，不读取测试集。
- `training/model_export.py`：通过 UTF-8 文本加载模型，兼容 Windows 中文路径；最终重训复用 training.build_regressor 保持参数一致。
- `evaluation/evaluator.py` 与 `domain/metrics.py`：总体 MAE、分工况原始 MAE 和固定鲁棒目标的唯一实现；向量化 normalized_objective 同时供真实评分与代理候选评分使用。
- `evaluation/uncertainty.py`：保留独立单元误差和样本数；只对足量物理刀具/独立运行执行分组重采样，日期块和不足分组不生成区间。
- `optimization/base.py`：统一 optimize(config, trial_runner, progress_callback, cancel_check)，支持 random / tpe / tpe_robust / rac_hpo，所有算法共享真实训练、预算、取消与持久化路径。
- `optimization/rac_hpo`：surrogate 维护多输出性能/对数成本代理和前向检验；regime_priority 计算有界可信关注；acquisition 计算改善/成本分数；search 组合候选、全局探索、缓存和显式 TPE 回退，不直接训练模型或访问 GUI/数据库。
- `application/experiment_service.py`：prepare_dataset、run_experiment、list_experiments、get_experiment、export_results、finalize_experiment。
- `infrastructure`：版本化 YAML、SQLite 元数据、原子文件写入、模型 / 图表 / 配置 / 环境快照。
- `_io.py`：数据清单与实验文件共用的原子 writer；不可变清单使用独占提交，数据层保持独立于数据库实现。Windows 临时访问/共享锁错误有限次退避重试，永久错误仍抛出并保留旧文件。
- `interfaces/gui`：Qt 主线程绘制，独立进程调用应用服务，队列传递真实进度与结果，Event 请求取消。

## 数据与评价边界

本轮基线研究任务为已知日历条件下的钢铁用电量回归，并非完整生产功率预测。输入仅日历元数据；Load_Type 和同时刻电气量不参与训练。工况先验定义为工作日与周末；日期仅用于相关时间块计数，未声明独立生产批次。数据按时间顺序划分为 train / validation / test，并保留日期边界间隔。

CNC 任务使用当前周期传感器聚合与已知工艺元数据，预测 CycleToFailure（cycles）。身份、周期序号和两个未来寿命标签排除；单机床 14 把刀具按整把工具固定分层划分，442/400/126 行。ADOC=5/10 mm 是先验工况。验证集每工况只有两把刀具，默认 minimum_independent_groups=5，因此区间为空、q=0；不得以周期行数或文件数代替独立证据。来源、许可、字段顺序、真实工具 ID 与索引均保存在独占创建的 manifest。

每次搜索先运行默认基线，固定其分工况验证 MAE 作为 B_g；权重由验证样本占比预先固定，alpha 与 epsilon 从运行快照读取。基线初始化耗时、搜索耗时和总耗时分别保存。搜索预算在下一次试验开始前检查，已开始的单次试验允许完成，可能超过时间上限一个 trial。测试集只在显式 finalize 流程使用，搜索与界面排名使用验证指标。

## 持久化与版本

App 0.3.0；RAC Algorithm rac-hpo-0.2.0，其余基线保留各自算法标识；Config / DB Schema 1。新增数据和诊断使用兼容的配置/JSON 字段，没有数据库迁移。每次实验 UUID 唯一目录，不覆盖旧实验。SQLite 保存 experiments、trials、regime_metrics、artifacts、schema_version；文件保存 config.yaml、manifest.json、environment.json、trials.jsonl、metrics.json、模型和曲线。未知数据库版本明确阻断，不自动迁移。

RAC 默认暖启动/最少历史均为 16，48 棵 ExtraTrees、128 个候选（全局/局部各半），20% 全局探索；基于过去前缀预测最后 5 个历史试验，性能 MAE 不高于前缀均值基线的 1.25 倍且排序相关不为负才启用代理。默认每新增 4 个完成试验重拟合，缓存至多落后 3 次，记录训练历史大小和年龄。候选使用树离散度及配对前向残差重采样近似改善概率，分数为 (EI_J + beta·sum(q_g·EI_g))/(cost+t0)^gamma，beta=gamma=0.5、t0=0.01。q 上限 0.5，经 n/(n+5) 收缩且必须满足独立证据条件；最终真实 J 不随 q 改变。代理检验、覆盖诊断与总体误差筛选均不构成已校准统计保证。

每次决策保存 method、reason、candidate_seed、前向检验、预测、q、代理年龄、选择耗时；汇总保存回退次数与原因。预算包含候选选择开销，收敛图累计选择与实际训练耗时。默认基线初始化仍单独计时。导出使用目标真实单位与分组定义，不硬编码 kWh 或日期。

## 实验工作区 UI

五页保留PySide6/QPainter及独立任务进程。主窗顶部上下文栏与导航均56逻辑像素，导航仅显示单个Tooltip。后台任务和当前观察实验分开，历史查看不改变新任务输入。

`workspace_state`承载纯展示状态与Trial映射；`workspace_widgets`复用指标、Section、可选紧凑多选表及详情；`workbench_widgets`负责响应式双栏/列表对话框和只读并排查看；`parallel_coordinates`根据保存的参数空间绘图并发出观察/brush事件。GUI不新增存储或训练接口。

优化页Trials与图表共用搜索/状态/brush交集；完整历史保留累计最优，其他分析标明过滤范围。观察行和勾选独立，稳定ID为experiment_id:number，基线-1不进入搜索统计。最佳objective与最佳MAE各自标识Trial，缺失和非有限值显示—。

MainWindow继续按experiment_id隔离活动/查看快照、number去重、80ms合并渲染与终态完整替换。详情和最大化绑定对应实验，保留焦点、滚动和过滤。最大化关闭先脱离父控件再deleteLater，避免父子析构的重入。

Runs/Trials宽屏默认280/320px、可调280–440px；窗口<1024px时使用覆盖列表。工作区面板按900px容器断点重排；最小720×560。跨Run缺少split及目标/特征版本证明，仅并排呈现真实结果，不排名。未提供的重要性、样本预测、质量与过程数据明确空态。

详细约定见UI_DESIGN.md，当前交付见docs/UI_WORKBENCH_V2_REPORT.md，旧UI_REFACTOR_REPORT记录上一轮实现。

## 算法证据与后续

工业分类可显式选择 `model_config.decision_mode=time_oof`。训练分区按已审计时间戳的唯一值进行前向分折，每折独立拟合预处理和分类器；合并训练侧折外概率，以平衡准确率在固定网格上选阈值，同分取较高阈值。折内保留时间边界和行索引哈希，结果保存阈值、类别召回、误报率、平均精确率与折样本数；概率未校准。该策略要求二分类、可靠的时间顺序和足够的折外正负样本，拒绝跨时间折或训练／验证划分的已知分组重叠；物理轴承任务拒绝使用并要求后续实现组感知验证。缺失设备或批次 ID 时无法证明这些未知实体没有重叠。为确保折外与最终拟合可比，固定树数并禁用早停，成本高于原默认训练；不能将不同策略的计时当成同资源对照。模型携带阈值，旧模型和 `native` 保留原行为。RAC 单工况代理以一维目标训练，消除 sklearn 目标形状告警，不改变代理质量门槛。具体实验与限制见 `docs/INDUSTRIAL_ALGORITHM_OPTIMIZATION_REPORT.md`。

阶段 2、3 的实现和三种子 10 秒小预算对照已完成，结果及全部 ID 见 docs/PHASE_2_3_REPORT.md。该对照只验证初步效果：平均 J 与总体 MAE 的排序不同，可信工况分支在当前真实数据中未被激活。阶段 4 仍需扩大独立样本、外部验证和消融；阶段 5 发布未实施。
