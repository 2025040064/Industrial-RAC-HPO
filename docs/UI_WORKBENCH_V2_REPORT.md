# RAC-HPO 五页工作台 V2 交付报告

日期：2026-10-30。App 0.3.0、算法 rac-hpo-0.2.0、Schema 1 保持原值。本轮为本地UI改造，没有发布安装包。

## 实际完成

- 五页保留原生PySide6/QPainter/application与独立工作进程。顶部上下文与导航固定56逻辑像素；查看中的数据、模型、实验和后台任务分开显示。
- 单一Tooltip、250ms出现/100ms离开关闭、键盘焦点、Escape与首次点击导航；图标按实际DPR生成。全局Escape过滤仅在Tooltip显示时注册，隐藏/关闭后移除。
- 数据页紧凑导入、真实概览、划分/工况与来源Sections；训练页真实指标、始终可用的配置动作、工况与模型结果；日志页会话范围、紧凑数量与完整操作。
- 优化Trials/对比Runs独立左列；宽屏默认280/320px，可调整280–440px；窄窗口覆盖列表，最小720×560。详情在窄窗口使用完整内容区。
- 最佳objective与最佳验证MAE各自标注Trial；基线-1排除搜索统计。完整历史保持累计最优，分布/参数图/平行坐标使用统一筛选集合。
- 参数平行坐标、鼠标/键盘范围刷选、观察行双向联动、独立勾选、隐藏选择提示、2–8条显式并排、详情与绑定实验的最大化。
- 背景曲线缓存保留全部1000条测试曲线，选择只重绘高亮；统计没有采样。缓存按数据/过滤、尺寸和DPR更新。
- 跨Run仅展示已选模型的真实指标和来源；接口缺少固定划分及目标/特征版本证明，不排名、不标胜出。没有新增训练或持久化接口。

## 面板来源与缺口

A表示已核实可用，B表示需求存在但当前接口不足，C为本轮排除；分类依据为本仓库，参考截图不作数据证据。

| 内容 | 类别/实际来源 | 粒度与口径 | 本轮状态 |
|---|---|---|---|
| Runs与上下文 | A：list_experiments/get_experiment，id/config/dataset_id/status/data_sha256 | experiment为一次Run；无独立Study实体 | 上线，tags缺失不造列 |
| Trials、参数、耗时 | A：trials，复合ID与params/duration_seconds | experiment_id:number；-1为默认基线；无Trial起止时间 | 上线，缺值— |
| 最佳objective/MAE/J | A：完成Trial的objective与metrics | 所有现有算法minimize；Random/TPE目标MAE，robust/RAC目标J | 各自找最优并标Trial；不重算业务评分 |
| 历史、分布、参数散点 | A：真实完成Trial有限值 | 历史全任务；分布bin=ceil(sqrt(n))且最多12；其他图为过滤集合 | 上线，失败不填0 |
| 平行坐标与brush | A：config.optimization.search_space及Trial.params | 当前六维数值/整数/log参数；缺参断线 | 上线；筛选交集后分页 |
| 工况验证表现 | A：metrics.regimes及既有结果 | 原始目标单位；样本/独立单元证据沿用后端 | 上线；CNC缺区间不造区间 |
| 数据概览/来源/划分 | A：prepare_dataset的summary/manifest | 数据集级，不随Trial筛选重算 | 上线，明确来源与限制 |
| 超参数重要性/Correlation | B：无已保存结果 | RAC代理rank_correlation不能替代 | 单一明确空态 |
| 预测、残差 | B：未落盘sampleId、评估集/模型版本及逐样本输出 | 不能按数组位置硬配对，也不读取test补图 | 明确空态 |
| 特征重要性 | B：模型文本包含信息，但无application读取契约 | 本轮不让GUI重载模型或绕过服务 | 明确空态，后续单独接口任务 |
| 质量统计/过程趋势 | B：缺统计口径、分母、异常规则和带单位时间序列 | 校验通过不等于质量指标；时间覆盖不等于过程趋势 | 数据页一组简洁缺口说明 |
| 日志、artifacts、导出 | A：既有事件、结果和export_results | 日志页为当前会话；没有历史日志application读取方法 | 保留实际功能与原语义 |
| 设备、班次、批次、SHAP、Pareto、云协作 | C：无本轮已验证实体/结果 | 不增加业务能力、上传或依赖 | 排除 |

