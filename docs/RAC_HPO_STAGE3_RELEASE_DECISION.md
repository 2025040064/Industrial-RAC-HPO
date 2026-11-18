# RAC-HPO 阶段三：发布决策与验证记录

本报告是本地公开训练/验证结果，不是官方成绩。保留原有两个 amd64 镜像及所有历史 checkpoint，不上传、不运行平台试验或正式评测。源码起点为 `e62f58e7082ede8bfc636c3361580c50dc0d44e9`；工作区开始时已有未提交变更，该 SHA 并不代表此次完整源码，具体基线 diff、实验协议和逐文件 SHA 在 `experiments/ablation/stage3-20261118-01/` 留存。

## 发布边界

| 功能 | 默认建议 | 依据与限制 |
|---|---|---|
| 同父历史、TPE、真实主指标与固定 J、B 硬门槛 | 保留 | SDK 回归及中断恢复通过；此处没有改动原有选模规则。 |
| 性能与成本前向门槛分离 | 保留，性能代理 shadow | 无成本或成本质量失败不能阻断合格性能代理；未证明性能提升。 |
| 跨父迁移 | 关闭；`gated` 安全回退 | 距离、过去记录、最少 4 条及 2 个不同父模型之外仍须过去的配对收益证据。SDK 当前不载入有效配对证据，gated 因此不会接管；`legacy` 仅显式复现实验。 |
| 工况代理 active | 暂关、观察 shadow | 要求同一父 SHA、历史中真实训练过的 shadow 提案至少 3 条，并对非平坦结果验证排序及误差；未达到时自动回退。回放中假设排名不是训练结果。 |
| B 可行性排序 | 仅 shadow | 特征包含父轴承误差和参数；样本及前向质量不足不会过滤真实训练，任何预测均不能绕过真实硬门槛。 |
| 两处成本惩罚 | 默认均关闭 | 可分离 transfer 与 acquisition，成本代理优先训练 CPU；质量不达标或 CPU 标签缺失则成本项为零。尚无单独 R5a/R5b 收益证据。 |
| 真实 PyTRiO | 保留 SDK 原有模型回执；观察 | 已完成真实本地网关一轮对照，仅支持协议与可行性结论，不支持模型普遍提高成绩。 |

当前没有证据支持完整 RAC-HPO 或迁移、代理和成本模块的算法优势。不能仅凭触发计数或一轮分数宣称收益。NASA Score 未核实，保持 `null`。

## 实现与科学边界

`stage3_controls.py` 对开关与 JSON 二选一严格校验；除已测试的旧单词回复外，无效内容保守回退。SDK 的 `rnd.finish()` 使用真实 `receipt.call_id`，没有伪造平台回执。SDK 自身在调用抛异常且没有任何模型回执时，不能构造合法的 `model_call_id`；该路径会失败而不是伪造回执，远端超时恢复仍待专门验证。

`surrogate.py` 分别记录前向性能误差、朴素基线、排序相关与成本对数误差；树分歧和残差重采样均不视作校准置信保证。`transfer_gate.py` 仅对同一数据投影、严格过去的记录计算加权对数工况距离，数据口径不兼容、参数不合法、距离过大或证据不足的记录被拒绝；无证据不会作为迁移样本。`bearing_feasibility.py` 不输出经校准的概率，不能改变硬约束。当前成本训练标签是实际 fit CPU；加载、搜索、验证、SDK、总 worker CPU 另记。冻结硬预算覆盖 worker 进程 user+system CPU，controller CPU 单独报告，不将两者混称。

## 历史核验和离线回放

独立重算阶段二 36 个最终选中 checkpoint 的公开验证指标、父 SHA，全部与保存值一致；阶段二 2314 个受保护文件的摘要均匹配。回放 `historical-replay-v2.jsonl` 共 357 条，不含本轮或未来记录；跨父筛选为记录不足 325、不同父不足 17、缺少过去配对证据 15，实际允许迁移 0。6 次 shadow 排序的性能前向检查通过，但这是历史候选上的离线重放，不是这些影子候选实际训练并获益的证据；53 个回顾性相同父候选配对同样不是在线无偏因果证据。

