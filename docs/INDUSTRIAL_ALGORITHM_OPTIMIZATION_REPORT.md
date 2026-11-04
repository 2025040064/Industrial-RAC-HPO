# 工业训练与 RAC-HPO 优化实验报告

日期：2026-10-31。现有工程增量实现，实验使用原始数据和原有固定划分，不覆盖历史实验。本文结果是开发验证结果，不是现场验收，也不证明模型可用于生产。

## 做了什么

1. 重载并校验原模型、来源哈希和固定划分，复现 SECOM 失效样本全漏判，以及 Paderborn 外圈损伤全漏判。可执行 `scripts/reproduce_industrial_weakness.py` 重现；传入 `--require-positive-recall` 时，实际为零召回会返回非零状态。
2. 仅在 SECOM 原训练分区内部按时间划出较早的 660 行和较晚的 280 行（其中失效 10 行）进行开发探针。未加权默认阈值召回 0/10；用更早训练数据的前向折外预测选出的 0.04 阈值召回 2/10、该 280 行中误报为 0。训练侧折外结果的误报率约 8.4%，不能据此保证新数据的误报率。类别权重方案在这个开发探针上召回 1/10，因此没有设为默认。具体配置、结果和警告见 `workspace/verification/industrial-optimization/imbalance_probe.{py,json,log}`。
3. 新增可选 `time_oof` 策略：只用训练分区的三个严格前向折拟合预处理和模型，再用折外概率选平衡准确率最高的阈值，同分取较高阈值；最终拟合固定树数并禁用早停。原 `native` 行为保持默认。概率没有校准，阈值不代表已验证的生产成本最优值。前向验证和阈值选择的相关背景见 scikit-learn 的 [TimeSeriesSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html) 和[阈值选择示例](https://scikit-learn.org/stable/auto_examples/model_selection/plot_cost_sensitive_learning.html)。
4. 明确拒绝跨时序折、训练和外部验证集的已知分组重叠；物理轴承和缺少可靠时间或足够类别样本的任务不支持该策略。SECOM 未提供设备或批次 ID，无法确认未知设备或批次之间是否重叠。
5. 单工况 RAC 代理训练此前触发 sklearn 单列目标形状告警；先以失败测试重现，改为一维目标后警告消失，多工况预测和代理质量门槛不变。新增平均精确率、类别召回与混淆矩阵的工作台查看入口，以及阈值、每折时间边界和行索引哈希记录。

主要修改文件：`src/rac_hpo/training/threshold.py`、`training/classification.py`、`evaluation/classification.py`、`optimization/rac_hpo/surrogate.py`、`application/industrial_service.py`、`interfaces/cli.py`、`interfaces/gui/pages/industrial_page.py`；基准脚本、相关测试、README、ARCHITECTURE、PLAN 和 CHANGELOG 同步更新。新增的重现、消融与证据提取脚本保存在 `scripts/reproduce_industrial_weakness.py` 和 `workspace/verification/industrial-optimization/`。未迁移数据库、覆盖旧模型或新增依赖。

## 真实 SECOM 搜索对照

数据集原训练／验证／测试分别为 940／313／314 行，验证集包括 11 个 fail 与 302 个 pass；数据来源、版本和哈希见实验清单。原验证集已在前一轮被观察过，本轮又用于搜索选参，因此这些结果只反映该开发验证集，不能当作新的独立泛化证明。测试样本未参与训练或选参，也没有用于本报告的评估。

三种方法均使用 LightGBM、相同固定训练／验证划分、相同搜索空间和归一化 J、`time_oof` 三折、120 棵树、2 线程，种子 42／71／103；各搜索最多 24 次、墙钟上限 300 秒，基线初始化单独计时。九组均完成 24 次且公平性校验通过。数值为三个种子的均值 ± 样本标准差；这些种子共用一份验证集，不能视为三个独立数据集。误报率的分母是 302 个正常件。

| 方法 | 平衡准确率 | 固定目标 J，越低越好 | 失效召回率 | 正常件误报率 | 搜索耗时均值 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Random Search | 0.5506 ± 0.0141 | 0.8842 ± 0.0278 | 24.24% | 14.13% | 27.36 s |
| Optuna TPE | 0.5897 ± 0.0477 | 0.8073 ± 0.0939 | 36.36% | 18.43% | 32.91 s |
| RAC-HPO | 0.5897 ± 0.0477 | 0.8073 ± 0.0939 | 36.36% | 18.43% | 33.16 s |

按种子查看，RAC 与 TPE 的选中模型结果完全相同：种子 42 检出 4/11、误报 75/302；种子 71 检出 3/11、误报 42/302；种子 103 检出 5/11、误报 50/302。对应报警精确率分别为 4/79、3/45 和 5/55。这些漏检和误报仍然很高，不能用于实际自动判定。

72 次 RAC 候选选择包含 54 次 TPE 回退、5 次全局探索、13 次代理采集；本次代理分支有运行，但没有让最终选中结果超越 TPE。SECOM 的工况只有 `overall`，不能据此评估多工况可信加权或声称自适应分支有效。

作为背景，上一轮默认策略的三方法九个选中模型均漏掉 11/11 失效件且误报 0/302。本轮单次固定参数 `time_oof` 基线仍漏掉 11/11 且误报 5/302。历史默认策略使用早停，本轮阈值策略使用三个额外折和固定树数，两轮不是同计算量的严格消融，不能将差异全部归因于阈值，更不能据此承诺未来收益。

另对本轮九个已选模型做同一模型的阈值消融：在内存中切换回模型默认阈值时，九个模型均漏掉 11/11 且误报 0/302；切回各自训练侧阈值后，检出和误报为上表所示。这个对照固定了模型与数据，但模型本身已经按同一验证集的 `time_oof` 结果选出，不能当作独立性能或不同方法在相同计算成本下的证明。逐模型对照见 `workspace/verification/industrial-optimization/campaign-623f3c44f469-paired-threshold-ablation.json`。

完整运行、每种子参数、各工况指标、阈值和模型路径见 `workspace/industrial_benchmarks/campaign-623f3c44f469/campaign.json`。分类结果提取见 `workspace/verification/industrial-optimization/campaign-623f3c44f469-secom-outcomes.json`，单次固定参数基线为 `IND-6037f530601e49f8`。每个 `IND-*` 目录包含配置、模型、来源与划分、搜索记录及日志。

## Paderborn 与多工况限制

沿用上一轮真实 Paderborn 小集：9 把物理轴承、两个预先定义的转速／载荷工况，每个验证工况仅 3 把独立轴承，每类 1 把。两个工况里外圈损伤召回均为零；整段信号切出的窗口不是独立轴承。详细分工况结果及模型见 [上一轮工业训练报告](INDUSTRIAL_TRAINING_REPORT.md)。

本轮尝试从官方来源读取额外 K004 轴承归档时请求超时，记录见 `workspace/verification/industrial-optimization/paderborn-source-probe.json`。未伪造或拼接新轴承。现有验证工况均不足最低 5 个独立组，RAC 的可信工况权重为 0；要评价多工况自适应机制，需要更多可核验且划分独立的轴承或现场设备数据。

## 可复现操作

在工程目录中运行：

```powershell
.venv\Scripts\python.exe -m rac_hpo industrial train --dataset secom --model lightgbm --decision-mode time_oof --seed 42 --estimators 120 --threads 2
.venv\Scripts\python.exe scripts\run_industrial_benchmarks.py --datasets secom --seeds 42 71 103 --trials 24 --seconds 300 --estimators 120 --threads 2 --decision-mode time_oof --skip-baselines
```

工作台入口为项目根目录的 `Run-GUI.cmd`，进入“工业训练”页选择数据集、模型、方法和“训练期时序阈值”。使用该策略必须核对误报、漏检和分组条件；如数据不符合要求，实验会失败并保存日志。不同随机种子会追加产生新的实验目录，运行时间受机器负载影响。

## 验证与后续

本轮新增的两项跨工件分组检查和单工况代理告警检查均先出现预期的失败，再实施修复。一次人工读取 CLI 输出时误按 UTF-16 解码失败，随后按实际 UTF-8 成功读取；一次查找不存在的 `optimizer.py` 命令失败，随后读取现有 `search.py`，不影响训练。默认沙箱进程初始化曾失败，后续通过已授权执行通道完成。官方 Paderborn 请求超时按前述记录保留。

完整工程回归：283 项通过，0 项失败，耗时 232.41 秒；日志和 JUnit 位于 `workspace/verification/industrial-optimization/full-suite.{log,xml}`。原两轮的 36 个模型和本轮 9 个模型共 45 个，全部通过来源／划分与模型哈希核验、模型重载，以及同配置重训的验证预测一致性检查；记录 `workspace/verification/industrial-model-replay-0b7db962ea1c.json`。重训检查不使用测试集选参或评估。

后续需要更多真实独立工件或设备、预先冻结的独立外部验证集、业务误报与漏报成本，以及有标注的现场漂移证据，才能继续评估生产可用性。尚未声称完成工业部署、CNN／LSTM、分类漂移监测或分类自主演化闭环。
