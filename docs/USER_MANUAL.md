# 智训引擎用户手册

适用日期：2026-10-31。App 元数据版本 0.3.0，算法版本 rac-hpo-0.2.0；包含尚未发布的自主优化与工业分类训练增量。本文按当前源码编写，不代表已提供安装包或生产部署。

配套阅读：[算法详解](ALGORITHM_GUIDE.md) · [工程说明](../README.md) · [工业来源审计](../datasets/INDUSTRIAL_SOURCES.md)。

## 1. 先选任务

| 你要解决的问题 | 使用入口 | 当前支持 |
| --- | --- | --- |
| 预测钢铁能耗或 CNC 剩余加工周期 | 数据管理 → 模型训练 → 超参数优化 | LightGBM 回归；七种搜索方法 |
| 预测故障类别 | 工业训练 | AI4I、SECOM、Paderborn；三种分类模型、三种搜索方法 |
| 演示发现退化后重新优化并审核候选 | 自主优化 | CNC 固定协议、单轮离线回放、本地模拟切换 |
| 查看和保存已有结果 | 实验对比、运行日志及各任务历史 | 保留真实指标、模型、配置与日志 |

XJTU-SY 当前只有完整寿命 RUL 回归导入审计，不能通过分类训练器训练。联想数据需要授权；Pneumatic 需要带来源证明且保留动作标签语义的本地规范化表。界面有入口不等于所有来源已经完成训练接入。当前没有 CNN/LSTM、生产自动上线或连续多轮优化。

## 2. 安装与启动

当前本机为 Apple M5、10核、16 GiB 的 Mac，使用原生 arm64 Python 3.11、回归4线程与串行候选。先安装 uv 和 `brew install libomp`，运行 `./Setup.command`，随后双击 `Run-GUI.command` 或终端 `./Run-GUI.command`。Mac CLI 将下文 `.venv\Scripts\python.exe` 替换为 `.venv/bin/python`。安装不会自动下载数据；使用 fetch 显式获取。

也支持 Windows 11。以下示例采用 Windows PowerShell 路径。

已有环境时双击 `Run-GUI.cmd`，或运行：

```powershell
.venv\Scripts\python.exe main.py
```

新环境先安装 uv，再双击 `Setup.cmd`。该脚本按锁文件配置项目内环境与缓存，并显式下载公开数据，需要网络。之后检查：

```powershell
.venv\Scripts\python.exe scripts\verify_environment.py
.venv\Scripts\python.exe -m rac_hpo --help
```

手动重新进行 editable 安装后，运行 `.venv\Scripts\python.exe -S scripts\configure_environment.py` 处理当前 Windows 中文路径兼容问题，不需要修改系统编码。

训练不会自动下载数据。下载和导入校验必须先完成。不要把任意 CSV 改名后当作已有数据集使用：适配器会核验来源、字段和固定划分。

## 3. 第一次完成回归实验

### 3.1 准备数据

进入“数据管理”，选择支持的数据集，检查来源、目标、特征、工况和固定划分，再执行导入。CLI 等价流程：

```powershell
.venv\Scripts\python.exe -m rac_hpo fetch --dataset steel_energy
.venv\Scripts\python.exe -m rac_hpo import --dataset steel_energy
```

钢铁数据预测 Usage_kWh，单位 kWh；只使用预先可获得的日历特征，工况为 weekday/weekend。按日期排序、边界留一天间隔，约按 60%/20%/20% 划分。

CNC 数据预测 CycleToFailure，单位 cycles；观察当前周期信号后预测剩余加工周期。968 行、14 把物理刀具，按整刀划分为 442/400/126 行。工况为 5 mm/10 mm 切深，刀具身份和未来寿命字段不作输入。

```powershell
.venv\Scripts\python.exe -m rac_hpo fetch --dataset cnc_milling_2025
.venv\Scripts\python.exe -m rac_hpo import --dataset cnc_milling_2025
```

### 3.2 训练基线

进入“模型训练”，检查数据集、种子及模型配置，运行默认参数基线。观察总体 MAE、分工况 MAE、耗时和结果状态。

```powershell
.venv\Scripts\python.exe -m rac_hpo train --dataset cnc_milling_2025 --seed 42 --estimators 300
```

基线用于判断搜索是否有收益。训练只拟合 train，validation 用于早停和选参。test 不用于此次运行。

### 3.3 搜索参数

进入“超参数优化”，选择算法、试验次数和时间预算，然后启动。首次体验可用 TPE；观察 RAC 代理行为建议设置 32–48 次，16 次以内通常仍在暖启动。

```powershell
.venv\Scripts\python.exe -m rac_hpo optimize --dataset cnc_milling_2025 --algorithm rac_hpo --max-trials 48 --timeout 120 --seed 42
```

回归可用 `random`、`grid`、`tpe`、`tpe_robust`、`rac_hpo`、`successive_halving`、`hyperband`。只有 `tpe_robust` / `rac_hpo` 按固定 J 选择，其余按总体 MAE 选择。Grid 为三档粗网格；资源方法在候选间分层剪枝，详情保留中间验证误差和资源，剪枝试验不参与最佳选择。因此“最佳 J”和“最佳 MAE”可能属于不同 Trial，不能混称一个最佳结果。