## 验证结果

**最终完整pytest：189 passed，0 failures、0 errors、0 skipped；控制台102.73秒。** [最终JUnit](../workspace/verification/ui-workbench-v2/delivery-1793359371819555400/pytest-delivery.xml)。全部新增与既有测试在最终版本同一次执行通过。

- 规划基线33项通过；实施相关组合回归36项通过，之后导航/工作台25项通过；追加滚动、键盘及Tooltip路径4项通过。
- GUI与验收脚本compileall通过。当前没有已配置且已安装的独立lint工具，未虚构lint结果；未升级依赖。
- Windows原生DPR=1：720×560、800×600、1280×800、1440×900、1920×1080，五页实际尺寸一致、导航/顶部56px、外层无水平溢出，38张截图。
- Windows原生DPR=2：720×560、1280×800；20张截图，另覆盖真实Runs/Trials并排、参数筛选、最大化/Escape及新任务输入保护。
- 自动化为Qt程序化真实控件与QPainter截图审阅，没有把浏览器验收套用于桌面程序；未使用Windows Narrator做完整屏幕阅读器认证，也未做多显示器或小时级耐久测试。
- 两张生成效果图未取得，像素一致性未验证。

- 原生DPR1：1000 Trial固定测试夹具，选择耗时 35.89–41.53ms，目标200ms，通过。夹具未写入数据库或导出。
- 原生DPR2：1000 Trial固定测试夹具，选择耗时 57.99–62.58ms，目标200ms，通过。夹具未写入数据库或导出。

六组实际主题组合对比度均通过：正文16.216、辅助文字5.951、主按钮6.159、上下文徽标5.503；关键控件轮廓3.645、活动导航图标3.637。仅对实际列出的组合负责，不宣称所有环境完整WCAG认证。详见contrast-checks.json。

## 隔离真实任务

使用真实UCI钢铁能耗数据、seed=42、最多30棵树、n_jobs=1、每次搜索3次/30s上限；取消任务在真实trial_completed后请求并等待后端确认。全部产物在隔离根目录，不覆盖生产历史。不调用finalize；本轮不用于算法领先、充分暖启动或可信权重收益证明。CNC使用真实历史展示，没有增加新的CNC研究训练。

| 方法 | 实验 ID | 状态 | 最佳目标 |
|---|---|---|---|
| baseline | `EXP-ee5a2483a66442eb` | completed | 20.712589 kWh |
| random | `EXP-63a9375bb020463f` | completed | 15.178431 kWh |
| tpe | `EXP-b88a5ec3d18741eb` | completed | 15.178431 kWh |
| tpe_robust | `EXP-b893d1342d624409` | completed | 0.90843262 J（无量纲） |
| rac_hpo | `EXP-1dbe852eb3554258` | completed | 0.90843262 J（无量纲） |
| tpe · cancel | `EXP-8012787477804bc1` | cancelled | — |

五次完成实验的真实JSON/CSV/Markdown/PNG/模型及复现快照导出存在；配置断言确认树数、线程数、预算请求保持一致。GUI心跳1005次，最大间隔0.438s（包含同步导出）。真实任务记录：[verification.json](../workspace/verification/ui/session-1793364135461200800/verification.json)。

## 业务保护与修改范围

应用、domain、data、training、optimization、evaluation、SQLite实现的已有源码SHA-256与实施前一致。四个GUI训练请求入口（MainWindow.start_experiment/_start_task、训练页_start、优化页_start）AST与备份一致。没有改API、Schema、参数空间、指标公式、拆分、CLI或依赖版本；没有新增W&B SDK/上传机制、密钥或.env。具体清单见本轮business-protection.json。

源码ZIP和基线manifest：[备份目录](../workspace/verification/ui-workbench-v2/delivery-1793359371819555400)。当前Git文件原本均未跟踪，因此没有以git diff冒充改动证据，也没有提交/切分支/清空工作区。

## 过程中发现的问题

