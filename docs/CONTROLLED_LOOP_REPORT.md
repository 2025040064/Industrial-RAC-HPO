# 智训引擎受控闭环交付报告

日期：2026-10-31。范围为已批准的单轮 CNC 离线软件闭环；不包含生产部署、新数据、分类模型、LLM、多轮持续优化或安装包。

## 已完成行为

- 现有五页保留，新增“自主优化”第六页与CLI loop命令组；沿用Python、LightGBM、PySide6、SQLite，未新增依赖。
- 不可变train/validation视图、源行映射、整刀回放与标签释放；独立生命周期库、授权预算、真实HPO、候选冻结、一次门禁、人工本地切换/回滚、审计与导出。
- 未授权、非法参数/工具、过期审批、重复门禁、模型损坏、取消、预算耗尽、并发执行和中断均有明确结果。
- 启动恢复死进程，将会话标为INTERRUPTED并关闭关联运行中子实验；已提交门禁恢复已有结果，不再读取数据或重训。审批与模型引用/审计在同一事务提交，注入事务失败时全部回退。

协议、接口、运行命令及数据限制见 [CONTROLLED_LOOP.md](CONTROLLED_LOOP.md)。实际文件清单、原数据库一致性和受保护源码验证保存在 `workspace/verification/controlled-loop/delivery-audit.json`。

## 真实实验

最终实测目录：`workspace/verification/controlled-loop/acceptance-1793421856206707800`。

会话：`LOOP-61baace896474f1b`；48个实际搜索trial（候选实验另含默认基线），seed=42、RAC-HPO，固定分组、目标和预算。初始及候选训练总墙钟4.9042264秒；完整回放167周期，状态COMPLETED。触发依据为tool5整刀标签释放后的ADOC_10mm误差退化，不是虚构告警或manual_demo替代。

| 门禁指标（cycles） | 初始冠军 | 候选 | 结果 |
|---|---:|---:|---|
| 总体MAE | 40.9661224403 | 33.9288729156 | 通过总体上限 |
| ADOC_5mm MAE | 54.3902848847 | 40.6060663789 | 通过工况上限 |
| ADOC_10mm MAE | 17.1542152472 | 22.0848035583 | 超过1.05倍上限，拒绝 |

门禁正确拒绝，活动槽位保持初始冠军，没有人工或自动切换。原CNC test未用于此次训练、搜索、诊断或门禁；没有调用finalize。未为得到通过结果修改阈值、划分或搜索空间。

初次验收位于 `acceptance-1793421620781393500`，补充实际源码指纹后按同一固定协议复现。两次冠军与候选模型文件SHA-256分别一致，不将第二次当作独立外部验证。最终实验、模型、策略、逐批预测、门禁、完整审计及导出位置均在实测目录的 `acceptance.json` 中。

正向模拟切换/回滚由隔离自动化测试覆盖：以相同实际模型作为非退化候选，检验审批、原子提交、恢复和预测一致性；该夹具不是HPO改善证据。负向案例包含本次真实候选工况退化及单元测试中的零误差/缺失工况保护。

## 测试与UI检查

本轮先运行失败测试，再实现或修复。完整210项检查曾通过；随后补充死进程启动恢复、已提交门禁恢复与GUI历史隔离，最终结果由下面自动汇总和JUnit记录。

```powershell
.venv\Scripts\python.exe -m pytest --basetemp workspace/verification/controlled-loop/pytest-final -o cache_dir=workspace/verification/controlled-loop/pytest-cache --junitxml=workspace/verification/controlled-loop/pytest-final.xml
.venv\Scripts\python.exe scripts/verify_controlled_loop.py --native --scale 1
.venv\Scripts\python.exe scripts/verify_controlled_loop.py --render-root workspace/verification/controlled-loop/acceptance-1793421856206707800 --native --scale 2 --sizes 720x560,1280x800
.venv\Scripts\python.exe scripts/verify_controlled_loop.py --render-root workspace/verification/controlled-loop/acceptance-1793421856206707800 --scale 2
```

