# 智训引擎技术规范与实施架构

<<<<<<< HEAD
## 2026-11-09 macOS 运行环境

macOS 使用项目内 `.venv`、`.python` 和 `.cache`；Apple Silicon 的 LightGBM 依赖 Homebrew libomp。macOS 依赖 PySide6-Essentials 6.9.3（项目使用的 QtCore、QtGui、QtWidgets 和 QtTest 均包含在内），其他平台仍依赖原 PySide6 6.9.3；环境快照兼容两种发行包并保留 `PySide6` 键。原生界面验证脚本不再强制 Windows 平台插件：`--native` 由 Qt 自动选择当前系统平台，默认仍使用 offscreen。回归 GUI 恢复与后端一致的 Grid、Successive Halving 和 Hyperband 入口。安装不隐式下载数据。
=======
## 2026-11-18 竞赛代理与迁移安全门槛

SDK 回调通过 `RAC_TRANSFER_MODE=off|legacy|gated`、`RAC_SURROGATE_MODE=off|shadow|active`、`RAC_COST_MODE=off|transfer|acquisition|both` 和 `RAC_BEARING_FEASIBILITY=off|shadow|active` 控制搜索；默认分别为 off、shadow、off、off。历史兼容开关 `RAC_TRANSFER_HISTORY=1` 显式选择 legacy，不能作为可信迁移证据。gated 要求匹配投影、时间、工况距离、足够观察及不同父模型，并要求既往配对证据；当前 SDK 尚不提供可信证据载入，因此不会自动启用。

工况代理分别前向核验性能和可变训练 CPU 成本；成本失败仅关闭成本惩罚。active 必须有相同父模型、真实训练过且严格早于当前轮的影子候选质量证据，否则实际使用 shadow。B 的最近邻可行性仅记录影子判断，真实逐轴承硬门槛不变。结构化模型回复只能选择合法方案，仍由平台主指标、固定 J 和真实轴承误差共同决定是否采纳；非法回复保守回退。CPU 分段、SHA、历史门槛及模型回执写入逐轮审计。详细证据和未完成事项见 [阶段三决策](docs/RAC_HPO_STAGE3_RELEASE_DECISION.md)。

## 2026-11-18 竞赛硬 CPU 预算对照

独立实验驱动 `experiments/ablation/hard_budget.py` 保留既有 SDK 回调与选择规则，按冻结协议在每个单线程 worker 进程施加 `RLIMIT_CPU`，以 `wait4` 记录 user/system CPU。预先冻结 A/B/C 上限 4/9/60 秒，软限额提前 1 秒，最终已完成轮、未完成轮资源、阶段计时和峰值内存分别留痕。候选和 state 写完后原子提交轮次；恢复前核对父 SHA、审计和累计 attempt CPU，无法核算的中断安全拒绝恢复。controller 的解压与调度 CPU 单独报告。模型服务仅本地替身，结果不代表赛事平台。三种子对照、局限和未触发模块见 [阶段二报告](docs/RAC_HPO_STAGE2_REPORT.md)。

## 2026-11-18 竞赛消融实验接口

`ContestRACPolicy` 增加有界 `transfer_cost_weight` 选项，默认 0.05 不变；传入当前轮时拒绝本轮及未来轮历史，并记录 TPE 暖启动阈值、观察数和是否已进入拟合。离线 `experiments/ablation/run.py` 以 SDK 替身宿主、相同父链与选模合同运行 G0–G3；G1/G2 关闭 RAC acquisition 和迁移 TPE 的成本惩罚，G3 开启两处，三组保留相同代理成本质量门槛。源代码更改尚未写入历史镜像。首阶段单种子结果与预算限制见 [消融报告](docs/RAC_HPO_ABLATION_REPORT.md)。

## 2026-11-18 竞赛逐轮搜索审计

