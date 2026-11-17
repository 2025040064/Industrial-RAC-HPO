"""Run PyTRIO decisions on a narrow projection of public validation history."""
import json
import re

from rac_hpo.contest.packages import write_json
from rac_hpo.contest.policy import validate

BASE_MODEL = "Qwen/Qwen3.5-4B"
SYSTEM = (
    "You propose the next CPU continuation experiment for an industrial model. "
    "Use the supplied public validation history. Preserve checkpoint architecture and data splits. "
    "A maximizes Macro-F1. B and C minimize RMSE. B must keep every bearing's RMSE "
    "at or below its initial value. Return one JSON object only. Required keys: "
    "learning_rate (0.00001 to 0.01), batch_size (integer 16 to 1024), epochs "
    "(integer 1 to 5), strategy, reason (short string). The exact allowed strategies are "
    "uniform for any task, class_focus for A, and unit_balanced for B/C. "
    "For class_focus only, include target_class and sampling_multiplier (integer 1 to 16). "
    'Example: {"learning_rate":0.001,"batch_size":128,"epochs":2,"strategy":"uniform",'
    '"reason":"Measure a conservative continuation step."}'
)
ACTION_KEYS = {"learning_rate", "batch_size", "epochs", "strategy",
               "target_class", "sampling_multiplier"}
CLASSES = {"Ethanol", "Ethylene", "Ammonia", "Acetaldehyde", "Acetone", "Toluene"}


def decision_messages(context):
    task = context["task"]
    metric = "macro_f1" if task == "A" else "rmse"
    history = [
        {"round": row["round"], "action": {key: value for key, value in row["proposal"].items()
                                           if key in ACTION_KEYS},
         "value": row["metrics"][metric], "accepted": row["accepted"]}
        for row in context["history"][-3:]
    ]
    payload = {"task": task, "round": context["round"], "metric": metric,
               "baseline": context["baseline_metrics"][metric],
               "selected": context["selected_metric"], "history": history}
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, allow_nan=False)}]


def parse_action(text, task):
    if not isinstance(text, str):
        raise ValueError("Response has no text")
    text = text.strip().removesuffix("<|im_end|>").strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL)
    action = json.loads(fenced[1] if fenced else text)
    if not isinstance(action, dict):
        raise ValueError("Decision must be a JSON object")
    strategy = action.get("strategy")
    if not isinstance(strategy, str):
        raise ValueError("Missing or invalid strategy")
    strategy = {"uniform_sampling": "uniform"}.get(strategy, strategy)
    if strategy not in ({"uniform", "class_focus"} if task == "A" else {"uniform", "unit_balanced"}):
        raise ValueError("Strategy is incompatible with task")
    if strategy != "class_focus":
        for key in ("target_class", "sampling_multiplier"):
            if action.get(key) is None:
                action.pop(key, None)

    fields = set(action) - {"strategy"}
    if strategy == "class_focus":
        target = action.get("target_class")
        multiplier = action.get("sampling_multiplier")
        if (not isinstance(target, str) or target not in CLASSES
                or type(multiplier) is not int or not 1 <= multiplier <= 16):
            raise ValueError("Invalid class_focus target or multiplier")
        fields -= {"target_class", "sampling_multiplier"}
    validate({key: action[key] for key in fields})
    return {**action, "strategy": strategy}


class SamplerPolicy:
    def __init__(self, model, path):
        if model != BASE_MODEL:
            raise ValueError(f"Sampler policy currently supports {BASE_MODEL}")
        if path is not None and not path.startswith("trio://"):
            raise ValueError("Provide the full Sampler URI with --sampler-path or HARNESS_SAMPLER_PATH")
        self.model = model
        self.path = path
        self.client = None
        self.tokenizer = None

    def propose(self, context, trace_path):
        import pytrio as trio

        if self.client is None:
            self.client = trio.ServiceClient().create_sampling_client(self.model, model_path=self.path)
            self.tokenizer = self.client.get_tokenizer()
        messages = decision_messages(context)
        trace = {"model": self.model, "sampler_path": self.path, "attempts": []}
        try:
            for request in range(2):
                prompt = self.tokenizer.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
                ids = self.tokenizer.encode(prompt, add_special_tokens=False)
                sequence = self.client.sample(
                    prompt=trio.ModelInput.from_ints(ids),
                    sampling_params=trio.SamplingParams(max_tokens=384, temperature=0, seed=42,
                                                        stop=["<|im_end|>"]),
                    num_samples=1,
                ).result().sequences[0]
                response = {"text": sequence.text, "stop_reason": str(sequence.stop_reason),
                            "tokens": len(sequence.tokens)}
                trace["attempts"].append(response)
                try:
                    action = parse_action(sequence.text, context["task"])
                except ValueError as error:
                    response["validation_error"] = str(error)
                    if request == 1:
                        raise
                    messages[0]["content"] += (
                        " The previous response failed validation. Include ALL five required keys. "
                        "Always include a strategy field with an exact value. Use uniform if unsure."
                    )
                    continue
                trace["validated_action"] = action
                return action
        finally:
            write_json(trace_path, trace)
