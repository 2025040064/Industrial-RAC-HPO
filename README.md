# 智训引擎 · 工业模型训练与超参数优化

使用指南：[中文用户手册](docs/USER_MANUAL.md) · [RAC-HPO 算法详解](docs/ALGORITHM_GUIDE.md)。覆盖当前七页工作台、回归与分类训练、CLI、离线闭环和结果解读。

新增工业数据审计与分类训练入口：工作台第七页“工业训练”和 CLI `industrial`。支持 AI4I / SECOM / Paderborn 独立适配，Random Forest / XGBoost / LightGBM，以及同目标、同预算的 Random / TPE / RAC-HPO。AI4I 为官方合成基准，不能称真实生产数据；SECOM 没有已核验工艺工况。当前交付范围与实际实验见 [工业训练报告](docs/INDUSTRIAL_TRAINING_REPORT.md)，其他来源的授权、本地导入和任务限制见 [来源审计](datasets/INDUSTRIAL_SOURCES.md)。

```powershell
.venv\Scripts\python.exe -m rac_hpo industrial fetch --dataset ai4i_2020
.venv\Scripts\python.exe -m rac_hpo industrial fetch --dataset secom
.venv\Scripts\python.exe -m rac_hpo industrial fetch --dataset paderborn
.venv\Scripts\python.exe -m rac_hpo industrial audit --dataset secom
.venv\Scripts\python.exe -m rac_hpo industrial audit --dataset paderborn --data path\to\local.zip
.venv\Scripts\python.exe -m rac_hpo industrial train --dataset secom --model xgboost --threads 2
.venv\Scripts\python.exe -m rac_hpo industrial train --dataset secom --model lightgbm --decision-mode time_oof --threads 2
.venv\Scripts\python.exe -m rac_hpo industrial optimize --dataset paderborn --model lightgbm --algorithm rac_hpo --max-trials 24 --threads 2
.venv\Scripts\python.exe scripts\run_industrial_benchmarks.py --datasets ai4i_2020 secom paderborn --seeds 42 71 103 --trials 24 --threads 2
```

`time_oof` 是可选的二分类时序阈值策略：只用训练分区内部的前向预测选阈值，额外训练三个折并固定树数；原有默认决策不变。它不支持轴承分组数据，不保证改善失效召回或误报，具体实验见 [算法优化报告](docs/INDUSTRIAL_ALGORITHM_OPTIMIZATION_REPORT.md)。工作台“工业训练”页可选择决策策略，详情中保留阈值、折的时间与类别指标。

分类实验追加保存到 `workspace/industrial_runs/IND-*`，配置、固定划分、模型、曲线和日志齐全；不修改原实验 SQLite。分类界面和比较不会将 balanced accuracy / macro F1 / log loss 混为回归 MAE。训练不隐式下载，不用 test 选参；单独基线的 balanced error 与搜索 J 不混排。Paderborn / XJTU 归档解压至工程内 `datasets/processed/industrial`，重复审计与训练复用前校验原归档和解压文件哈希。当前不新增分类最终测试入口。XJTU-SY 保留 RUL 回归导入审计，尚未接本分类训练器；联想须授权，Pneumatic 须按真实操作动作标签提供带来源证明的本地表。1D-CNN/LSTM 与新数据的漂移、持续优化属于后续阶段。

项目新增受控单轮离线闭环：CNC 整刀回放 → 质量/分布/有标签诊断 → 会话授权下真实 HPO → 一次候选门禁 → 人工确认本地模拟切换 → 配对观察与人工回滚。RAC-HPO 仍是核心算法，现有五页工作台保留，新增第六页“自主优化”。App 元数据仍为 0.3.0，本轮为未发布增量，未制作安装包。

协议、CLI、状态与限制见 [闭环说明](docs/CONTROLLED_LOOP.md)，真实结果与验证见 [交付报告](docs/CONTROLLED_LOOP_REPORT.md)。首次使用在 GUI 的“自主优化”页核对固定协议与预算，勾选授权再开始；候选即使总体 MAE 改善，也必须满足各工况门禁。仅有本地模拟槽位，没有生产部署。