默认基线为 trial -1，不占 `max_trials`。时间预算在启动下一试验前检查，当前试验可以运行结束；基线初始化另计，总用时可能超过设置的搜索秒数。取消需要后台进程确认，已完成结果保留。

### 3.4 查看与导出

把命令返回的真实实验 ID 替换下面的 `EXP-ID`：

```powershell
.venv\Scripts\python.exe -m rac_hpo list
.venv\Scripts\python.exe -m rac_hpo show EXP-ID
.venv\Scripts\python.exe -m rac_hpo export EXP-ID
```

导出包含指标、Trial、配置、模型、图表及复现快照。先核对状态、所选 Trial、目标单位和固定划分，再使用结果。

## 4. 七个页面怎么用

| 页面 | 主要操作 | 阅读要点 |
| --- | --- | --- |
| 数据管理 | 选择、校验和导入数据 | 确认来源、目标、工况与固定划分 |
| 模型训练 | 运行基线、查看验证结果、取消和导出 | 基线与搜索的用途不同 |
| 超参数优化 | 配置搜索、筛选 Trial、查看图表与 RAC 诊断 | 区分 J 最优和 MAE 最优 |
| 实验对比 | 选择历史 Run 并排查看 | 原回归跨 Run 缺少完整可比证明，不生成排名 |
| 运行日志 | 搜索、复制、导出日志 | 清空显示不等于删除实验产物 |
| 自主优化 | 授权固定协议训练、回放、审查候选与模拟切换 | 单轮、离线、人工审批 |
| 工业训练 | 数据审计、分类基线/HPO、历史和比较 | 分类指标独立于回归 MAE |

左侧图标悬停显示页面名。宽屏 Trial/Run 列表位于左侧，小窗口通过列表按钮打开。最小窗口为 720×560。

优化页搜索、状态筛选和参数刷选共同决定可见 Trial。点击行只切换观察对象；勾选用于并排查看，两者独立。支持勾选 2–8 条；被过滤隐藏的勾选仍保留，比较前检查提示。完整优化历史保留全量累计最优，其他图表按其标注的过滤范围阅读。

启动可能显示最近真实历史搜索。查看历史不会改变新任务预算或种子；全局任务栏取消的是当前后台任务，需要时点击“返回当前任务”。空白分析面板可能表示没有逐样本预测、残差或重要性接口，不代表系统已计算出零值。

## 5. 工业分类训练

### 5.1 数据与模型

| 数据 | 性质与任务 | 必须知道的限制 |
| --- | --- | --- |
| AI4I 2020 | 官方合成维护数据，故障二分类；工况 L/M/H | 不能当真实工厂验证；少数工况故障极少 |
| SECOM | 真实半导体数据，pass/fail 分类 | 只有 overall，无已核验工艺工况；类别失衡明显 |
| Paderborn | 真实实验台，健康/外圈/内圈分类 | 当前小子集仅 9 把轴承；按整轴承分组；许可 CC BY-NC 4.0 |

支持 `random_forest`、`xgboost`、`lightgbm`。缺失值填补与编码只在训练折拟合。Random Forest 没有逐轮验证学习曲线，界面会说明原因。

### 5.2 推荐流程

进入“工业训练”，选择数据并显式获取或提供本地路径，先审计，再运行基线，最后在相同模型、划分和资源条件下搜索。

```powershell
.venv\Scripts\python.exe -m rac_hpo industrial fetch --dataset ai4i_2020
.venv\Scripts\python.exe -m rac_hpo industrial audit --dataset ai4i_2020
.venv\Scripts\python.exe -m rac_hpo industrial train --dataset ai4i_2020 --model lightgbm --threads 2 --seed 42
.venv\Scripts\python.exe -m rac_hpo industrial optimize --dataset ai4i_2020 --model lightgbm --algorithm rac_hpo --max-trials 48 --timeout 300 --threads 2 --seed 42
.venv\Scripts\python.exe -m rac_hpo industrial list
.venv\Scripts\python.exe -m rac_hpo industrial show IND-ID
.venv\Scripts\python.exe -m rac_hpo industrial compare IND-ID-1 IND-ID-2
```

本地文件用 `--data`，例如 `industrial audit --dataset paderborn --data path\to\local.zip`。归档会在工程内安全解压和校验；重复使用前核对缓存，不要手动修改缓存文件。

分类三种搜索 `random`、`tpe`、`rac_hpo` 都按同一固定 J 选择，区别于旧回归入口。默认分类模型上限 120 棵树、2 线程，默认搜索 24 次/300 秒。若要更多代理决策机会可提高次数，但代理质量不通过仍会回退。

### 5.3 怎么读分类结果

- balanced accuracy：各类别召回率的平均，越大越好；比普通 accuracy 更能暴露类别失衡。
- macro F1：各类 F1 的平均，越大越好，同时关注精确率和召回率。
- log loss：预测概率的损失，越小越好；不等于错误率。
- 每类召回：特别检查故障类，不能只看总体数字。
- 分类 J：对各工况 balanced error 做基线归一化后的固定目标，越小越好。

