"""Train a PyTRIO LoRA policy on accepted public-validation contest decisions."""
import argparse
import json
import math
from pathlib import Path

from rac_hpo.contest.packages import write_json
from rac_hpo.contest.sampler import BASE_MODEL, decision_messages, parse_action

BATCH_SIZE = 2


def examples(root, task):
    folder = root / task
    audit = json.loads((folder / "audit.json").read_text())
    recent = []
    rows = []
    for path in sorted(folder.glob("round-??.json")):
        round_result = json.loads(path.read_text())
        if round_result["task"] != task:
            raise ValueError(f"Invalid task in {path}")
        completion = json.dumps(round_result["proposal"], ensure_ascii=False, allow_nan=False)
        parse_action(completion, task)
        if round_result["accepted"]:
            prompt = decision_messages({
                "task": task, "round": round_result["round"], "baseline_metrics": audit["baseline_metrics"],
                "selected_metric": round_result["previous_selected_metric"], "history": recent,
            })
            rows.append((task, prompt, completion))
        recent.append(round_result)
    return rows


def split_examples(history, supplement=None):
    training = []
    sources = {}
    for task in ("A", "B"):
        source = history
        rows = examples(source, task)
        if not rows and supplement is not None:
            source = supplement
            rows = examples(source, task)
        if not rows:
            raise ValueError(f"No accepted decisions for {task}")
        training.extend(rows)
        sources[task] = source
    heldout = examples(history, "C")
    if not heldout:
        raise ValueError("No accepted decisions for held-out task C")
    return training, heldout, {**sources, "C": history}


def encode_prompt(tokenizer, messages):
    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True,
                                           enable_thinking=False)
    return tokenizer.encode(prompt, add_special_tokens=False)


def train(args, training, heldout):
    import numpy as np
    import pytrio as trio
    import swanlab

    run = swanlab.init(project=args.project, name=args.name, public=False,
                       mode="online", on_online_error="raise",
                       log_dir=str(args.output.parent / "swanlog"),
                       config={"base_model": BASE_MODEL, "rank": 8, "epochs": 1,
                               "batch_size": BATCH_SIZE, "learning_rate": 1e-4,
                               "train_a_examples": sum(task == "A" for task, _, _ in training),
                               "train_b_examples": sum(task == "B" for task, _, _ in training),
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
    for _, prompt, completion in training:
        prefix = encode_prompt(tokenizer, prompt)
        target = tokenizer.encode(completion, add_special_tokens=False)
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
        client.optim_step(trio.AdamParams(learning_rate=1e-4)).result()
        run.log({"train/loss": loss, "train/supervised_tokens": int(weights.sum())},
                step=index // BATCH_SIZE + 1)

    saved = client.save_weights_for_sampler(name=args.name).result()
    if not saved.path.startswith("trio://"):
        raise RuntimeError("Unexpected sampler path")
    receipt = {"sampler_path": saved.path, "training_record_url": url, "base_model": BASE_MODEL,
               "train_examples": len(training), "heldout_examples": len(heldout),
               "history_sources": {task: str(source) for task, source in args.sources.items()}}
    write_json(args.output, receipt)
    print(f"SAMPLER_PATH={saved.path}", flush=True)
    for label, path in (("base", None), ("lora", saved.path)):
        sampler = service.create_sampling_client(base_model=BASE_MODEL, model_path=path)
        valid = 0
        for task, prompt, _ in heldout:
            result = sampler.sample(prompt=trio.ModelInput.from_ints(encode_prompt(tokenizer, prompt)),
                                    sampling_params=trio.SamplingParams(
                                        max_tokens=384, temperature=0, seed=42, stop=["<|im_end|>"]),
                                    num_samples=1).result()
            try:
                parse_action(result.sequences[0].text, task)
            except (IndexError, ValueError):
                continue
            valid += 1
        run.log({f"heldout/{label}_valid_fraction": valid / len(heldout)})
        print(f"{label}: {valid}/{len(heldout)} valid actions", flush=True)
    swanlab.finish()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, default=Path("workspace/contest_optimization/v3"))
    parser.add_argument("--supplement-history", type=Path, help="Fill a training task with no accepted examples")
    parser.add_argument("--project", default="industrial-harness-sft")
    parser.add_argument("--name", default="industrial-harness-lora-v1")
    parser.add_argument("--output", type=Path, default=Path("workspace/contest_sampler/submission.json"))
    parser.add_argument("--train", action="store_true", help="Start billable PyTRIO training and SwanLab cloud logging")
    args = parser.parse_args()
    training, heldout, args.sources = split_examples(args.history, args.supplement_history)
    print(f"Examples: A/B train={len(training)}, C heldout={len(heldout)}")
    for task, source in args.sources.items():
        rows = heldout if task == "C" else training
        rounds = [json.loads(prompt[1]["content"])["round"] for label, prompt, _ in rows if label == task]
        print(f"{task}: {source} rounds={rounds}")
    print(f"Plan: {math.ceil(len(training) / BATCH_SIZE)} training steps, 1 sampler save, "
          f"{2 * len(heldout)} held-out inference requests.")
    if args.train:
        if args.output.exists():
            parser.error("--output already exists; specify a new result path")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        train(args, training, heldout)


if __name__ == "__main__":
    main()
