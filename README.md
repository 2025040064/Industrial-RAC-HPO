# 智训引擎 · 工业模型训练与超参数优化

<<<<<<< HEAD
使用指南：[跟着做（实操手册）](docs/PRACTICAL_GUIDE.md) · [中文用户手册](docs/USER_MANUAL.md) · [RAC-HPO 算法详解](docs/ALGORITHM_GUIDE.md)。覆盖当前七页工作台、回归与分类训练、CLI、离线闭环和结果解读。
=======
竞赛 V2 已接入官方 Harness SDK 1.0.2 的训练和预测回调。提交候选按赛事要求使用 Linux/amd64 单镜像未压缩 tar，已完成本地真实模型联调、公开验证对照和禁网容器验收。赛事宿主实际结果以用户发起的试运行为准。见 [首次试运行预检](docs/submission_preflight.md)。

竞赛续训已接入 `--policy rac_hpo`，支持 A/B/C 每项最多 10 轮 CPU 续训。Linux amd64 续训镜像默认启用 RAC-HPO，运行说明和公开验证结果见 [竞赛续训镜像](docs/CONTEST_HARNESS.md)。

竞赛续训支持显式配置 PyTRIO Sampler，见 [运行与挂载说明](docs/CONTEST_HARNESS.md#pytrio-sampler-模式)。

竞赛续训镜像的构建、输入挂载与预测命令见 [竞赛续训镜像](docs/CONTEST_HARNESS.md)。

初版 A/B/C 本地规则模拟实训各完成 10 轮真实检查点续训，使用独立 NumPy 1.26.4 环境。正式赛事平台启动和隐藏评测协议待核验。见 [初版运行指南](docs/CONTEST_SIMULATION.md) 和 [实训报告](docs/CONTEST_SIMULATION_REPORT.md)。

使用指南：[中文用户手册](docs/USER_MANUAL.md) · [RAC-HPO 算法详解](docs/ALGORITHM_GUIDE.md)。覆盖当前七页工作台、回归与分类训练、CLI、离线闭环和结果解读。
>>>>>>> 20aa64b (完成RAC-HPO阶段三算法优化)

2026-11-07 增量增加回归训练/验证 MAE 差距、总体及工况 P95 绝对误差、真实验证学习曲线，以及可选的单次训练限时。CLI `train` / `optimize` 使用 `--trial-timeout 10`，GUI 训练和优化页提供同一控制。限时包括基线，按树迭代和评估边界协作检查，可能超过设定值并保存超时量。分类 `time_oof` 新增 50 个训练期阈值工作点及网格内 Pareto 标记。最终评估增加持久化的一次性执行保护，中断后保留执行标记。实测与限制见[本轮改进报告](docs/PROJECT_IMPROVEMENT_20261107.md)。

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

项目支持 Windows 和 macOS，使用 Python 3.11；依赖版本由 pyproject.toml 和 uv.lock 固定。

### macOS 双击即用（免安装版）

Apple Silicon、macOS 14 及以上。把 `智训引擎-<版本>-macOS-arm64.dmg` 里的应用拖进「应用程序」，双击打开。不需要 Python、uv、Homebrew 或终端；LightGBM 所需的 OpenMP 已内置。

- 首次打开：应用未做 Apple 开发者签名与公证（仅 ad-hoc 签名）。若提示“无法验证开发者”，在应用上右键 → 打开，或到「系统设置 → 隐私与安全性」点“仍要打开”，只需一次。
- 数据：打开「数据管理」，点「下载官方数据」，再点「导入并校验数据」。下载走官方地址并校验 SHA-256。
- 工作区位置：`~/Library/Application Support/RAC-HPO`（配置、数据、实验历史、SQLite），升级或删除应用不会丢失；可用环境变量 `RAC_HPO_HOME` 指向别处。
- 命令行（可选）：`"/Applications/智训引擎.app/Contents/MacOS/RAC-HPO"` 只启动界面；完整 CLI 仍使用下面的开发环境。

自行构建安装包：在 Finder 双击 `Build-macOS-App.command`，或运行 `./packaging/macos/build_app.sh`，产物在 `dist/`。构建用独立环境，不影响 `.venv`；首次需联网。

### macOS 开发环境

首次使用需要联网、`uv` 和 LightGBM 依赖的 OpenMP 运行库。Apple Silicon 用户可先通过 Homebrew 安装：

```bash
brew install uv libomp
```

在项目目录运行一次安装脚本，再启动界面：

```bash
./Setup.command
./Run-GUI.command
```

也可在 Finder 中双击这两个 `.command` 文件；若没有执行权限，在项目目录执行 `chmod +x Setup.command Run-GUI.command`。安装脚本使用项目内的 `.venv`、`.python` 和 `.cache`，会根据锁文件安装依赖；不自动下载数据。macOS 安装同版本的 PySide6 Essentials，包含程序使用的 Qt 核心、图形和控件，不下载未用到的 Qt 附加组件；Windows 依赖保持 PySide6 不变。已有项目内 `.cache/bootstrap/bin/uv` 时无需另行安装全局 uv。训练命令使用 `.venv/bin/python -m rac_hpo --help` 查看；数据通过 CLI 显式获取或在界面中导入。图形运行需 macOS 桌面会话，首次启动可能需要一些时间。

### Windows

已配置的本地环境可以直接双击 `Run-GUI.cmd`，或在项目目录运行：

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

数据管理保留真实导入、来源/字段/工况/固定划分。模型训练保留配置、基线、验证工况、取消、结果和导出。超参数优化提供当前四种方法、四项真实KPI、平行坐标与参数刷选、完整优化历史、过滤分布/参数散点、状态与RAC诊断。

列表搜索、状态筛选和brush统一联动，排序后分页。行点击高亮，勾选独立控制2–8条并排查看，详情通过显式按钮打开；过滤隐藏的勾选保留并提示。最佳objective和最佳MAE分别注明Trial，MAE使用目标真实单位，J无量纲。基线-1不进入搜索统计。

启动显示最近真实搜索（含失败/取消）并标为历史。查看历史不改变新任务文件、算法、预算或种子；全局任务栏取消当前后台任务，“返回当前任务”切回活动实验。所有长任务使用独立进程，进度按实验ID隔离。

跨Run并排表展示已选模型指标与数据、单位、预算和固定目标；当前接口缺少固定split及目标/特征版本证明，因此不生成排名。参数重要性、逐样本预测、残差、质量和过程统计缺少接口时显示清楚空态，不补造数据。日志页显示当前会话事件，支持搜索、复制、导出、手动滚动与清空显示。

维护规范见[UI_DESIGN.md](UI_DESIGN.md)，当前验收见[五页工作台V2交付报告](docs/UI_WORKBENCH_V2_REPORT.md)。重现验证使用`scripts/verify_ui_workspace.py`：默认在隔离目录显示真实历史；`--exercise`执行真实训练、搜索、导出和取消；`--native`使用当前系统的原生 Qt；`--scale 2`验证双倍缩放。验证不调用finalize。

## 测试与后续

```powershell
.venv\Scripts\python.exe -m pytest --basetemp .cache\pytest
```

测试包含评分与非法配置、时间划分与来源、训练 / 搜索 / SQLite / 模型 / 导出，以及离屏 Qt 真实后台任务。仅针对边界规则的单元测试构造输入，不把这些输入或指标当作工业训练成果。

阶段 0、1 历史验收见 [原报告](docs/PHASE_0_1_REPORT.md)；既有算法实验见 [阶段 2、3 报告](docs/PHASE_2_3_REPORT.md)。后续仍需增加独立刀具与外部工况，扩大同预算多种子对照并做代理、成本、可信权重消融。多轮持续优化与 LLM 未实施；macOS 免安装包已可构建，但未做 Apple 签名与公证，Windows 打包未实施。新增工业数据与分类模型的范围见本文顶部。

## 作者与许可

作者 / 维护者：Yraguo。代码以 Apache License 2.0 发布，见 [LICENSE](LICENSE)。数据集本身不随仓库分发，各来源的许可与引用要求见 [数据来源](datasets/SOURCES.md)。

