# 总结与展望对齐记录（2026-11-04）

依据用户提供的《总结与展望.md》，对齐黑盒优化、工业数据审计、预测评价、资源调度和可控更新。原文中的演示提纲与性能结论不是已完成验收证明；本记录以代码和实测为准。

## 需求与实现

| 文档关注点 | 工程落点 | 实际边界 |
|---|---|---|
| 效果 | 回归总体/分工况 MAE；分类 balanced accuracy、macro F1、log loss、各类别召回、漏报/误报率 | 各类别漏报=FN/(TP+FN)，误报=FP/(FP+TN)；分母为零保存 null。故障类别以来源定义为准 |
| 稳定 | 固定鲁棒 J、真实先验工况、RAC 代理门禁 | 不自动加入扰动训练；鲁棒目标不等同于抗所有噪声；CNC 独立刀具不足，q=0 |
| 效率 | Random / Grid / TPE / 鲁棒 TPE / RAC-HPO；新增 Successive Halving / Hyperband 回归对照 | 同墙钟预算、同上限候选数均应报告；短跑不能证明效率提升 |
| 异常审计 | 独立 quality_audit.json 与数据页/工业审计入口 | 只用 train 数值特征拟合 1.5 IQR 阈值，检查 train/validation，保存源行标记；test 不参与。不删除、不裁剪、不将标记自动加入模型 |
| 可追溯 | 原实验目录、配置、模型、指标、完整 trial 和资源曲线 | 原数据库 Schema 1 保持；旧 manifest 不增加字段，避免破坏 finalize 对照 |
| 可控 | 既有 CNC 单轮离线门禁、人工模拟切换/回滚 | 只控制本地模拟槽位；代理门禁不保证优化结果比 TPE 更优 |

## 搜索接口

回归 CLI 与 GUI 增加 `grid`、`successive_halving`、`hyperband`，工业分类仍保留原三种搜索方法。六维搜索空间保持不变。

Grid 为每维低/中/高三档的粗网格；对数维中点取几何均值，整数/步长维对齐合法网格并去重。惰性笛卡尔积固定顺序遍历；默认最多 3^6=729 点，次数/时间预算可提前截断。短预算按词典序仅覆盖部分维度，不能称完整穷举。

资源对照采用 RandomSampler + Optuna SuccessiveHalvingPruner（异步实现）或 HyperbandPruner，使用固定 study_name 保持 bracket 分配可复现。资源单位为 boosting iteration，默认 min_resource=10、reduction_factor=3，上限为 model.n_estimators。每轮报告 validation MAE，跨候选淘汰；LightGBM 自身验证早停继续独立工作。资源上限轮不再剪枝。剪枝记录为 `pruned`，保存中间误差、最后迭代、原因和耗时，不参与最优模型选择，不伪造完整 MAE/J。基线 -1 仍独立计费。

`train` 增加可选 `resource_callback(step, validation_mae)`；旧调用不变。资源算法 runner 接收第三参数 report，普通算法仍用二参数 runner。最终 J 与分工况评价不变；资源对照以 MAE 选模型，不能与按 J 搜索的方法直接宣称公平领先。

## 本机运行配置

实测 macOS 26.6，Apple M5 / arm64，10 核 CPU，16 GiB 内存。默认采用 CPU、每模型 4 线程、单 trial 串行；300 棵树上限、30 轮早停。此配置为保留桌面余量的保守起点，没有通过调优证明最优。Random Forest / XGBoost / LightGBM 的工业分类默认仍为 2 线程。未配置 Metal/CUDA。

新增 `Setup.command` 和 `Run-GUI.command`。安装脚本按 uv.lock 冻结版本，Python/环境/缓存/临时目录放工程内；不隐式下载数据。Apple Silicon LightGBM 需要 Homebrew libomp。双击运行或终端 `./Run-GUI.command`；CLI 使用 `.venv/bin/python -m rac_hpo ...`。

## 验证

定向检查 46 项通过，包含真实 CNC 数据、三种新方法、源行审计与 test 访问拒绝。首次完整回归 294 通过、2 失败：旧 GUI 用例硬编码四种方法；字体用例依赖中文字体列表首项的具体字形，在 Mac 上不成立。已改为实际可用字形验证，并为 Mac 选择 Helvetica Neue / Heiti SC / Songti SC 回退，两项定向复测通过。最终完整检查见下方收尾记录。