当前 App 0.3.0，阶段 0–3 已接入真实 UCI 钢铁能耗与 CNC Milling 2025 数据，支持 LightGBM、Random、Optuna TPE、固定鲁棒 TPE 和 RAC-HPO，配有 SQLite 实验记录及 PySide6 白色桌面工作区。算法可独立通过 CLI 运行。

阶段 2、3 的真实验收见 [交付报告](docs/PHASE_2_3_REPORT.md)。CNC 同预算三种子试跑中，RAC-HPO 平均固定目标 J 略优于普通 TPE，但总体 MAE 略差；每个验证工况只有两把刀具，可信薄弱工况加权分支尚无实证收益证明。

统一规范见 [ARCHITECTURE.md](ARCHITECTURE.md)，原始总纲保存在 [docs](docs/RAC-HPO_Implementation_Architecture_v1.md)。实施记录见 [PLAN.md](PLAN.md)。

## 环境与启动

当前本机为 macOS 26.6 / Apple M5（arm64、10 核、16 GiB）。已采用原生 CPU 环境，回归默认每模型 4 线程、候选串行，工业分类默认 2 线程；不配置 GPU。首次需 uv 和 OpenMP（`brew install libomp`），然后运行：

```sh
./Setup.command
./Run-GUI.command
.venv/bin/python -m rac_hpo fetch --dataset cnc_milling_2025
.venv/bin/python -m rac_hpo optimize --dataset cnc_milling_2025 --algorithm hyperband --max-trials 24
```

也可双击 `Run-GUI.command`。安装脚本按锁文件安装，环境/缓存/临时文件保存在工程内；数据下载为显式操作。以下 PowerShell 命令保留供 Windows 使用，Mac 对应解释器为 `.venv/bin/python`。

回归新增粗网格 `grid`、`successive_halving` 和 `hyperband`；后两者按验证 MAE 在候选间做分层资源淘汰，与单模型早停分别记录。数值特征极值/缺失只标记审计，不自动删除或加入特征。分类增加各类别漏报/误报率。对齐范围、算法口径和实测见 [总结文档对齐记录](docs/SUMMARY_ALIGNMENT.md)。

Windows 11、Python 3.11；依赖版本由 pyproject.toml 和 uv.lock 固定。已配置的本地环境可以直接双击 `Run-GUI.cmd`，或在项目目录运行：

```powershell
.venv\Scripts\python.exe main.py
```

新环境先安装 uv，再运行 `Setup.cmd`。该脚本将 Python、依赖缓存、临时文件和虚拟环境保存在本项目，按锁文件安装并显式下载官方公开数据。不会隐式升级全部依赖。

Python 3.11 的 Windows editable 安装需要处理中文目录编码，Setup 已自动运行 `python -S scripts/configure_environment.py`。手动重新安装 editable 包后也请运行此命令。系统编码无需更改。

```powershell
.venv\Scripts\python.exe scripts\verify_environment.py
.venv\Scripts\python.exe -m rac_hpo --help
.venv\Scripts\python.exe -m rac_hpo fetch
.venv\Scripts\python.exe -m rac_hpo import
.venv\Scripts\python.exe -m rac_hpo train --seed 42 --estimators 300
.venv\Scripts\python.exe -m rac_hpo optimize --algorithm tpe --max-trials 16 --timeout 120
.venv\Scripts\python.exe -m rac_hpo optimize --algorithm random --max-trials 16 --timeout 120
.venv\Scripts\python.exe -m rac_hpo optimize --algorithm tpe_robust --max-trials 16 --timeout 120
.venv\Scripts\python.exe -m rac_hpo fetch --dataset cnc_milling_2025
.venv\Scripts\python.exe -m rac_hpo import --dataset cnc_milling_2025
.venv\Scripts\python.exe -m rac_hpo train --dataset cnc_milling_2025 --seed 42
.venv\Scripts\python.exe -m rac_hpo optimize --dataset cnc_milling_2025 --algorithm rac_hpo --max-trials 48 --timeout 120
.venv\Scripts\python.exe scripts\run_cnc_benchmarks.py --seconds 10 --seeds 42 71 103
.venv\Scripts\python.exe -m rac_hpo list
.venv\Scripts\python.exe -m rac_hpo show EXP-ID
.venv\Scripts\python.exe -m rac_hpo export EXP-ID
```

