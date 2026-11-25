"""Train a PyTRIO LoRA policy on contest RAC/conservative decisions.

The offline prompts are built by the same `selection_messages` helper the
submitted runtime uses, so training and inference share one payload contract.
"""
import argparse
import json
import math
from pathlib import Path

from rac_hpo.contest.packages import write_json
from rac_hpo.contest.sampler import (
    BASE_MODEL, decision_messages, parse_action, parse_selection_reply, selection_messages)

BATCH_SIZE = 2
DEFAULT_EPOCHS = 3
DEFAULT_LEARNING_RATE = 2e-4


def selection_label(round_result):
    """Derive a contract-conformant label from a historical round.

    Accepted rounds used the RAC proposal and passed all gates; rejected rounds
    fell back to the conservative branch. reason_codes records that the label is
    derived from public validation history; risk separates the two outcomes.
    """
    accepted = bool(round_result["accepted"])
    return {"selected_option": "RAC" if accepted else "conservative",
            "reason_codes": ["history"],
            "risk": "low" if accepted else "medium"}


def decision_context(round_result, previous_selected_metric, history):
    """Rebuild the runtime decision context for one offline round."""
    proposal = dict(round_result["proposal"])
    alternative = {**proposal, "learning_rate": max(1e-5, proposal["learning_rate"] / 2),
                   "sampling_level": 1, "epochs": 1}
    return {"task": round_result["task"], "round": round_result["round"],
            "history": history, "selected_metric": previous_selected_metric,
            "rac": proposal, "conservative": alternative}


def examples(root, task, legacy=False):
    folder = root / task
    audit = json.loads((folder / "audit.json").read_text())
    recent = []
    rows = []
    for path in sorted(folder.glob("round-??.json")):
        round_result = json.loads(path.read_text())
        if round_result["task"] != task:
            raise ValueError(f"Invalid task in {path}")
        if legacy:
            # Historical parameter-proposal contract. Explicit opt-in only.
            completion = json.dumps(round_result["proposal"], ensure_ascii=False, allow_nan=False)
            parse_action(completion, task)
            if round_result["accepted"]:
                prompt = decision_messages({
                    "task": task, "round": round_result["round"],
                    "baseline_metrics": audit["baseline_metrics"],
                    "selected_metric": round_result["previous_selected_metric"], "history": recent,
                })
                rows.append({"task": task, "prompt": prompt, "completion": completion})
        else:
            completion = json.dumps(selection_label(round_result), ensure_ascii=False, allow_nan=False)
            parse_selection_reply(completion)
            context = decision_context(round_result, round_result["previous_selected_metric"], list(recent))
            rows.append({"task": task, "context": context, "completion": completion})
        recent.append(round_result)
    return rows


def split_examples(history, supplement=None, legacy=False):
    training = []
    sources = {}
    for task in ("A", "B"):
        source = history
        rows = examples(source, task, legacy=legacy)
        if not rows and supplement is not None:
            source = supplement
            rows = examples(source, task, legacy=legacy)
        if not rows:
            raise ValueError(f"No accepted decisions for {task}")
        if legacy:
            training.extend(rows)
        else:
            # Round-1 rows carry no history and only teach a task prior, which is
            # what collapsed the previous Sampler. Keep evidence-bearing rounds and
            # add their flipped-history partners.
            rows = [row for row in rows if row["context"]["history"]]
            if not rows:
                raise ValueError(f"No evidence-bearing decisions for {task}")
            training.extend(rows + counterfactuals(rows))
        sources[task] = source
    heldout = examples(history, "C", legacy=legacy)
    if not heldout:
        raise ValueError("No accepted decisions for held-out task C")
    return training, heldout, {**sources, "C": history}


def balance(rows):
    """Interleave the two classes so no batch is dominated by one outcome.

    The raw history is 7 RAC versus 13 conservative across A/B, which made the
    Sampler collapse to the majority class at temperature 0.
    """
    groups = {"RAC": [], "conservative": []}
    for row in rows:
        groups[json.loads(row["completion"])["selected_option"]].append(row)
    target = max(len(groups["RAC"]), len(groups["conservative"]))
    if not target:
        raise ValueError("No training labels")
    ordered = []
    for index in range(target):
        for label in ("RAC", "conservative"):
            group = groups[label]
            if group:
                ordered.append(group[index % len(group)])
    return ordered, {label: len(group) for label, group in groups.items()}


def encode_prompt(tokenizer, messages):
    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True,
                                           enable_thinking=False)
    return tokenizer.encode(prompt, add_special_tokens=False)


def prompt_for(row):
    if "messages" in row:
        return row["messages"]
    if "prompt" in row:
        return row["prompt"]
    return selection_messages(row["context"])


def sample_action(sampler, tokenizer, messages, trio):
    import numpy as np
    result = sampler.sample(prompt=trio.ModelInput.from_ints(encode_prompt(tokenizer, messages)),
                            sampling_params=trio.SamplingParams(
                                max_tokens=384, temperature=0, seed=42, stop=["<|im_end|>"]),
                            num_samples=1).result()
    try:
        option = parse_selection_reply(result.sequences[0].text)["selected_option"]
    except (IndexError, ValueError):
        return "invalid"
    return "RAC" if option == "rac" else "conservative"