原生 macOS 1280×800 逻辑像素（Retina DPR 2）窗口启动、数据审计和 Hyperband 历史显示通过；截图保存在 `workspace/verification/summary-alignment/mac-data.png` 与 `mac-hyperband.png`。未重新做全部尺寸与 DPI 矩阵。Python 3.11.18、LightGBM 4.6.0、Optuna 4.5.0 与锁定依赖导入通过；最初缺少 libomp 导致收集失败，安装 libomp 23.1.5 后解决。Homebrew 索引更新曾停滞，跳过自动更新后安装成功。

### M5 本机真实 CNC 运行

源文件 SHA-256 通过既有官方固定校验。固定整刀 train/validation，seed=42，每法 24 个候选、120 棵树上限、30 轮单模型早停、4 线程、串行执行、120 秒搜索上限；默认基线另计。强制拒绝 `dataset.split("test")`，未执行 finalize。实验在隔离 `workspace/verification/summary-alignment/runtime` 保存独立模型、配置、数据库、试验与日志，不改历史实验库。

| 方法 | 验证 MAE (cycles) | 固定 J | 搜索秒 | 完成/剪枝 | 实验 ID |
|---|---:|---:|---:|---|---|


| random | 25.419135 | 0.895356 | 0.468 | 24/0 | EXP-1285d68a1bb74c27 |
| grid | 30.939655 | 1.020982 | 0.485 | 24/0 | EXP-819d297abcd0411c |
| tpe | 25.510272 | 0.894110 | 0.590 | 24/0 | EXP-bf43ebff6734409d |
| tpe_robust | 27.133059 | 0.873330 | 0.844 | 24/0 | EXP-3e86efd7c159449e |
| rac_hpo | 27.133059 | 0.873330 | 0.761 | 24/0 | EXP-394799603fb04273 |
| successive_halving | 27.636992 | 0.875557 | 0.252 | 3/21 | EXP-f1cdef605aa84bd4 |
| hyperband | 27.347680 | 0.963676 | 0.418 | 9/15 | EXP-d379680d24824ff4 |

全部七次运行完成，没有失败 trial。RAC 包含 16 次历史不足回退、3 次代理质量不合格回退、2 次全局探索和3次代理排序。CNC 可信权重仍为0。质量标记不改变训练输入。

本表只是一次同候选上限、同训练资源上限的本机机制验收；实际运行远未耗尽120秒，不是等墙钟研究。MAE 与 J 两类选优目标不同，不能合并排名。Successive Halving / Hyperband 本轮实际用时更短，但 MAE 高于 Random；Grid 只访问729点中的前24点，效果更差。没有据此证明 RAC 领先或资源策略总能节约算力且保留效果。下一步应采用多种子、同目标、固定资源与外部工况进行正式比较，扰动增强与异常特征注入需单独验证。

参考：[Optuna Hyperband](https://optuna.readthedocs.io/en/v4.5.0/reference/generated/optuna.pruners.HyperbandPruner.html)、[Successive Halving](https://optuna.readthedocs.io/en/v4.5.0/reference/generated/optuna.pruners.SuccessiveHalvingPruner.html)。

### 最终收尾

- 最终完整回归：296 passed，0失败/跳过，81.29秒；证据 `workspace/verification/summary-alignment/final.xml` 与 `final.log`。命令：`QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --basetemp .cache/test-alignment-final --junitxml workspace/verification/summary-alignment/final.xml -q`，运行时 TMPDIR/MPLCONFIGDIR 均指向工程 `.cache`。
- `zsh -n Setup.command Run-GUI.command`、源码与脚本 compileall、CLI optimize 帮助、`git diff --check` 通过。锁文件未变，未迁移数据库，未发布。
- 修改范围：optimization/base + baselines、training/lightgbm_trainer、data/quality_audit、evaluation/classification、两个 application 服务、配置/CLI、数据/优化/工业页与详情/状态/字体、Mac脚本/环境验证、对应单元与真实CNC/GUI测试，以及README/ARCHITECTURE/PLAN/CHANGELOG/算法与用户说明。
- 原生 Mac UI 曾在字体改动前验收；字体改动后的字形检查与完整离屏回归通过。未进行所有尺寸原生UI复验。原始文档未改动；历史实验只追加保存。
