"""Bounded local simulation decisions driven by public validation history."""
import math


def validate(proposal):
    if set(proposal) != {"learning_rate", "batch_size", "epochs", "reason"}:
        raise ValueError("Decision must contain learning_rate, batch_size, epochs, reason")
    rate = proposal["learning_rate"]
    if isinstance(rate, bool) or not isinstance(rate, (int, float)) or not math.isfinite(rate) or not 1e-5 <= rate <= .01:
        raise ValueError("Learning rate outside local experiment budget")
    for name, lower, upper in (("batch_size", 16, 1024), ("epochs", 1, 5)):
        if type(proposal[name]) is not int or not lower <= proposal[name] <= upper:
            raise ValueError(f"Invalid {name}")
    if not isinstance(proposal["reason"], str) or not 1 <= len(proposal["reason"]) <= 2000:
        raise ValueError("Decision reason required")
    return proposal


def local_decision(context):
    config = context["metadata"]
    history = context["history"]
    rate = config["learning_rate"]
    reason = "Continue original checkpoint at its learning rate for a measured reference."
    if history:
        last = history[-1]
        rate = last["proposal"]["learning_rate"]
        if last["accepted"]:
            reason = "Previous candidate improved the public validation metric; continue selected weights."
        else:
            rate = max(1e-5, rate * .5)
            reason = "Previous candidate was rejected; resume selected weights with half the learning rate."
    return validate({"learning_rate": rate, "batch_size": config["batch_size"],
                     "epochs": 2, "reason": reason})


def optimized_decision(context):
    """Apply a bounded candidate schedule and adapt C after a rejected candidate."""
    metadata = context["metadata"]
    task = context["task"]
    history = context["history"]
    number = context["round"]
    rate = metadata["learning_rate"]
    batch = metadata["batch_size"]
    epochs = 2
    strategy = "uniform"
    target = None
    multiplier = None
    if task == "A" and number > 4:
        weak_classes = context["diagnostics"]["classes"]
        target = min(weak_classes, key=lambda label: weak_classes[label]["f1"])
        rate_scale, batch, epochs, multiplier = (
            (2, 16, 5, 2), (1, 32, 4, 16), (1, 16, 3, 4),
            (.5, 32, 4, 16), (2, 64, 3, 8), (.5, 16, 4, 4),
        )[number - 5]
        rate *= rate_scale
        strategy = "class_focus"
    elif task == "B":
        rate_scale, batch_scale, epochs, strategy = (
            (1, 1, 1, "unit_balanced"), (1, 4, 3, "unit_balanced"),
            (.5, .5, 1, "unit_balanced"), (.2, 1, 2, "uniform"),
            (.2, .25, 5, "unit_balanced"), (.1, 1, 4, "unit_balanced"),
            (.5, 2, 1, "uniform"), (.1, .25, 5, "unit_balanced"),
            (.05, 1, 3, "unit_balanced"), (.025, 1, 2, "uniform"),
        )[number - 1]
        rate *= rate_scale
        batch = int(batch * batch_scale)
    elif task == "C" and history:
        rate = history[-1]["proposal"]["learning_rate"]
        if not history[-1]["accepted"]:
            rate *= .5
            epochs = 1 if number > 6 else 2
    reason = f"Evaluate {strategy} from the selected checkpoint against public validation."
    if history:
        reason += f" Previous candidate accepted={history[-1]['accepted']}; selected metric={context['selected_metric']:.6f}."
    proposal = validate({"learning_rate": rate, "batch_size": batch, "epochs": epochs, "reason": reason})
    proposal["strategy"] = strategy
    if target is not None:
        proposal.update(target_class=target, sampling_multiplier=multiplier)
    return proposal


def accept_candidate(task, baseline_details, candidate_details, selected_value, value):
    improved = value > selected_value if task == "A" else value < selected_value
    if not improved:
        return False
    if task == "B":
        original = baseline_details["groups"]
        candidate = candidate_details["groups"]
        return original.keys() == candidate.keys() and all(
            candidate[key]["rmse"] <= original[key]["rmse"] for key in original)
    return True