正式 SDK 回调的 `contest-sdk-history-v2` 状态将训练、验证及工况元数据投影摘要、主指标合同与连续的已选父 SHA 链绑定。同父记录供完整 `RACSearchPolicy` 使用；跨父记录不进入其代理，而是在同父历史不足时默认供独立 TPE 启发式使用，可通过 `RAC_TRANSFER_HISTORY=0` 关闭。旧状态或口径、链条不一致的记录保存在隔离归档，不进入新搜索。跨父目标是各轮候选 J / 父 J，再加 `0.05 * clip(log(训练秒数 / 中位训练秒数), -2, 2)`；这是有界软惩罚，不是硬性限时或完整成本代理。相对 J 不能消除父模型变化带来的不可比性。当时旧的无成本迁移在 A/B/C 三种子对照中未优于原策略；后续对照见本页阶段二记录。

SDK 的 `selection-audit.jsonl` 和状态逐轮保存 RAC 推荐、模型回复及合法性、`fit_epochs` 实际参数和采样策略、训练秒数、父与候选摘要、主指标和 J 门槛、选择理由与历史使用。宿主是否长期保存历史 artifact 仍待核实。独立本地修复镜像与原候选并存，详见 [竞赛审计报告](docs/CONTEST_CORE_AUDIT_20261118.md)。

## 2026-11-18 竞赛选择链与审计

新建本地 RAC 续训从上一轮已选 checkpoint 出发，固定 J 仍以原始模型为基准，仅将同父观察提供给搜索；已有无 `parent_mode` 标记的 RAC 运行继续按原固定父模型协议恢复。正式 SDK 始终使用宿主父产物，主指标严格改善与原有 J、可用的 B 逐轴承门槛同时生效。父/候选平台主指标还须与使用同一公开投影和 checkpoint 本地重算结果在相对 `1e-7`、绝对 `1e-8` 容差内一致，且本地值也严格改善；否则保留父模型。连续轮次的宿主父摘要若与已保存的上一轮选中摘要不一致，则停止本轮并报告，避免继续污染选择链。旧 state 无审计历史时不能作此跨轮核验。

每轮本地运行和 SDK state 中的 `selection-audit.jsonl` 记录父、候选、选中模型摘要、主指标、J、各门槛与原因；SDK 的路径是 artifact 内相对路径，能否长期恢复由宿主持久化合同决定。仅记录摘要和 ID 不保证历史 artifact 永久可用。本地已提交轮次可在日志写入中断后重建缺失的末尾审计记录。详见 [模型选择审计](docs/model_selection_audit.md)。

## 2026-11-17 竞赛提交候选与消融

竞赛基准脚本可选择 `rac_no_forward_gate` 或 `rac_bearing_constraint`。前者保留前向质量记录并绕过质量判定，后者在 B 的 TPE 提议中优先使用满足逐轴承 RMSE 边界的历史候选。真实 SDK 入口按默认设置保留代理质量回退和既有候选排序。当前提交候选依据比赛页面要求，在 Linux/amd64 构建并使用 `docker save` 导出单镜像未压缩 tar。

## 2026-11-17 跨父历史研究选项

当时的 SDK 回调默认关闭跨父迁移，显式 `RAC_TRANSFER_HISTORY=1` 才启用相对 J 暖启动 TPE。三种子实验证据未支持该方案，详见 [实验报告](docs/CONTEST_TRANSFER_EXPERIMENT.md)。现行源码的后续变化见上方 2026-11-18 记录。

## 2026-11-17 Harness SDK 容器装配

`official_submission/prepare_context.py` 校验 SDK 压缩包与三份基线运行源码摘要，生成独立 Docker 上下文和源文件清单。容器安装锁定 Python 依赖及实际 SDK 1.0.2，入口使用原 SDK 模板。官方镜像入口与既有本地 `Dockerfile.harness` 续训镜像分别构建。ARM64 本机门禁在只读根文件系统、禁网、单 CPU 和非 root 用户下验证。

## 2026-11-17 Harness SDK 1.0.2 适配

`official_submission/contest_submission.py` 实现官方模板调用的 `train(rnd)` 和 `predict(sample, model_dir)`。每轮校验官方父 NPZ 摘要，按固定特征合同从本轮公开训练投影续训，使用 SDK 模型回执在 RAC 与保守候选之间选择。训练后的候选由宿主测量，主指标缺失或门槛失败时保留合法父产物。状态只在 `/workspace` 副本保存，按父摘要及公开划分摘要限制可比较搜索历史。B/C 无验证组元数据时使用整体验证 MAE 作为内部 J 的唯一分量，关闭独立单元加权；即使如此，宿主的主指标仍为 RMSE。