`--root` 可指定包含 configs/default.yaml 的其他工作目录，放在子命令之前。训练与搜索无 Qt 依赖，运行中不会下载数据。缺失文件与非法配置明确失败；CLI 失败返回非零退出码。

## 数据、工况与限制

数据来自 [UCI Steel Industry Energy Consumption](https://archive.ics.uci.edu/dataset/851/steel+industry+energy+consumption)，许可 CC BY 4.0，DOI 10.24432/C52G8C。真实 CSV 有 35,040 条记录、11 列，目标 Usage_kWh，单位 kWh。来源、引用和字段说明见 [datasets/SOURCES.md](datasets/SOURCES.md)。原始数据默认不纳入版本管理，可按官方下载并核验 SHA-256。

本轮任务为日历条件下的能耗回归，使用 hour、minute、day_of_week、month、is_weekend。排除 Load_Type、CO2、同时刻无功功率、功率因数等未证明预测时可获得的输入。工况为预先确定的 weekday / weekend。日期块仅反映时间相关性；数据没有已核验的独立机床、刀具或加工批次标识。

按日期排序，在训练 / 验证 / 测试边界各留 1 天间隔，再按固定约 60% / 20% / 20% 整日划分。manifest 保存源行映射、所有划分索引、日期、特征顺序和源文件校验。模型只在训练集拟合，验证集早停和选参，测试集封存。预处理无填补、缩放或目标编码，日历派生不拟合统计量。

CNC 数据来自 [作者 Figshare 发布集](https://doi.org/10.6084/m9.figshare.28589216.v1)，许可 CC BY 4.0；968 个真实加工周期、14 把物理刀具，使用作者的 120 个信号聚合特征及 5 项工艺元数据，预测剩余加工周期 CycleToFailure（cycles）。观测当前周期信号后才预测；身份、周期序号及未来寿命标签均不作为输入。按整把刀具固定划分为 442 / 400 / 126 行，工况为预先设置的 5 mm / 10 mm 切深。每个验证工况仅两把刀具，默认最少五个独立单元的要求不满足，因此不输出工况置信区间，可信关注权重 q=0。不能据此证明跨机床泛化或可信加权的收益。另已下载核验 NASA Milling，尚未接入训练；详情见来源记录。

## 训练、搜索与存储

LightGBM 使用默认的六项模型参数，显式统一最多 300 棵树、30 轮早停、4 个线程，固定 seed。所有搜索复用同一训练器、六维搜索空间及划分。TPE 默认前 10 次为随机暖启动；12 次以上才覆盖 TPE 驱动的选参。

每次搜索先训练默认基线并固定各工况 B_g；工况权重由固定验证样本占比确定。固定目标 J 的 alpha=0.3、epsilon=1e-8 均写入快照。Random / TPE 按总体 MAE 选择，tpe_robust / rac_hpo 按 J 选择，所有方法同时保存两类指标。可靠性默认至少需要 5 个真实独立单元；日期块不会被升级为独立实验，独立单元充分时的分组 bootstrap 仍是近似区间。

RAC-HPO 默认前 16 次使用 TPE 暖启动，之后用 ExtraTrees 分工况性能与成本代理、前向质量检查、全局探索和改善/成本排序。代理不合格或异常时明确回退 TPE；建议至少 32–48 次试验，短任务可能全部处于暖启动。代理每 4 个已完成试验重拟合，缓存年龄、选择耗时、预测、工况权重和回退原因逐次记录。树离散度与前向残差重采样未校准，预测总体退化筛选不构成真实误差硬保证；最终报告始终保留固定 J 与原始 MAE。

`max_trials` 不包含默认基线预跑（trial -1），初始化、搜索和总耗时分别记录。时间预算在新试验启动前检查；已运行的单次试验可完成，超时量单独保存。取消请求经工作进程与树迭代回调确认后才显示 cancelled，已完成试验继续保留。失败试验保存原因并按搜索策略继续。

每次实验在 workspace/experiments/EXP-... 中独立保存 manifest、完整配置、依赖锁与环境、trials.jsonl、指标、日志、真实模型及真实收敛图；SQLite 保存同一实验和试验元数据。导出生成新目录，包含 JSON / CSV / Markdown / PNG / 模型及复现快照。未知数据库版本会阻断并要求显式备份迁移，不隐式改变旧记录。

在中文路径重载模型时，使用 `rac_hpo.training.model_export.load_model(path)`。它先以 UTF-8 读取文本再交给 LightGBM，已验证重载预测与原模型一致；LightGBM 的原生文件路径接口在当前 Windows 环境不能读取中文路径。

搜索完成后可按既定流程显式最终评估一次：

```powershell
.venv\Scripts\python.exe -m rac_hpo finalize EXP-ID
```

该流程固定已选超参数和验证早停轮数，合并训练与验证集重训，再读取测试集；结果单独保存。不要用测试结果再次选择方法或参数。旧实验的测试记录不会覆盖。

## GUI 已接入功能

五页采用固定56px图标导航和顶部上下文栏。导航只显示当前图标Tooltip；宽屏优化页为Trials+分析区，对比页为Runs+概览/并排查看，小窗口通过按钮打开列表。最小720×560，图表按容器宽度重排。

数据管理保留真实导入、来源/字段/工况/固定划分。模型训练保留配置、基线、验证工况、取消、结果和导出。超参数优化提供当前七种回归方法、四项真实KPI、平行坐标与参数刷选、完整优化历史、过滤分布/参数散点、状态与RAC诊断。

列表搜索、状态筛选和brush统一联动，排序后分页。行点击高亮，勾选独立控制2–8条并排查看，详情通过显式按钮打开；过滤隐藏的勾选保留并提示。最佳objective和最佳MAE分别注明Trial，MAE使用目标真实单位，J无量纲。基线-1不进入搜索统计。

启动显示最近真实搜索（含失败/取消）并标为历史。查看历史不改变新任务文件、算法、预算或种子；全局任务栏取消当前后台任务，“返回当前任务”切回活动实验。所有长任务使用独立进程，进度按实验ID隔离。

跨Run并排表展示已选模型指标与数据、单位、预算和固定目标；当前接口缺少固定split及目标/特征版本证明，因此不生成排名。参数重要性、逐样本预测、残差、质量和过程统计缺少接口时显示清楚空态，不补造数据。日志页显示当前会话事件，支持搜索、复制、导出、手动滚动与清空显示。

维护规范见[UI_DESIGN.md](UI_DESIGN.md)，当前验收见[五页工作台V2交付报告](docs/UI_WORKBENCH_V2_REPORT.md)。重现验证使用`scripts/verify_ui_workspace.py`：默认在隔离目录显示真实历史；`--exercise`执行真实训练、搜索、导出和取消；`--native`使用Windows原生Qt；`--scale 2`验证双倍缩放。验证不调用finalize。

## 测试与后续

```powershell
.venv\Scripts\python.exe -m pytest --basetemp .cache\pytest
```

测试包含评分与非法配置、时间划分与来源、训练 / 搜索 / SQLite / 模型 / 导出，以及离屏 Qt 真实后台任务。仅针对边界规则的单元测试构造输入，不把这些输入或指标当作工业训练成果。

阶段 0、1 历史验收见 [原报告](docs/PHASE_0_1_REPORT.md)；既有算法实验见 [阶段 2、3 报告](docs/PHASE_2_3_REPORT.md)。后续仍需增加独立刀具与外部工况，扩大同预算多种子对照并做代理、成本、可信权重消融。多轮持续优化、LLM 和打包发布未实施；新增工业数据与分类模型的范围见本文顶部。