def mutate_history(context, accepted):
    """Flip the accepted flag and the observed trajectory of the recent rounds."""
    metric = "macro_f1" if context["task"] == "A" else "rmse"
    base = context.get("selected_metric")
    if isinstance(base, dict):
        base = base.get(metric)
    rows = []
    last = base
    for index, row in enumerate(context["history"]):
        copy = json.loads(json.dumps(row))
        copy["accepted"] = accepted
        metrics = copy.get("metrics") if isinstance(copy.get("metrics"), dict) else {}
        if isinstance(base, (int, float)) and base:
            last = base + (index + 1) * 0.02 * base if accepted else base - (index + 1) * 0.02 * base
            metrics[metric] = last
        copy["metrics"] = metrics
        copy["previous_selected_metric"] = last
        rows.append(copy)
    probe = dict(context)
    probe["history"] = rows
    probe["selected_metric"] = last
    return probe


def counterfactuals(rows):
    """Teach the decision rule, not the task prior.

    Each round contributes a pair that differs only in whether the recent
    history was accepted; the label must flip with it. Without this pairing a
    tiny LoRA learns "B is usually rejected, so answer conservative".
    """
    out = []
    for row in rows:
        context = row.get("context")
        if not context or not context.get("history"):
            continue
        label = json.loads(row["completion"])["selected_option"]
        flipped = label == "conservative"
        probe = mutate_history(context, flipped)
        completion = json.dumps({"selected_option": "RAC" if flipped else "conservative",
                                 "reason_codes": ["history"],
                                 "risk": "low" if flipped else "medium"},
                                ensure_ascii=False, allow_nan=False)
        out.append({"task": row["task"], "context": probe, "completion": completion})
    return out


def probes(heldout):
    out = []
    for row in heldout:
        if "context" not in row or not row["context"]["history"]:
            continue
        for label, accepted in (("improving", True), ("stalling", False)):
            probe = mutate_history(row["context"], accepted)
            probe["round"] = int(row["context"]["round"]) + 1
            out.append((label, probe))
        if len(out) >= 8:
            break
    return out


def guard(service, tokenizer, saved_path, heldout, probe_rows):
    """Reject a Sampler that cannot produce both branches."""
    import pytrio as trio
    sampler = service.create_sampling_client(base_model=BASE_MODEL, model_path=saved_path)
    report = {"heldout": {"RAC": 0, "conservative": 0, "invalid": 0},
              "improving": {"RAC": 0, "conservative": 0, "invalid": 0},
              "stalling": {"RAC": 0, "conservative": 0, "invalid": 0}}
    for row in heldout:
        report["heldout"][sample_action(sampler, tokenizer, prompt_for(row), trio)] += 1
    for label, context in probe_rows:
        report[label][sample_action(sampler, tokenizer, selection_messages(context), trio)] += 1
    total = {"RAC": 0, "conservative": 0, "invalid": 0}
    for block in report.values():
        for key in total:
            total[key] += block[key]
    both = total["RAC"] > 0 and total["conservative"] > 0
    improving = report["improving"]
    monotone = improving["RAC"] >= report["stalling"]["RAC"]
    return {"distribution": report, "totals": total,
            "both_branches_reachable": both,
            "improving_prefers_rac": monotone,
            "passed": bool(both and monotone)}