- 新需求先形成6项失败测试；首轮搜索夹具关键词同时命中参数/目标，已改为精确字段搜索。旧宽度、指标列数和单击开详情测试按确认的新行为更新，排序/导出/焦点/隔离断言保留。
- 修复非有限值显示、最大化父子控件与信号闭包析构冲突、宽屏默认列表宽度、耗时标签宽度为0、曲线观察未同步列表、数据导入行数被上下文覆盖，以及关闭导航后仍注册全局事件过滤；均有先失败的对应检查。
- 初次原生DPR2选择216–226ms，未达到200ms；增加背景曲线缓存后通过。验收脚本现将性能不通过也计为非零退出码。
- 首次完整回归182通过、1失败（导入行数）；一次重复运行在相同失败后提前结束，不计为完整验收。之后185项旧集合也通过；最新完整集合189项全部通过，最终结果只取pytest-delivery.xml。
- 一次读取不存在的tests/conftest.py失败，转用现有模块级夹具；进度日志尚未产生时的读取失败不作为测试结果。
- 沙箱初始化曾失败；只读/工程内授权操作改由审批执行。一次指纹检查因自动审批服务额度未执行，后续重试成功；没有绕过审批。

## 截图与恢复

![最终原生优化工作台](../workspace/verification/ui/session-1793365114532131600/optimization-1920x1080.png)

![真实Run并排查看](../workspace/verification/ui/session-1793365318056285900/runs-comparison-1440x900.png)

改造前22张截图保存在workspace/verification/ui/session-1793359380880244600；当前规格见UI_DESIGN.md。恢复时先保留当前工作，再按修改清单从source-backup.zip恢复原有UI/测试/文档，单独处理清单内本轮新增GUI模块与测试/报告；不恢复或删除数据库、datasets和workspace/experiments，不使用reset --hard。

临时清理完成：删除本轮明确创建的17个测试/中间会话目录，无清理失败；中间会话JSON先归档，原始数据与生产实验未删除。详见[cleanup.json](../workspace/verification/ui-workbench-v2/delivery-1793359371819555400/cleanup.json)。保留最终截图、真实验收实验/导出、源码备份、指纹、JUnit及必要诊断；仅清理本轮明确创建且不需交付的中间文件。

## 实际文件清单

- 修改 `ARCHITECTURE.md`
- 修改 `CHANGELOG.md`
- 修改 `PLAN.md`
- 修改 `README.md`
- 修改 `UI_DESIGN.md`
- 修改 `docs/SIDEBAR_COLLAPSE_UI.md`
- 修改 `docs/UI_REFACTOR_REPORT.md`
- 修改 `scripts/verify_ui_workspace.py`
- 修改 `src/rac_hpo/interfaces/gui/charts.py`
- 修改 `src/rac_hpo/interfaces/gui/main_window.py`
- 修改 `src/rac_hpo/interfaces/gui/sidebar.py`
- 修改 `src/rac_hpo/interfaces/gui/theme.py`
- 修改 `src/rac_hpo/interfaces/gui/widgets.py`
- 修改 `src/rac_hpo/interfaces/gui/workspace_state.py`
- 修改 `src/rac_hpo/interfaces/gui/workspace_widgets.py`
- 修改 `src/rac_hpo/interfaces/gui/pages/compare_page.py`
- 修改 `src/rac_hpo/interfaces/gui/pages/data_page.py`
- 修改 `src/rac_hpo/interfaces/gui/pages/logs_page.py`
- 修改 `src/rac_hpo/interfaces/gui/pages/optimize_page.py`
- 修改 `src/rac_hpo/interfaces/gui/pages/train_page.py`
- 修改 `tests/integration/test_aux_workspace.py`
- 修改 `tests/integration/test_optimization_workspace.py`
- 修改 `tests/integration/test_sidebar.py`
- 修改 `tests/integration/test_workspace_widgets.py`
- 新增 `src/rac_hpo/interfaces/gui/parallel_coordinates.py`
- 新增 `src/rac_hpo/interfaces/gui/workbench_widgets.py`
- 新增 `tests/integration/test_workbench_v2.py`
- 新增 `docs/UI_WORKBENCH_V2_REPORT.md`
