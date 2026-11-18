#!/usr/bin/env python3
"""Render a descriptive, non-significance-claiming report from stage-two statistics."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[2]


def fmt(v, digits=6):
    return '—' if v is None else f'{v:.{digits}f}'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('campaign', type=Path)
    p.add_argument('statistics', type=Path)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    campaign, stats = args.campaign.resolve(), args.statistics.resolve()
    data = json.loads((stats / 'analysis.json').read_text())
    protocol = json.loads((campaign / 'protocol.json').read_text())
    engine = json.loads((campaign / 'engine-lock.json').read_text())
    runs, groups, seeds = data['runs'], ('G0','G1','G2','G3'), protocol['search_seeds']
    lines = ['# RAC-HPO 阶段二：硬 CPU 预算消融报告', '',
             '本报告是本地公开验证结果，不是官方平台成绩。每项仅三个配对搜索种子；不作统计显著性声明。', '',
             '## 冻结协议和预算', '',
             '- 分别采用 A 4 秒、B 9 秒、C 60 秒的 worker 进程 user+system CPU 硬上限，单线程，最多 10 轮。预算根据阶段一全进程 CPU 最大值预先确定，运行期间未调节。',
             '- `RLIMIT_CPU` 在硬限额前 1 秒设置软终止点；worker 到软限额通常提前停止，硬限额为内核后备。未使用的安全余量如实保留，CPU 阶段与未完成轮均计入总量；结果不使用事后截取。controller 解压、调度和报告 CPU 独立统计，不计入 worker 限额。',
             '- G0 固定参数；G1 关闭迁移和成本排序；G2 启用迁移但关闭成本排序；G3 加入跨父 TPE 和 RAC acquisition 的成本项。三组共享成本代理前向质量门槛，因此 G1/G2 不等于完全不使用成本信息。G2/G3 两处成本项共同变化，不能分别归因。',
             '- 训练随机状态继承原始 checkpoint，101/202/303 仅是搜索随机种子；每任务和种子按轮换顺序运行四组。使用同一 SDK 选择与严格指标对账、同一数据/元数据投影及父链。',
             '- C 官方 NASA Score 公式和平台口径未核实，全部记为 `null`。', '',
             f"协议 SHA-256：`{sha(campaign/'protocol.json')}`；驱动 SHA-256：`{engine['source_sha256']['experiments/ablation/hard_budget.py']}`；统计 SHA-256：`{sha(ROOT/'experiments/ablation/stage2_stats.py')}`；报告生成器 SHA-256：`{sha(Path(__file__))}`。完整源码及数据摘要见 protocol、engine 和 analysis lock。", '',
             '## 三种子逐组结果', '',
             '所有指标为实际预算停止时最后一个已完成且通过选择门槛的模型；表中 `标准差` 为样本标准差。', '',
             '| 任务 | 组 | 指标 | 101 | 202 | 303 | 均值 | 标准差 | 中位数 | 范围 |',
             '| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |']
    for task in 'ABC':
        metrics = ('macro_f1','accuracy') if task == 'A' else ('rmse','mae')
        for group in groups:
            for metric in metrics:
                values = [next(r[metric] for r in runs if (r['task'],r['group'],r['seed'])==(task,group,seed)) for seed in seeds]
                s = next(x for x in data['aggregate'] if (x['task'],x['group'],x['metric'])==(task,group,metric))
                lines.append(f"| {task} | {group} | {metric} | {' | '.join(fmt(x) for x in values)} | {fmt(s['mean'])} | {fmt(s['sample_std'])} | {fmt(s['median'])} | {fmt(s['min'])}–{fmt(s['max'])} |")
    lines += ['', '## 逐种子配对差值', '', '差值为左组减右组；A 指标越大越好，B/C 误差越小越好。每行 n=3，不能把正负号当作显著性证明。', '',
              '| 任务 | 对照 | 指标 | 101 | 202 | 303 | 均值 | 标准差 | 中位数 | 范围 |',
              '| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |']
    for task in 'ABC':
        metrics = ('macro_f1','accuracy') if task == 'A' else ('rmse','mae')
        for comp in ('G1-G0','G2-G1','G3-G2'):
            for metric in metrics:
                vals = [next(r['difference'] for r in data['paired'] if (r['task'],r['comparison'],r['metric'],r['seed'])==(task,comp,metric,seed)) for seed in seeds]
                s = next(x for x in data['paired_statistics'] if (x['task'],x['comparison'],x['metric'])==(task,comp,metric))
                lines.append(f"| {task} | {comp} | {metric} | {' | '.join(fmt(x) for x in vals)} | {fmt(s['mean'])} | {fmt(s['sample_std'])} | {fmt(s['median'])} | {fmt(s['min'])}–{fmt(s['max'])} |")
    lines += ['', '## CPU、完成轮次、采纳与模块触发', '',
              'CPU 为 worker 总 user+system 秒，包含全部已启动和未完成轮；轮次只统计已原子提交结果。`效率` 定义为相对初始模型的主指标正向改善量除以 worker CPU 秒。成本排名逆转为各轮成对逆转次数之和，同一对可在多轮重复计数。', '',
              '| 任务 | 组 | 完成轮数 101/202/303 | CPU 秒 101/202/303 | 采纳 101/202/303 | 失败轮合计 | 代理排序合计 | 迁移轮合计 | 排名逆转合计 | 效率均值 |',
              '| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |']
    for task in 'ABC':
        for group in groups:
            rows=[next(r for r in runs if (r['task'],r['group'],r['seed'])==(task,group,seed)) for seed in seeds]
            eff=statistics.mean(r['improvement_per_cpu_second'] for r in rows)
            lines.append(f"| {task} | {group} | {' / '.join(str(r['rounds_completed']) for r in rows)} | {' / '.join(fmt(r['cpu_seconds'],3) for r in rows)} | {' / '.join(str(r['accepted']) for r in rows)} | {sum(r['failed_rounds'] for r in rows)} | {sum(r['surrogate_used'] for r in rows)} | {sum(r['transfer_tpe_rounds'] for r in rows)} | {sum(r['cost_ranking_inversions'] for r in rows)} | {fmt(eff)} |")
    lines += ['', '预载、搜索、训练、验证、SDK 宿主和其他 CPU 的每组逐种子数值，及其采纳率、失败率、峰值内存、最终 checkpoint 路径与 SHA 均在 `runs.csv`；每轮推荐/实际参数、门槛、历史、累计 CPU、内存与指标在 `trajectory.csv`。所有均值、标准差、中位数、范围以及各指标的逐种子差值在对应 CSV。', '',
              '## B 逐轴承门槛', '', '| 组 | 因逐轴承门槛拒绝次数（101 / 202 / 303） | 已完成轮数（101 / 202 / 303） |', '| --- | --- | --- |']
    for group in groups:
        rows=[next(r for r in runs if (r['task'],r['group'],r['seed'])==('B',group,seed)) for seed in seeds]
        lines.append(f"| {group} | {' / '.join(str(r['bearing_guard_rejects']) for r in rows)} | {' / '.join(str(r['rounds_completed']) for r in rows)} |")
    lines += ['', '## C 各公开子数据集', '', '按真实 source_subset 聚合逐单元误差，三种子均值与样本标准差；完整逐种子及配对结果见 `subsets.csv`、`subset-statistics.csv`、`subset-paired-statistics.csv`。', '', '| 子集 | 组 | MAE 均值 ± 标准差 | RMSE 均值 ± 标准差 |', '| --- | --- | ---: | ---: |']
    for subset in sorted(set(r['subset'] for r in data['subsets'])):
        for group in groups:
            a=next(r for r in data['subset_statistics'] if (r['subset'],r['group'],r['metric'])==(subset,group,'mae'))
            b=next(r for r in data['subset_statistics'] if (r['subset'],r['group'],r['metric'])==(subset,group,'rmse'))
            lines.append(f"| {subset} | {group} | {fmt(a['mean'])} ± {fmt(a['sample_std'])} | {fmt(b['mean'])} ± {fmt(b['sample_std'])} |")
    incomplete=sum(r['partial_rounds'] for r in runs)
    failures=sum(r['failed_rounds'] for r in runs)
    limit=sum(r['status']=='budget_exhausted' for r in runs)
    lines += ['', '## 资源与异常', '',
              f"正式对照共 {len(runs)} 个任务组、{sum(r['rounds_completed'] for r in runs)} 个已完成轮；{limit} 个任务组因 CPU 限额停止，{incomplete} 个未完成轮，{failures} 个训练/回调失败轮。全部 worker 进程 CPU 共 {sum(r['cpu_seconds'] for r in runs):.3f} 秒，最大进程峰值内存 {max(r['peak_rss_bytes'] for r in runs)/1048576:.1f} MiB；controller CPU {data['controller_cpu_seconds']:.3f} 秒另计。预算停止、部分轮资源及任何异常的完整清单见 `anomalies.json`。", '',
              '日志里的资源与峰值属于本地机器。内核 CPU 会计与软信号的实际粒度可能有细小误差；实际用量和硬预算超量字段逐项保存，发现超量时不纳入有效对照。', '',
              '## 解释与发布边界', '',
              'G1/G0、G2/G1、G3/G2 的逐种子方向和变化幅度应结合上表、成本与完成轮数阅读；三种子只能描述本次样本。未确认的赛事投影、父链回执与 NASA Score 仍限制对正式成绩的推断。具体建议及未触发模块见本报告末尾的实验审计结论。', '']
    with args.output.open('x', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(args.output)


if __name__ == '__main__':
    main()