当前正式记录中，SECOM 的选中模型故障召回为 0，Paderborn 的选中模型外圈损伤召回为 0。这些结果不能用于生产故障判定。完整数值和实验条件见[工业训练报告](INDUSTRIAL_TRAINING_REPORT.md)。分类当前没有新增最终测试命令，禁止把回归 `finalize` 套到 IND 实验。

## 6. 自主优化：单轮离线演示

此页只适用于固定 CNC 协议，不能直接监控新增分类数据，也不会连接生产系统。

1. 核对固定数据角色、训练预算和授权范围，勾选授权后建立会话。
2. 系统训练初始冠军，按 20 行批次回放刀具 5，再回放刀具 8。整刀结束才释放后验寿命标签。
3. 质量异常阻断并要求检查；无标签分布变化只提示观察。有标签误差达到条件才形成退化提案。
4. 授权范围内最多执行一次 HPO，冻结候选后只做一次门禁。
5. 总体 MAE 不超过冠军 1.02 倍、各工况不超过 1.05 倍（均另加 1e-8）才可能通过；还必须通过模型哈希、特征顺序和预测检查。
6. 通过后仍需人工决定是否切换本地模拟槽位。后续在相同行上配对观察；必要时人工回滚初始冠军。

总体改善而某工况退化仍会被拒绝。门禁按来源和行指纹在工作区限制一次，换会话不能重试另一个候选；不要删除记录以反复选模型。无自然退化时可显式演示，但不能称为自然触发。

CLI 例子如下，ID 和 revision 均取真实返回值：

```powershell
.venv\Scripts\python.exe -m rac_hpo loop create --authorize-training
.venv\Scripts\python.exe -m rac_hpo loop run LOOP-ID
.venv\Scripts\python.exe -m rac_hpo loop show LOOP-ID
.venv\Scripts\python.exe -m rac_hpo loop export LOOP-ID
```

`promote`、`rollback`、`decline` 均要求 `--expected-revision`，应先查看最新会话再提交人工操作。详细授权、状态和命令见[闭环说明](CONTROLLED_LOOP.md)。闭环实验不能运行 `finalize`；模型切换只是本地模拟，不构成生产部署。

## 7. 保存位置与最终评估

| 内容 | 位置 |
| --- | --- |
| 原始数据、来源、清单 | `datasets/raw`、`datasets/SOURCES.md`、`datasets/manifests` |
| 工业分类来源与解压缓存 | `datasets/INDUSTRIAL_SOURCES.md`、`datasets/processed/industrial` |
| 原回归实验 | `workspace/experiments/EXP-*`，同时保存 SQLite 元数据 |
| 工业分类实验 | `workspace/industrial_runs/IND-*`，独立追加文件，不写旧实验 SQLite |
| 历史验收依据 | `docs/*REPORT.md` 与 `workspace/verification` |

以每次命令返回的真实路径为准。保留模型、完整配置、manifest、环境快照、日志及原数据校验值，只有模型文件通常不足以复现。

原回归普通实验在方法和参数已固定后，可显式运行一次最终评估：

```powershell
.venv\Scripts\python.exe -m rac_hpo finalize EXP-ID
```

它固定已选参数和验证早停轮数，用 train+validation 重训，然后读取 test，单独保存结果。不要依据 test 再选参数、改算法或反复筛选赢家。本手册生成过程未执行该命令。

## 8. 常见问题

| 现象 | 检查与处理 |
| --- | --- |
| 启动提示依赖缺失 | 用项目 `.venv` 启动；运行环境验证，必要时重新执行 Setup |
| 数据不存在 | 先显式 fetch，再 import/audit；检查本地路径与数据集选择 |
| 来源或缓存哈希不符 | 查看报错文件，核对来源；不要绕过校验或覆盖历史 manifest |
| RAC 一直显示 TPE 回退 | 看 reason、完成次数、前向检验；16 次成功历史只是最低门槛 |
| J 更好但 MAE 更差 | J 还惩罚最弱工况，逐工况核对；两种指标不等价 |
| 预算到了仍在运行 | 当前 Trial 可完成，基线另计；查看初始化、搜索和总耗时 |
| 点击取消后未立即停止 | 等待工作进程与训练回调确认，不把按钮点击当作终止成功 |
| 比较没有排名 | 缺少公平可比证据或配置不一致，按并排数据阅读 |
| 重启后任务为 interrupted | 中断记录保留，系统不会自动重训；检查日志再决定新任务 |
| 模型在中文路径无法重载 | 回归 LightGBM 用 `rac_hpo.training.model_export.load_model(path)` |
| 数据库版本未知 | 停止写入，先备份并核验兼容性，禁止直接删除数据库解决 |

## 9. 一次实验结束前核对

确认数据来源与目标正确；训练/验证/测试划分固定；比较条件一致；检查最弱工况与少数类；保存实际 ID、配置和模型；如实标记失败、取消和未验证内容。当前实验不支持“RAC 已全面优于 TPE”“可信度已经校准”或“可直接生产上线”的结论。
