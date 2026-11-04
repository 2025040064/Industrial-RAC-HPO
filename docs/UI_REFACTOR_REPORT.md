> 历史记录：本文描述上一版界面；当前56px固定导航及五页工作台规范见[UI_DESIGN.md](../UI_DESIGN.md)，验收见[工作台V2报告](UI_WORKBENCH_V2_REPORT.md)。

# RAC-HPO 实验工作区 UI 重构报告

日期：2026-10-30。工程内完成五页重排；保持 PySide6、QPainter、现有 application 服务和独立任务进程。

## 交付结果

- TopBar 与全局任务栏、60/200px 覆盖式侧栏、统一 WorkspaceHeader、真实指标和独立面板。
- 六项优化指标，四个真实图表，悬停提示、单位与轴名、空态及非模态放大；默认基线 -1 不进入搜索统计。
- 试验与历史记录支持搜索、筛选、数值排序、25/50/100 分页和稳定 ID 详情/导出。
- 结构化抽屉支持试验下钻、Esc、焦点恢复；更新同一实验时保留滚动、筛选与键盘操作，匹配 ID 的对比抽屉同步真实终态。
- 搜索/训练配置可折叠，动作始终可见；保留预算、种子、当前实际支持的四种搜索方法、取消、错误和导出。
- 数据页显示真实来源/许可/划分/字段单位/限制；训练页分开 MAE、J、训练流程耗时与实验总耗时；日志增量追加并支持手动滚动。
- 历史与活动任务分开，启动选择最近非 baseline 实验（含失败/取消）；查看历史不改变新任务输入。

## 测试与构建

最终全量 pytest：**175 passed，0 failures，0 errors，0 skipped**；JUnit 记录总时间 99.47s。精确控制台时间见 [完整日志](../workspace/verification/ui/pytest-full.log)，[JUnit](../workspace/verification/ui/pytest-full.xml)。

```powershell
.venv\Scripts\python.exe -m pytest --basetemp .cache\pytest-ui-delivery -o cache_dir=.cache/pytest-ui-state --junitxml=workspace/verification/ui/pytest-full.xml -q
.venv\Scripts\python.exe -m compileall -q src/rac_hpo/interfaces/gui scripts/verify_ui_workspace.py
.venv\Scripts\python.exe scripts\verify_ui_workspace.py
.venv\Scripts\python.exe scripts\verify_ui_workspace.py --exercise
.venv\Scripts\python.exe scripts\verify_ui_workspace.py --native --sizes 720x560,1280x880
```

GUI 与验收脚本编译通过。当前为 Python/Qt 工程，不生成新的安装包、不发布或升级依赖。

回归覆盖真实数据导入、基线/搜索/取消/导出、字体、五页导航、侧栏覆盖与减少动画、历史隔离、重复事件、失败经 finished 返回、进程异常、全失败、动态单位、表格 ID、抽屉与最大化、日志增量。新增展示测试中的构造记录只用于边界验证，没有接入正式页面。

曾复现并修复：历史查看更改新任务配置、排序后 ID 错配、无任务时取消按钮可用、导入失败污染上一实验、失败原因不持续显示、曲线错误色块、同一行不能重开详情、详情实时刷新重置阅读位置、对比抽屉终态不更新。调试过程中也出现过测试夹具名称/旧坐标断言错误、沙箱启动器 setup refresh 失败和旧 pytest 缓存权限警告；均已处理，最终完整测试无警告。

## 真实任务验证

独立目录：[真实验证记录](../workspace/verification/ui/session-1793346482978106000/verification.json)。使用真实 UCI 钢铁能耗数据、seed=42、最多 30 棵树、每次搜索 3 次试验；取消用独立的 1000 次上限任务，在真实试验事件后发出取消。所有运行均使用现有服务，结果和导出保存在此隔离目录，没有覆盖生产工作区的旧实验。

| 方法 | 实验 ID | 状态 | 最佳目标 |
|---|---|---|---|
| `baseline` | `EXP-09934850ac704fd2` | completed | 20.712589 kWh |
| `random` | `EXP-5eb75337c8c44f1f` | completed | 15.178431 kWh |
| `tpe` | `EXP-81ef0ab5677043d5` | completed | 15.178431 kWh |
| `tpe_robust` | `EXP-2fb890b476ba4202` | completed | 0.90843262 J（无量纲） |
| `rac_hpo` | `EXP-bf7551640d534781` | completed | 0.90843262 J（无量纲） |
| `tpe · cancel` | `EXP-3f03b553d4b747b5` | cancelled | — |

五次完成任务的 JSON/CSV/Markdown/PNG/模型与快照导出已核验；第六次取消由实际 worker 确认。短预算只验证 UI 调用、回退、存储与交互，不用于算法优劣结论，也不覆盖 RAC-HPO 的充分暖启动研究。

真实执行期间 GUI 20ms 心跳收到 994 次事件，最大间隔 0.453s（包括结束后的同步导出）。没有调用 finalize 或以测试指标选参。

## 响应式与视觉检查