Windows原生100%：720×560、1280×800、1920×1080，实际尺寸匹配，无页面横向溢出。原生200%：720×560、1280×800匹配；离屏200%：三尺寸匹配。最终目录保存8张截图和三份几何JSON，已人工查看1280×800常规及720×560双倍截图，文字/布局可读，窄窗口纵向滚动。

原生200%的1920×1080请求曾失败：Windows把逻辑窗口限制为1502×951。失败检查和实际截图保留在初次验收目录，未声称此原生尺寸通过；对应大尺寸仅有离屏验证。

完整回归覆盖旧数据、训练、四种搜索、导出、取消、原GUI、平行坐标、原子写入及Windows启动。既有finalize测试仍按原协议显式评估其隔离测试数据，不代表闭环解封CNC test。

## 失败与修复记录

| 发现 | 失败证据 | 处理 |
|---|---|---|
| 新模块/第六页尚未实现 | ModuleNotFoundError、页面数5≠6 | 按测试实现视图、服务、UI |
| 视图清单缺少源路径 | KeyError: source_path | 保存源路径并验证摘要、源与协议 |
| 并发初始化看到空版本表 | Unsupported lifecycle schema | 移除executescript隐式提交，建表/版本同事务 |
| 隔离工作区缺少实际源码指纹 | KeyError: implementation_source_sha256 | 分别记录工作区和实际实现指纹及源码快照 |
| 异常退出后仍显示训练中 | TRAINING_INITIAL ≠ INTERRUPTED | 实际退出码7子进程测试，启动恢复并终止关联实验状态 |
| 200%大窗口被桌面约束 | actual 1502×951 ≠ 1920×1080 | 区分原生可显示尺寸与离屏大尺寸，不伪报通过 |

普通沙箱进程曾无法启动（helper_unknown_error），使用获审查的执行方式完成本工程内读写与测试。最初旧pytest缓存出现访问权限警告，后续改用本轮工作区缓存，最终结果单独记录。一次文档补丁上下文不匹配，检查文件未变化后按实际文本重做。

## 兼容性、局限与恢复

旧算法、训练、评价等18个受保护文件与实施前快照一致；原实验库schema_version、experiments、trials、regime_metrics、artifacts逐项比较一致，包含30个实验、3069条trial、6138条工况记录和58个产物。旧库未迁移，旧模型/清单未覆盖。

源码和旧实验库的实施前快照位于 `workspace/verification/controlled-loop/delivery-1793420984275843400`。恢复应按变更文件清单从源码ZIP逐项恢复、新文件逐项移除；不要清空工作区、恢复覆盖原实验数据库或删除历史数据。本轮独立验收目录可单独保留或归档。交付源码快照与最终文件指纹在验证目录中保存。

这些门禁行曾被历史研究使用；验证和门禁每工况各一把刀具，q=0，无置信区间。漂移阈值和误差上限只是工程规则，不是因果、统计非退化、跨机床泛化或生产可靠性证明。App元数据仍为0.3.0，本轮为未发布增量。

下一阶段需新增独立刀具/设备数据，再研究多轮协议、公平多种子对照、可靠性分支及消融。正式赛题规则、指定平台与发布仍需独立核验，本轮未把附件建议当作官方要求。

## 最终验证汇总

最终完整 pytest：**213 passed，0失败/错误/跳过，157.972秒**。完整输出：`workspace/verification/controlled-loop/pytest-final.log`；JUnit：同目录 `pytest-final.xml`。

初始冠军实验：`EXP-735e163088204c0b`；候选实验：`EXP-8baed53dc9eb4fd7`。

冠军SHA-256：`a0180279bc265afe861b1d51c8f4eec12fb411b77edbfac622a412c38e7a65ac`。候选SHA-256：`e452bed04a16a6456d207a04f4ee678d468cc7d98bcf654d0f47fdc9822cee75`。

真实验收后仅补充启动恢复及门禁证据核对；训练与搜索实现未再改变。实测时源码快照见验收目录的implementation.zip，交付源码另保存在验证目录delivery-source.zip。