def train(args, training, heldout):
    import numpy as np
    import pytrio as trio
    import swanlab

    if args.legacy_params:
        balanced, raw_counts = list(training), {}
    else:
        balanced, raw_counts = balance(training)
    dataset_rows = balanced * max(1, args.epochs)
    steps = math.ceil(len(dataset_rows) / BATCH_SIZE)
    run = swanlab.init(project=args.project, name=args.name, public=False,
                       mode="online", on_online_error="raise",
                       log_dir=str(args.output.parent / "swanlog"),
                       config={"base_model": BASE_MODEL, "rank": 8, "epochs": args.epochs,
                               "batch_size": BATCH_SIZE, "learning_rate": args.learning_rate,
                               "raw_labels": raw_counts, "balanced_examples": len(balanced),
                               "training_steps": steps,
                               "train_a_examples": sum(row["task"] == "A" for row in training),
                               "train_b_examples": sum(row["task"] == "B" for row in training),
                               "heldout_c_examples": len(heldout)})
    url = getattr(run, "url", None)
    if url is None:
        url = run.public.cloud.experiment_url
    if not url or not url.startswith("https://"):
        raise RuntimeError("SwanLab cloud experiment URL is unavailable")
    print(f"TRAINING_RECORD_URL={url}", flush=True)
    service = trio.ServiceClient()
    client = service.create_lora_training_client(base_model=BASE_MODEL, rank=8, seed=42)
    tokenizer = client.get_tokenizer()
    dataset = []
    for row in dataset_rows:
        prefix = encode_prompt(tokenizer, prompt_for(row))
        target = tokenizer.encode(row["completion"], add_special_tokens=False)
        if tokenizer.eos_token_id is not None:
            target.append(tokenizer.eos_token_id)
        tokens = prefix + target
        weights = [0] * len(prefix) + [1] * len(target)
        dataset.append(trio.Datum(model_input=trio.ModelInput.from_ints(tokens[:-1]),
                                  loss_fn_inputs={
                                      "target_tokens": np.asarray(tokens[1:], dtype=np.int32),
                                      "weights": np.asarray(weights[1:], dtype=np.float32)}))

    for index in range(0, len(dataset), BATCH_SIZE):
        batch = dataset[index:index + BATCH_SIZE]
        result = client.forward_backward(batch, loss_fn="cross_entropy").result()
        logprobs = np.concatenate([output["logprobs"].tolist() for output in result.loss_fn_outputs])
        weights = np.concatenate([item.loss_fn_inputs["weights"].tolist() for item in batch])
        loss = float(-np.dot(logprobs[weights > 0], weights[weights > 0]) / weights.sum())
        if not math.isfinite(loss):
            raise RuntimeError("Non-finite training loss")
        client.optim_step(trio.AdamParams(learning_rate=args.learning_rate)).result()
        run.log({"train/loss": loss, "train/supervised_tokens": int(weights.sum())},
                step=index // BATCH_SIZE + 1)

    saved = client.save_weights_for_sampler(name=args.name).result()
    if not saved.path.startswith("trio://"):
        raise RuntimeError("Unexpected sampler path")
    print(f"SAMPLER_PATH={saved.path}", flush=True)
    if args.legacy_params:
        check = {"passed": True, "skipped": "legacy parameter-proposal contract"}
    else:
        check = guard(service, tokenizer, saved.path, heldout, probes(heldout))
    print(f"GUARD={json.dumps(check, ensure_ascii=False)}", flush=True)
    run.log({"guard/both_branches_reachable": int(check.get("both_branches_reachable", False)),
             "guard/improving_prefers_rac": int(check.get("improving_prefers_rac", False)),
             "guard/passed": int(check["passed"])})
    for label, path in (("base", None), ("lora", saved.path)):
        sampler = service.create_sampling_client(base_model=BASE_MODEL, model_path=path)
        valid = 0
        for row in heldout:
            if sample_action(sampler, tokenizer, prompt_for(row), trio) != "invalid":
                valid += 1
        run.log({f"heldout/{label}_valid_fraction": valid / len(heldout)})
        print(f"{label}: {valid}/{len(heldout)} valid actions", flush=True)
    receipt = {"sampler_path": saved.path, "training_record_url": url, "base_model": BASE_MODEL,
               "train_examples": len(training), "balanced_examples": len(balanced),
               "raw_labels": raw_counts, "epochs": args.epochs,
               "learning_rate": args.learning_rate, "training_steps": steps,
               "heldout_examples": len(heldout), "guard": check,
               "history_sources": {task: str(source) for task, source in args.sources.items()}}
    write_json(args.output, receipt)
    swanlab.finish()
    if not check["passed"]:
        raise SystemExit("GUARD_FAILED: sampler cannot produce both branches consistently")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, default=Path("workspace/contest_optimization/v3"))
    parser.add_argument("--supplement-history", type=Path, help="Fill a training task with no accepted examples")
    parser.add_argument("--project", default="industrial-harness-sft")
    parser.add_argument("--name", default="industrial-harness-lora-v1")
    parser.add_argument("--output", type=Path, default=Path("workspace/contest_sampler/submission.json"))
    parser.add_argument("--epochs", type=int, default=DEFAULT_EPOCHS,
                        help="Passes over the balanced training set")
    parser.add_argument("--learning-rate", type=float, default=DEFAULT_LEARNING_RATE)
    parser.add_argument("--train", action="store_true", help="Start billable PyTRIO training and SwanLab cloud logging")
    parser.add_argument("--legacy-params", action="store_true",
                        help="Opt into the deprecated parameter-proposal contract; incompatible with the SDK callback")
    args = parser.parse_args()
    if args.legacy_params:
        print("WARNING: training against the legacy parameter-proposal contract; "
              "the result will not match the submitted SDK decision contract.", flush=True)
    training, heldout, args.sources = split_examples(
        args.history, args.supplement_history, legacy=args.legacy_params)
    print(f"Examples: A/B train={len(training)}, C heldout={len(heldout)}")
    for task, source in args.sources.items():
        rows = heldout if task == "C" else training
        rounds = [row["context"]["round"] if "context" in row else json.loads(row["prompt"][1]["content"])["round"]
                  for row in rows if row["task"] == task]
        print(f"{task}: {source} rounds={rounds}")
    if not args.legacy_params:
        balanced, counts = balance(training)
        steps = math.ceil(len(balanced) * max(1, args.epochs) / BATCH_SIZE)
        print(f"Labels: {counts} -> balanced {len(balanced)} rows, "
              f"{steps} steps at epochs={args.epochs}, lr={args.learning_rate}")
    if args.train:
        if args.output.exists():
            parser.error("--output already exists; specify a new result path")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        train(args, training, heldout)


if __name__ == "__main__":
    main()