## 2026-11-17 竞赛 V2 的 RAC 历史与成本门槛

本地竞赛新运行使用 `contest-rac-hpo-v2`。候选历史必须匹配固定搜索域和验证样本计数，能重算固定 J，并具有有限的实测正训练耗时。无效或重复记录的轮次和排除原因写入决策记录。A 类别 F1 缺少每类独立批次证据时，可信权重为零。竞赛启用成本前向门槛，以逐时间前缀的中位数 log 秒数为对照。性能或成本代理质量失败时回退 Optuna TPE。既有 V1 运行按保存的协议恢复，通用回归的默认代理门槛沿用原设置。

## 2026-11-17 RAC-HPO 决策模型训练

`scripts/train_contest_sampler.py` 在 Conda `industrial` 中使用 PyTRIO LoRA SFT，复用竞赛 Sampler 的提示投影及参数校验。默认本地核对数据，`--train` 启动云端训练并使用 SwanLab 在线记录。A/B 训练任务缺少已采纳样本时才使用显式补充历史，C 留出始终取自主要历史。记录训练 loss、监督 token 数、留出格式通过率和 Sampler URI。使用方式见 [竞赛续训镜像](docs/CONTEST_HARNESS.md#在-conda-industrial-中训练决策模型)。

## 2026-11-17 RAC-HPO 竞赛续训接入

- `contest/rac_policy.py` 将固定父检查点的候选记录适配到共享 `RACSearchPolicy` 和固定目标 J。A 以类别 F1 损失分组，B 以轴承 MAE 分组，C 以发布子集 MAE 分组并保留发动机级误差统计。现有 RAC 核心复用 ExtraTrees 分组和成本代理、前向质量检查、全局探索及成本归一化采集函数。
- 第一轮执行基准参数续训，之后用 Optuna TPE 及其随机启动填充历史。第 9、10 轮可触发代理排序或全局探索，代理未通过质量检查则回退 TPE。按已提交轮次重建决策状态，配置、候选、实测训练耗时与代理诊断原子保存。
- RAC 策略从各任务原始检查点训练每个候选。采纳需同时改善主验证指标与 J，B 还执行原有逐轴承基线 RMSE 门槛。历史规则和 PyTRIO 策略使用其原有的选中父模型协议。Linux amd64 镜像的默认策略为 `rac_hpo`，实验和启动命令见 [竞赛续训镜像](docs/CONTEST_HARNESS.md)。

## 2026-11-17 Sampler 效果对照

新增 pytrio_base 策略，与 pytrio_sampler 共享同一采样适配器、响应解析、参数范围和采纳规则。基础模式要求空 Sampler 路径，微调模式要求已保存的 URI。

## 2026-11-17 PyTRIO Sampler 接入

新增 contest/sampler.py，以投影后的公开验证历史请求 PyTRIO，并对模型提出的训练参数做白名单校验。服务的 pytrio_sampler 策略复用原训练、重放及采纳门槛，并将采样证据写入轮次目录。

## 2026-11-16 竞赛续训镜像

新增 contest/continuation 在公开训练数据上组织定向或按轴承均衡采样，沿用原模型结构、标准化与 Adam 实现。task_aware_v3 通过子进程训练和重放，A 记录分类别 F1，B 按验证轴承设置相对原始检查点的门槛。原有本地 CLI 策略仍可读取历史运行。Dockerfile.harness 仅封装竞赛模块和固定 NumPy 依赖，默认运行三任务，每任务 10 轮。运行和预测接口见 [竞赛续训镜像](docs/CONTEST_HARNESS.md)。

## 2026-11-16 竞赛本地模拟

新增 contest/packages 负责原始 ZIP、检查点和文件摘要核验，contest/worker 在独立进程内调用各包训练／评估模块，contest/policy 提供有界的本地验证历史策略，contest/service 负责逐轮执行、原子提交与恢复。CLI 入口为 python -m rac_hpo.contest，使用 NumPy 1.26.4 独立环境。复用 _io 原子写入，不依赖 Qt 或 SQLite。输出在独立 workspace/contest_simulation，原始 A/B/C 包逐项隔离。当前支持 macOS／Linux 进程锁。PyTRIO 与正式 Harness 待官方协议接入。

## 2026-11-07 训练诊断、限时与评估一致性

- `TrainingResult.diagnostics` 为兼容的可选字典。回归训练记录训练 MAE、验证 MAE、差值、实际评估轮数及逐迭代验证曲线。统一 evaluator 增加 `overall_p95_absolute_error` 和工况 `p95_absolute_error`，采用样本绝对误差的线性插值 95% 分位数。最终 J 定义沿用现有实现。
- `optimization.trial_timeout_seconds` 默认为 null。应用服务传给回归 `train(..., timeout_seconds=None)`，包含基线和每个候选的构建、拟合及评估。取消优先于超时，树迭代前后和评估边界检查。超时抛出 `TrainingTimeout`，保存 failed、`failure_kind=training_timeout`、预算、实际耗时、超时量和完成轮数。基线超时终止实验，候选超时继续下一候选。单次原生调用可能超过限时。分类服务和固定轮数最终重训沿用各自预算语义。
- 每次完成的回归 trial 保存 `training_diagnostics`。实验顶层只对应实际选中模型，并额外原子保存可导出的 `training_diagnostics.json`。训练页绘制真实验证曲线和已选迭代，详情抽屉显示摘要，历史缺失字段显示空态。
- `finalize_experiment` 在准备数据前独占原子创建 `finalization_claim.json`。并发调用及中断后的重复调用在读取 test 前阻断，旧实验若已有孤立测试报告也阻断。执行标记失败后保留，已保存的报告和模型可供人工核查，应用不会自动重复评估。
- 回归和分类 evaluator 在字符串转换前检查工况/分组缺失值，拒绝空白标签。`environment_snapshot` 增加实际导入包的路径和源码哈希，独立输出工作区也能追溯实际实现。
- 二分类 `time_oof` 在原有 0.01–0.5 网格和训练期前向折外预测上保存 `working_points`，包含 FN、FP、两类错误率、召回、已选与网格内 Pareto 标记。选择规则和概率校准状态沿用现有协议，工业训练页只展示保存值。

Config / SQLite Schema 仍为 1，新增数据保存到兼容 JSON 字段及独立产物。真实实验和验证详见 `docs/PROJECT_IMPROVEMENT_20261107.md`。
>>>>>>> 20aa64b (完成RAC-HPO阶段三算法优化)

## 2026-11-04 总结文档与 Mac 对齐

`optimization/baselines` 增加惰性三档粗网格与资源策略。统一回归优化器增加 grid / successive_halving / hyperband；资源方法用随机候选、固定 study_name、Optuna 分层剪枝，runner 增加第三参数 report，仅此两种方法使用。`training.train` 增加可选 resource_callback(step, validation_mae)，其余调用兼容。完成记录与剪枝记录分别保存，剪枝不参与最佳选择；资源控制以模型 n_estimators 为上限，独立保留单模型早停。Config Schema 1 兼容增加 min_resource/reduction_factor，数据库不变。

`data/quality_audit` 只用 train 数值特征拟合 IQR，审计 train/validation，保存源行标记，不变更数据、manifest 或特征。两类应用服务保存独立质量产物；数据页和工业页展示真实审计。分类评价增加各类别漏报/误报率，原指标不变。CLI/GUI 回归提供新方法，工业分类不增加资源剪枝。

本机 Apple M5 / 10 核 / 16 GiB，CPU 原生 arm64；回归 4 线程、串行 trial。Mac Setup/Run-GUI.command 使用工程内环境与缓存、显式数据获取。详细边界及验证见 docs/SUMMARY_ALIGNMENT.md。

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
- `runtime.py`：决定工作区位置。源码运行用检出目录；打包的 macOS 应用用 `~/Library/Application Support/RAC-HPO`，读取构建时写入的 `build_info.json`。核心算法不依赖它。`packaging/macos/` 含 PyInstaller spec、构建与自检脚本，不属于运行时包。
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
