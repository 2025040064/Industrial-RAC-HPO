"""Render existing RAC-HPO local records without rerunning or changing experiments."""
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "workspace/contest_optimization/rac-hpo-20261117/linux-amd64"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def report():
    lines = ["# 历史 RAC-HPO 逐轮记录", "", "这些是既有 Linux amd64 本地模拟的公开验证结果，不是 SDK 平台测量或官方成绩。各候选从原始检查点续训；训练耗时与整轮耗时分别列示。工况为原本地数据中的类别、轴承或发动机，正式投影未必提供这些元数据。", ""]
    for task in "ABC":
        folder = RUN / task
        audit = load(folder / "audit.json")
        metric = "macro_f1" if task == "A" else "rmse"
        lines += [f"## {task}：{metric}", "", f"基线：{audit['baseline_metrics'][metric]:.6f}；父检查点 SHA-256：`{audit['checkpoint_sha256']}`。", "", "| 轮 | 主指标 | J | 采纳 | 训练秒 | 整轮秒 | 工况指标（样本数） |", "|---:|---:|---:|:---:|---:|---:|---|"]
        for n in range(1, 11):
            row = load(folder / f"round-{n:02}.json")
            details = row["diagnostics"]
            if task == "A":
                groups = "; ".join(f"{name}: F1={v['f1']:.4f} (n={v['samples']})" for name, v in sorted(details["classes"].items()))
            else:
                groups = "; ".join(f"{name}: MAE={v['mae']:.3f}, RMSE={v['rmse']:.3f} (n={v['samples']})" for name, v in sorted(details["groups"].items()))
            lines.append(f"| {n} | {row['metrics'][metric]:.6f} | {row['robust_objective']:.6f} | {'是' if row['accepted'] else '否'} | {row['training_seconds']:.4f} | {row['elapsed_seconds']:.4f} | {groups} |")
        lines.append("")
    lines += ["此表是对已存在记录的只读整理，并非与 Random、TPE、固定鲁棒 TPE 在相同条件下的新对照。工况计数不等于独立样本量；耗时受执行环境影响，不包含官方模型调用成本。", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    print(report(), end="")