B 的第二阶段 124 个逐轮候选中，Bearing1_4 相对当轮父模型 RMSE 恶化 116 次；Bearing2_4 恶化 14 次；Bearing3_4 恶化 2 次。它们分别在硬门槛实际执行并拒绝时出现 116、12、0 次；部分候选因整体指标先未改善而未执行该门槛。这是已观察候选的描述性统计，不表示因果归因或外部泛化。

## 真实 PyTRiO 单轮审计

本地 Harness 宿主将合法提示传给真实 PyTRiO `Qwen/Qwen3.5-4B`；有效回执 `req_f883d8ee312e4ec6a5133599e6673164`，397 输入和 42 输出 token，费用服务未提供，记为 null。原始服务文本含 `<|im_end|>`，本地网关使用该模型 tokenizer 的 `skip_special_tokens=True` 解码，并将原文和归一化方法同时保存在 `pytrio-local-05/receipt.json`。模型返回 `conservative`、`constraint`/`risk`、`high`，选择真实影响训练参数：学习率 0.0015、1 epoch；同父固定 RAC 使用 0.003、2 epochs。两个候选本地公开验证 Macro-F1 分别为 0.7187354630 和 0.7166414061，均被现有门槛采用，差值 +0.0020940569。仅一个任务、一个种子、一轮、一个父模型，不支持模型增益结论。

此前两次实际远端回复因为结束 token 被严格解析器判无效并执行保守回退，记录保存在 `pytrio-local-03/`、`pytrio-local-04/`；停止符未被远端清除，未把这两次作为有效选择。前两次初始化失败没有成功推理，日志保留。实际服务和本地 SDK 宿主并非官方平台回执，实际费用及官方开放投影不可推断。

## 测试与复现

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv-contest/bin/python -m unittest discover -s tests/contest -v`：58 项，1 项需显式启用的预算集成测试跳过；另独立启用预算集成，7 项全通过，含真实 checkpoint 强制中断、续跑、CPU 累计和父链校验。
- `CONTEST_SDK_SOURCE="$PWD/.cache/sdk-stage3-save.wBTnNxLa" PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv-contest/bin/python -m unittest discover -s official_submission/tests -v`：19 项通过。第一次测试命令错误指向无 `template/harness.py` 的裁剪 SDK，1 项失败；使用完整原版 SDK 源目录重跑通过，两个日志均保存。
- 核心搜索 `tests/unit/test_rac_hpo.py`：20 项通过；随后 `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="src:$PWD/.venv/lib/python3.11/site-packages" .venv-contest/bin/python -m pytest tests/unit -q -p no:cacheprovider` 为 199 项全部通过，出现一次 `cache_dir` 配置警告。首次未把原环境依赖路径传给子进程时为 198 通过、1 项因子进程缺少 `lightgbm` 失败，补齐路径后重跑通过。工程级集成、GUI 等其余测试未全部重跑，不能称为全工程测试通过。
- 验证回放：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv-contest/bin/python experiments/ablation/stage3-20261118-01/replay_history_v2.py`。输出采用独占创建，已存在时应复制到新实验目录运行，不覆盖原始结果。
- 预算实验：先验证 `budget-tests.log`，再执行 `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv-contest/bin/python experiments/ablation/stage3_budget.py --campaign experiments/ablation/stage3-20261118-01/budget-comparison --smoke`，通过后去掉 `--smoke` 执行冻结的单种子对照。已有目录禁止重跑覆盖，恢复只用 `--resume` 且重新核验锁。

## 单种子硬 CPU 对照

冻结协议 SHA-256：`01b1b7d51363ae5285e79ae33996e38fd8b4ec917e45a34b6d6f51b3e9bbff61`；在实验前固定每 worker A/B/C 分别 4/9/60 CPU 秒、单线程、最多 10 轮、搜索 seed 4041，训练状态按 checkpoint 继承。四组初始 checkpoint、投影与选择门槛相同，CPU 限制由操作系统执行，不通过事后截断冒充。