- 离屏真实 Qt：800×600、1280×880、1920×1080，22 张五页、图表、记录与抽屉截图。窗口实际尺寸匹配，无主页面横向溢出；宽窗口双列、窄窗口单列，表格局部横向滚动。
- Windows 原生 Qt：720×560、1280×880 已验证，平台为 `windows`；[原生验证记录](../workspace/verification/ui/session-1793348207800105500/verification.json)。
- 已逐页检查截图与图表全貌，修正曲线填充和坐标轴/图例间距。最新截图目录：[离屏截图](../workspace/verification/ui/session-1793347950683495800)，原生截图见上述记录所在目录。

![优化工作区](../workspace/verification/ui/session-1793347950683495800/optimization-1280x880.png)

![真实四图面板](../workspace/verification/ui/session-1793347950683495800/optimization-panels-1280x880.png)

![真实训练结果](../workspace/verification/ui/session-1793347950683495800/training-1280x880.png)

验收使用程序化 Qt 操作与截图审阅；没有进行小时级持续运行或多 DPI/多显示器组合测试。

## 修改文件与边界

本次交付修改/新增 23 个文件：

- [src/rac_hpo/interfaces/gui/main_window.py](../src/rac_hpo/interfaces/gui/main_window.py)
- [src/rac_hpo/interfaces/gui/theme.py](../src/rac_hpo/interfaces/gui/theme.py)
- [src/rac_hpo/interfaces/gui/widgets.py](../src/rac_hpo/interfaces/gui/widgets.py)
- [src/rac_hpo/interfaces/gui/workspace_widgets.py](../src/rac_hpo/interfaces/gui/workspace_widgets.py)
- [src/rac_hpo/interfaces/gui/workspace_state.py](../src/rac_hpo/interfaces/gui/workspace_state.py)
- [src/rac_hpo/interfaces/gui/charts.py](../src/rac_hpo/interfaces/gui/charts.py)
- [src/rac_hpo/interfaces/gui/pages/data_page.py](../src/rac_hpo/interfaces/gui/pages/data_page.py)
- [src/rac_hpo/interfaces/gui/pages/train_page.py](../src/rac_hpo/interfaces/gui/pages/train_page.py)
- [src/rac_hpo/interfaces/gui/pages/optimize_page.py](../src/rac_hpo/interfaces/gui/pages/optimize_page.py)
- [src/rac_hpo/interfaces/gui/pages/compare_page.py](../src/rac_hpo/interfaces/gui/pages/compare_page.py)
- [src/rac_hpo/interfaces/gui/pages/logs_page.py](../src/rac_hpo/interfaces/gui/pages/logs_page.py)
- [tests/integration/test_sidebar.py](../tests/integration/test_sidebar.py)
- [tests/integration/test_workspace_lifecycle.py](../tests/integration/test_workspace_lifecycle.py)
- [tests/integration/test_workspace_widgets.py](../tests/integration/test_workspace_widgets.py)
- [tests/integration/test_aux_workspace.py](../tests/integration/test_aux_workspace.py)
- [tests/integration/test_optimization_workspace.py](../tests/integration/test_optimization_workspace.py)
- [scripts/verify_ui_workspace.py](../scripts/verify_ui_workspace.py)
- [UI_DESIGN.md](../UI_DESIGN.md)
- [PLAN.md](../PLAN.md)
- [ARCHITECTURE.md](../ARCHITECTURE.md)
- [README.md](../README.md)
- [CHANGELOG.md](../CHANGELOG.md)
- [docs/UI_REFACTOR_REPORT.md](../docs/UI_REFACTOR_REPORT.md)

当前目录不是 Git 仓库，使用实施前源文件指纹核对范围。核验所有已存在的非 GUI Python 核心文件 SHA-256 均未变化；sidebar.py、workers.py 也未修改。未改变模型、目标函数、训练/搜索逻辑、数据库结构、历史数据或依赖版本。W&B 仅用于布局参考，没有复制其资源或接入云服务。

详细组件契约、数据语义和维护边界见 [UI_DESIGN.md](../UI_DESIGN.md)。新增算法与数据继续由后端快照提供名称、单位和指标；没有真实来源的面板保留空态。

## 临时文件清理

已清理可访问的测试夹具、过期截图副本和一次性报告脚本；保留最终 JUnit、日志、源文件指纹、真实验证实验/导出和交付截图。

以下目录受沙箱账户的 Windows NTFS 权限保护，删除、读取 ACL 和针对单个临时目录的权限恢复尝试均被拒绝；普通沙箱执行器也持续报 setup refresh 错误，因此本轮未能完成这四处清理：

- `.cache/pytest-ui-lifecycle-followup-red`
- `.cache/pytest-ui-lifecycle-red`
- `.cache/pytest-ui-plan-baseline`
- `C:\Users\Legion\AppData\Local\Temp\pytest-of-Legion\pytest-31`（一次子代理测试使用了默认临时目录；之后的测试均显式指定工程内 basetemp）

它们是本轮测试临时文件，不属于原始数据或生产实验。未对其它目录调整权限；清理限制不影响 175 项通过的结果。详细操作结果见 [cleanup.json](../workspace/verification/ui/cleanup.json)。
