"""Line-oriented prediction. Reply to each row before reading the next."""
import json
import math
import os
import sys
from pathlib import Path

from .errors import HarnessError
from .protocol import dump


class Sample:
    def __init__(self, task, inputs, context=None):
        self.task = task
        self.inputs = inputs
        self.context = context
        self.dataset_key = None if context is None else context["dataset_key"]
        self.artifact_id = None if context is None else context["artifact_id"]


def prediction_context():
    """Read contest.predict-context.v1 from the environment. Stdin stays the first sample."""
    raw = os.environ.get("CONTEST_PREDICTION_CONTEXT")
    if not raw:
        return None
    try:
        context = json.loads(raw)
        if (not isinstance(context, dict) or set(context) != {"protocol", "dataset_key", "task", "artifact", "artifact_id"}
                or context["protocol"] != "contest.predict-context.v1"
                or any(not isinstance(context[key], str) or not context[key].strip() for key in ("dataset_key", "task", "artifact_id"))
                or context["dataset_key"] not in ("A", "B", "C")
                or context["task"] not in ("classification", "regression")
                or not isinstance(context["artifact"], dict)):
            raise ValueError
        dataset = os.environ.get("CONTEST_DATASET_KEY")
        task = os.environ.get("CONTEST_TASK")
        if (dataset is not None and dataset != context["dataset_key"]) or (task is not None and task != context["task"]):
            raise ValueError
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        raise HarnessError("PREDICTION_CONTEXT_INVALID") from exc
    return context


def model_dir():
    return Path("/model")


def _finite_unit(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and 0 <= value <= 1


def _finite_nonnegative(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and value >= 0


def normalize_output(task, result):
    """Accept either the outputs value or a one-key {outputs: ...} object."""
    if isinstance(result, dict) and set(result) == {"outputs"}:
        outputs = result["outputs"]
    else:
        outputs = result
    if task == "classification":
        if not isinstance(outputs, list) or not outputs:
            raise HarnessError("PREDICTION_INVALID", "classification outputs must be a non-empty list")
        seen = set()
        for item in outputs:
            if not isinstance(item, dict) or set(item) != {"label", "score"}:
                raise HarnessError("PREDICTION_INVALID", "each label needs label and score")
            label, score = item["label"], item["score"]
            if not isinstance(label, str) or not label.strip() or len(label.encode("utf-8")) > 4096 or label in seen:
                raise HarnessError("PREDICTION_INVALID", "labels must be unique non-empty strings")
            if not _finite_unit(score):
                raise HarnessError("PREDICTION_INVALID", "scores must be finite numbers from 0 to 1")
            seen.add(label)
        if sum(item["score"] == max(piece["score"] for piece in outputs) for item in outputs) != 1:
            raise HarnessError("PREDICTION_INVALID", "exactly one label must hold the top score")
        return {"outputs": outputs}
    if task == "regression":
        if not isinstance(outputs, dict) or set(outputs) != {"value"} or not _finite_nonnegative(outputs["value"]):
            raise HarnessError("PREDICTION_INVALID", "regression output is {value: nonnegative finite number}")
        return {"outputs": outputs}
    raise HarnessError("PREDICTION_TASK_UNKNOWN", str(task))


def serve_predictions(predict, reader=None, writer=None):
    """Read {task, inputs} lines and write one validated prediction per line."""
    reader = sys.stdin if reader is None else reader
    writer = sys.stdout if writer is None else writer
    directory = model_dir()
    context = prediction_context()
    for line in reader:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            raise HarnessError("PREDICTION_REQUEST_INVALID") from exc
        if not isinstance(request, dict) or "inputs" not in request or not isinstance(request.get("task"), str):
            raise HarnessError("PREDICTION_REQUEST_INVALID")
        if context is not None and request["task"] != context["task"]:
            raise HarnessError("PREDICTION_TASK_MISMATCH")
        sample = Sample(request["task"], request["inputs"], context)
        body = normalize_output(sample.task, predict(sample, directory))
        writer.write(dump(body) + "\n")
        writer.flush()