R0-shadow 为旧耦合门槛的影子参照，不是旧 G1 active 的完全复现；R1 解耦门槛，R2 增加 gated 迁移，R3 请求代理 active，但缺少真实 shadow 证据时自动回退 shadow。此次四组都没有实际迁移、代理提案、影子排序或成本惩罚，不能将它们相同的结果解释为这些模块有效或无效。因未达到方案要求的触发和质量证据，没有启动三种子扩展或 R4/R5 成本收益对照。

| 任务 | 四组共同的最终公开验证指标 | R0-shadow / R1 / R2 / R3 CPU 秒 | 各组完成轮数 | 各组采纳数 |
|---|---|---|---|---|
| A | Macro-F1 0.726366；Accuracy 0.885048 | 3.014 / 3.017 / 3.025 / 3.038 | 10 / 10 / 10 / 10 | 4 / 4 / 4 / 4 |
| B | RMSE 669.136435；MAE 548.437791 | 7.248 / 6.943 / 6.843 / 6.950 | 10 / 10 / 10 / 10 | 1 / 1 / 1 / 1 |
| C | RMSE 52.189980；MAE 37.349056；NASA Score null | 52.353 / 49.908 / 49.285 / 49.940 | 10 / 10 / 10 / 10 | 1 / 1 / 1 / 1 |

上述同任务四组最终 SHA 相同；各组指标配对差值为 0，但 0 次实际机制接管使比较没有区分机制的能力，CPU 小差值也不能作为效率优势。120 轮 0 失败、0 预算超额；4 组每任务为同种子重放，不能视为四个独立种子。主对照 worker 合计 241.565 CPU 秒、最大 RSS 553,730,048 字节，controller 另 0.231 CPU 秒；事先的 12 个单轮 smoke 合计 43.178 worker CPU 秒、controller 0.157 秒。计数不包含历史重放、测试、真实模型网关或镜像构建，不能误称完整项目总 CPU 成本。

C 的 FD001/FD002/FD003/FD004 本地 RMSE 分别为 41.063948、40.297641、51.432046、64.005131，MAE 分别为 31.393962、30.780190、38.662801、44.730885。B 本次四组共计 40 个候选，Bearing1_4 恶化 36 次且 28 次在硬门槛处拒绝；四组同一搜索路径，次数不是独立样本。逐组 SHA、CPU、采纳、RSS 在 `comparison.csv`；逐轮父链、参数、J、累计 CPU 在 `trajectory.csv`；各组 `history-audit.json` 和原始 `result.json` 包含实际控制状态与回退原因。

## 镜像与保留内容

从先前源码清单逐文件校验通过的 SDK/基线构建上下文准备新上下文，源码清单 `image-context/source-files.json` SHA-256 为 `bf65e0a5ccc9fb6bba4e599647fbe6e091cd342d10f9666dd71f57eb1155162f`。新建本地 `industrial-rac-hpo:stage3-20261118-01-amd64`，镜像 ID `sha256:9e76000a815336554e394002ea46bd2aced96b3a5cfebe81ddf1c2ab803a4d54`，没有上传。原 candidate ID 仍是 `sha256:0d193d1b34831dede3bd29b8939ff6eb61ec494ab41c3185470048c2a201eced`；原 audit ID 仍是 `sha256:3bcfb7b4e94b9ce17ba7bf6edc41eacee982907406c04a6cba9c1edbc33a2687`。再次复核阶段二清单 2314 个文件，摘要全部一致。

构建命令（不覆盖原标签）：`docker buildx build --platform linux/amd64 --load --tag industrial-rac-hpo:stage3-20261118-01-amd64 experiments/ablation/stage3-20261118-01/image-context`。若标签已存在，应换新标签，不能覆盖历史镜像。镜像禁网、只读、非 root 的 5 项 SDK 回归通过，覆盖 describe/predict、A/B/C 真实权重训练、状态继承与缺失指标回退、宿主指标不匹配拒绝、B 轴承硬门槛；详情见 `image-sdk-tests.log`。
