# 工业数据接入与分类训练报告

日期：2026-10-31。按固定数据划分完成分阶段验证；此文中的指标均来自所列正式实验，构造输入只用于自动测试。

## 数据审计与划分

- [AI4I 2020](https://archive.ics.uci.edu/dataset/601/ai4i+2020+predictive+maintenance+dataset)：UCI 明确标为**合成数据**，共 10,000 行；机器故障二分类，保留质量类型及五项传感器，排除 ID 和五项故障原因标签。按原始行顺序划分为 train/validation/test 6,000/2,000/2,000；产品质量 Type L/M/H 是工况，不存在已验证的物理设备分组。不能把结果描述为真实工厂性能。
- [SECOM](https://archive.ics.uci.edu/dataset/179/secom)：真实半导体工艺数据，1,567 个生产实体、590 项匿名传感器，104 fail、1,463 pass。按真实测量时间稳定排序，train/validation/test 为 940/313/314。缺失值处理只在训练集拟合；工况仅标记 overall，因为没有足以支持独立工况划分的元数据。
- [Paderborn](https://mb.uni-paderborn.de/en/kat/research/bearing-datacenter)：真实实验台信号，许可 CC BY-NC 4.0。小规模子集取 9 把轴承的两个已知转速/负载工况，各一条记录；每条分 8 个不重叠窗口，共 144 个窗口。每折 3 把物理轴承、48 窗口，分别覆盖健康、外圈和内圈三类；所有窗口和工况按轴承整体分组。每个验证工况只有 3 把独立轴承，不能把窗口当独立样本或得出可靠性证明。
- XJTU-SY 支持已核验完整寿命运行的本地导入和 RUL 回归审计，未纳入此次分类训练；联想需授权，本轮未取得授权；Pneumatic 的规范化本地契约保留动作分类语义，尚未核验其原始文件格式。详细来源、许可、下载失败与本地格式见 [来源审计](../datasets/INDUSTRIAL_SOURCES.md)。

数据加载和审计会校验源文件及预先划分；模型训练、早停、HPO 和汇总只使用 train/validation，未对 test 做最终评估。数据来源不混合标签。各次实验目录保留源文件哈希、划分、版本、配置、模型、日志和指标。

## 分类训练与比较协议

三种模型为 Random Forest、XGBoost 和 LightGBM，评价使用 balanced accuracy、macro F1、log loss 与各工况分类指标；它们不会与旧回归任务的 MAE 混排。默认参数基线与搜索分别保存，基线不计入搜索 trial。

三种搜索方法使用相同 LightGBM 搜索空间、固定划分、分类目标和线程数：Random Search、Optuna TPE、RAC-HPO。正式比较使用种子 42、71、103，每次最多 24 trial、300 秒、120 棵树上限、2 线程；每个算法各自的默认基线另计。相同种子下工况基线和权重固定，以验证集 `1 - balanced accuracy` 计算归一化目标 J：`0.7 × 加权平均工况误差比 + 0.3 × 最差工况误差比`，越小越好。每种方法按同一 J 选择，不用测试集选参。只有所有种子和试验完成且控制条件相符时，汇总才标记公平可比。

## AI4I 实测结果：合成基准

固定参数基线的验证 balanced accuracy：Random Forest 0.7654、XGBoost 0.7545、LightGBM 0.7434；各为 seed 42 的单次结果。

| 方法 | 验证 balanced accuracy，3 种子均值 ± 标准差 | J，3 种子均值 ± 标准差 | 平均实验耗时 / 秒 |
| --- | ---: | ---: | ---: |
| Random | 0.7399 ± 0.0167 | 1.0193 ± 0.0666 | 3.97 |
| TPE | 0.7474 ± 0.0069 | 0.9912 ± 0.0152 | 3.84 |
| RAC-HPO | 0.7476 ± 0.0067 | 0.9908 ± 0.0148 | 4.00 |

分工况 balanced accuracy 均值：

| 验证工况 | 样本数 / 故障样本数 | Random | TPE | RAC-HPO |
| --- | ---: | ---: | ---: | ---: |
| H | 181 / 2 | 0.4972 | 0.4972 | 0.4972 |
| L | 1,208 / 33 | 0.7621 | 0.7671 | 0.7673 |
| M | 611 / 10 | 0.7158 | 0.7328 | 0.7331 |

此次三个 RAC 搜索共记录 16 次代理采集、5 次全局探索、51 次 TPE 回退；包含暖启动。RAC 与 TPE 的结果非常接近，本次小预算、单数据划分和三种子不足以证明普遍领先。AI4I H 工况最弱，验证故障样本仅 2 个，三个方法的故障召回率均为 0；其分工况结果只能作描述性观察。

正式实验及可比性证据：`workspace/industrial_benchmarks/campaign-51a07f897106/campaign.json`。最终代码对 36 个正式模型（含 12 个 AI4I 模型）的哈希、重载及固定配置重训预测一致性检查全部通过，证据 `workspace/verification/industrial-model-replay-7548a10db693.json`。

## SECOM 实测结果：真实半导体数据

固定参数基线的验证 balanced accuracy：Random Forest 0.4967、XGBoost 0.5000、LightGBM 0.5000；各为 seed 42 单次结果。

| 方法 | 验证 balanced accuracy，3 种子均值 ± 标准差 | Macro F1 均值 | J 均值 | 平均实验耗时 / 秒 |
| --- | ---: | ---: | ---: | ---: |
| Random | 0.5000 ± 0.0000 | 0.4911 | 1.0000 | 10.65 |
| TPE | 0.5000 ± 0.0000 | 0.4911 | 1.0000 | 10.09 |
| RAC-HPO | 0.5000 ± 0.0000 | 0.4911 | 1.0000 | 10.60 |

三个方法在各个种子的选中模型都把验证集 11 个 fail 样本判为 pass，fail 召回率为 0；302 个 pass 全部识别。该结果显示模型在当前固定验证划分上没有识别出失效件，不能用于生产判定。SECOM 缺少可靠工况元数据，只报告 overall；不能将时间段伪造为不同工况。RAC 的 72 次选择中 67 次使用 TPE 回退、5 次全局探索，代理没有产生采集选择，本次不能证明自适应收益。

## Paderborn 实测结果：真实轴承实验台

固定参数基线的验证 balanced accuracy：Random Forest 0.1458、XGBoost 0.0000、LightGBM 0.0625；各为 seed 42 单次结果。它们表明在所选的整轴承划分上，默认模型不能可靠泛化。

| 方法 | 验证 balanced accuracy，3 种子均值 ± 标准差 | Macro F1 均值 | J，3 种子均值 ± 标准差 | 平均实验耗时 / 秒 |
| --- | ---: | ---: | ---: | ---: |
| Random | 0.3681 ± 0.0318 | 0.2396 | 0.6792 ± 0.0350 | 3.18 |
| TPE | 0.3542 ± 0.0361 | 0.2045 | 0.6930 ± 0.0402 | 3.14 |
| RAC-HPO | 0.3542 ± 0.0361 | 0.2045 | 0.6930 ± 0.0402 | 3.30 |

分工况 balanced accuracy 均值：

| 验证工况 | 每类窗口数 / 独立轴承总数 | Random | TPE | RAC-HPO |
| --- | ---: | ---: | ---: | ---: |
| N09_M07_F10：900 rpm，0.7 Nm，1,000 N | 8 / 3 | 0.3889 | 0.3611 | 0.3611 |
| N15_M07_F10：1,500 rpm，0.7 Nm，1,000 N | 8 / 3 | 0.3472 | 0.3472 | 0.3472 |

两工况中 N15 的平均结果较弱或持平；三个方法、三个种子的选中模型在两个工况上的外圈损伤召回率均为 0。每工况每类仅 1 把验证轴承，窗口高度相关，该差异只是小样本描述。RAC 共 7 次代理采集、5 次全局探索、60 次 TPE 回退；验证工况仅 3 把轴承，低于 5 把的独立证据门槛，可信关注权重 q=0。此次 Random 的平均 J 低于 RAC，但不足以推断总体算法排序。

三数据源各方法完整的每种子 ID、参数、指标、各类别召回和工况记录见 `workspace/industrial_benchmarks/campaign-51a07f897106/campaign.json` 与 `workspace/industrial_benchmarks/campaign-73ab094af4b8/campaign.json`；便于阅读的逐项汇总见 `workspace/verification/industrial-results-summary.log`。两个真实数据源的正式搜索共 18 次，全部各完成 24 trial；公平汇总未发现缺失种子或不匹配条件。SECOM 与 Paderborn 共 24 个正式模型也包含在最终 36 模型重载与重训检查中。

## 检查与失败记录

完整工程回归：271 项通过，0 失败；JUnit 为 `workspace/verification/industrial-full2.xml`。随后补充 RAR4 本地归档、重复导入、工程内缓存、篡改和链接拒绝等检查，数据/服务/公平汇总 42 项通过（`workspace/verification/industrial-archive-final.xml`），界面/分类 20 项通过（`workspace/verification/industrial-interface-final.xml`）。另将未修改的真实 Paderborn MAT 包装进本地构造的 RAR4，导入后哈希一致且信号结构解析通过，证据为 `workspace/verification/industrial-rar-local.json`；这个本地构造的归档不能称为原始官方 RAR。工业 GUI 另完成真实 AI4I 小预算训练、搜索和取消，保留截图、模型与日志，目录为 `workspace/verification/industrial-gui/session-1793425866151102200`。原有六页功能及受控闭环回归包含在完整测试中。

已发生并保留的异常包括：初次 PyPI 官方源下载超时，随后使用公开镜像安装相同锁定版本；UCI 实际字段名及 SECOM 日期格式与预期不同，均先增加失败测试再修复；Paderborn HTTPS 证书链校验失败后使用官方同域公开 HTTP 范围请求，未关闭证书校验。HTTP 获取的 SHA-256 用于后续完整性与复现，不能视为与官方独立公布的校验值匹配。额外重取一条官方归档压缩条目时发生 HTTPS 跳转及 TLS 握手超时，记录见 `workspace/verification/industrial-rar-real.json`；前述本地构造归档验证未冒称复核了官方压缩条目。SECOM 单工况 RAC 代理训练出现 scikit-learn 单列目标数组警告，搜索完成且该日志未被隐藏；其代理最终未产生采集选择。一次收集测试列表时管道提前关闭导致输出错误，未影响完整测试。全量测试首轮日志输出缓冲曾被误判为停滞，实际 266 项通过；新增检查后的第二轮 271 项通过。

当前 `uv.lock` 中包下载地址使用清华公开镜像，原有依赖版本未升级；`uv lock --check --offline` 已通过。新增 2 个归档缓存缺陷均先用失败测试复现，再修复并完成上述专项回归。本轮 44 项临时测试目录及临时脚本已清理，0 项清理失败；实验、数据、模型、JUnit 和运行日志保留。

## 本轮文件

- 数据：`src/rac_hpo/data/industrial/` 下的 `uci.py`、`bearings.py`、`local.py`、`common.py`、`archives.py` 与分派入口；`datasets/INDUSTRIAL_SOURCES.md`。
- 模型与服务：`training/classification.py`、`evaluation/classification.py`、`optimization/classification.py`、`application/industrial_service.py`；`pyproject.toml`、`uv.lock`。
- 入口：`interfaces/cli.py`、`interfaces/gui/pages/industrial_page.py`、`interfaces/gui/main_window.py`、`interfaces/gui/workers.py`、`interfaces/gui/sidebar.py`。
- 验证：`scripts/run_industrial_benchmarks.py`、`scripts/verify_industrial_models.py`；`tests/unit/test_industrial_data.py`、`test_industrial_benchmark.py`、`test_classification.py`；`tests/integration/test_industrial_service.py`、`test_industrial_gui.py`、`test_gui.py`。
- 文档：`README.md`、`ARCHITECTURE.md`、`PLAN.md`、`CHANGELOG.md`、`UI_DESIGN.md`、`docs/INDUSTRIAL_TRAINING_PLAN.md` 和本报告。

当前 Git 状态下工程文件均为未跟踪文件，不能用 `git diff` 单独生成本轮变更清单；本轮未创建提交。实验目录、原始数据及本地环境按既有忽略规则保留在工程中。

## 后续边界

1D-CNN、LSTM、其他时序网络，以及新分类数据上的漂移监测和持续自主演化尚未实施。原 CNC 受控单轮离线闭环仍有其独立协议，不能把其结果直接外推到新增分类数据。后续需要更多独立轴承及真实现场工况、更多种子和外部验证，再评估代理和可信工况关注的作用；不得以小样本试跑宣称算法性能已被全面证明。
