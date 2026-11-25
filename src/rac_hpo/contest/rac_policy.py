"""Adapt fixed-parent contest trials to the shared RAC-HPO search policy."""

import math
import statistics

import optuna

from rac_hpo.contest.policy import validate
from rac_hpo.contest.transfer_gate import filter_transfer
from rac_hpo.contest.bearing_feasibility import assess_feasibility
from rac_hpo.domain.metrics import robust_metrics
from rac_hpo.optimization.rac_hpo.search import RACSearchPolicy


LEGACY_PROTOCOL = "contest-rac-hpo-v1"
PROTOCOL = "contest-rac-hpo-v2"
ALPHA = 0.3
EPSILON = 1e-8
SEED = 42
# A continuation round only has 1-5 epochs. Below this rate the update is too
# small to move a warm-started model, and the round is wasted on a candidate the
# acceptance gate then rejects. Measured on the public C package (10 rounds,
# real parent checkpoint): lr 1.1e-5 -> 37.91 MAE, lr 3e-3..1e-2 -> 36.74-36.78.
# Classification has a different objective scale and keeps the wider range.
REGRESSION_LEARNING_RATE_LOW = 3e-3
C_LEARNING_RATE_LOW = 1e-4
TASK_LEARNING_RATE_LOW = {
    "A": 1e-5,
    "B": REGRESSION_LEARNING_RATE_LOW,
    "C": C_LEARNING_RATE_LOW,
}


def conservative_alternative(dataset, params, parent_batch_size):
    """Build a conservative 1-epoch step; prevent tiny-batch step explosion on large C."""
    batch_size = int(params["batch_size"])
    if dataset == "C":
        batch_size = min(512, max(batch_size, int(parent_batch_size), 256))
    return {
        **params,
        "learning_rate": max(TASK_LEARNING_RATE_LOW[dataset], params["learning_rate"] / 2),
        "batch_size": batch_size,
        "sampling_level": 1,
        "epochs": 1,
    }


def regime_metrics(task, diagnostics, validation_units):
    if "overall" in diagnostics:
        return {"overall": {**diagnostics["overall"], "effective_independent_groups": None}}
    if task == "A":
        return {
            name: {"mae": 1.0 - row["f1"], "samples": row["samples"],
                   "effective_independent_groups": validation_units}
            for name, row in diagnostics["classes"].items()
        }
    if task == "B":
        return {
            name: {"mae": row["mae"], "samples": row["samples"], "effective_independent_groups": 1}
            for name, row in diagnostics["groups"].items()
        }
    subsets = {}
    for key, row in diagnostics["groups"].items():
        subset = key.rsplit("/", 1)[0]
        subsets.setdefault(subset, []).append({
            "absolute_error_sum": row["mae"] * row["samples"], "samples": row["samples"],
        })
    regimes = {}
    for subset, units in subsets.items():
        samples = sum(unit["samples"] for unit in units)
        regimes[subset] = {
            "mae": sum(unit["absolute_error_sum"] for unit in units) / samples,
            "samples": samples, "effective_independent_groups": len(units), "group_errors": units,
        }
    return regimes


class ContestRACPolicy:
    require_forward_quality = True

    def __init__(self, task, audit, *, protocol=PROTOCOL, seed=SEED, prioritize_bearing_feasibility=False,
                 transfer_cost_weight=0.05, transfer_mode="legacy", surrogate_mode="active",
                 cost_mode=None, enforce_shadow_evidence=False, bearing_mode="off"):
        if (isinstance(transfer_cost_weight, bool) or not math.isfinite(transfer_cost_weight)
                or not 0 <= transfer_cost_weight <= 1):
            raise ValueError("Invalid transfer cost weight")
        self.transfer_cost_weight = transfer_cost_weight
        if transfer_mode not in {"off", "legacy", "gated"} or surrogate_mode not in {"off", "shadow", "active"}:
            raise ValueError("Invalid contest search mode")
        if cost_mode not in {None, "off", "transfer", "acquisition", "both"} or bearing_mode not in {"off", "shadow", "active"}:
            raise ValueError("Invalid contest cost or bearing mode")
        self.transfer_mode, self.cost_mode, self.bearing_mode = transfer_mode, cost_mode, bearing_mode
        self.requested_surrogate_mode = surrogate_mode
        evidence_ok = audit.get("surrogate_evidence", {}).get("passed") is True
        self.surrogate_mode = "shadow" if enforce_shadow_evidence and surrogate_mode == "active" and not evidence_ok else surrogate_mode
        self.activation_reason = "missing_validated_shadow_evidence" if self.surrogate_mode != surrogate_mode else None
        self.protocol = protocol
        self.seed = seed
        self.task = task
        self.validation_units = audit["units"]["validation"] if protocol == LEGACY_PROTOCOL else None
        self.diagnostic_section = "classes" if task == "A" else "groups"
        if "overall" in audit["diagnostics"]:
            self.diagnostic_section = "overall"
        self.validation_counts = self._diagnostic_counts(audit["diagnostics"])
        self.bearing_rmse = (
            {name: row["rmse"] for name, row in audit["diagnostics"]["groups"].items()}
            if prioritize_bearing_feasibility and task == "B" and self.diagnostic_section == "groups"
            else {}
        )
        self.parent_bearing_rmse = ({name: row.get("rmse") for name, row in audit["diagnostics"]["groups"].items()}
                                    if task == "B" and self.diagnostic_section == "groups" else {})
        baseline = regime_metrics(task, audit["diagnostics"], self.validation_units)
        self.error_name = "one_minus_class_f1" if task == "A" else "mae"
        self.weak_class = max(baseline, key=lambda name: baseline[name]["mae"]) if task == "A" else None
        weights = {name: 1 for name in baseline} if task == "A" else {
            name: row["samples"] for name, row in baseline.items()
        }
        self.objective_config = {
            "baseline_errors": {name: row["mae"] for name, row in baseline.items()},
            "weights": weights, "alpha": ALPHA, "epsilon": EPSILON,
        }
        self.baseline_objective = self.score(audit["diagnostics"])["robust_objective"]
        self.space = {
            "learning_rate": {"type": "float", "low": TASK_LEARNING_RATE_LOW.get(task, REGRESSION_LEARNING_RATE_LOW),
                              "high": .01, "log": True},
            "batch_size": {"type": "int", "low": 16, "high": 512, "log": True},
            "epochs": {"type": "int", "low": 1, "high": 5},
            "sampling_level": {"type": "int", "low": 1, "high": 16 if task == "A" else 2},
        }
        self.search_config = {
            **self.objective_config,
            "rac_hpo": {"warmup_trials": 8, "minimum_history": 8, "min_forward_train": 5,
                        "forward_holdout": 3, "refit_interval": 1},
        }
        if protocol == PROTOCOL:
            self.search_config["rac_hpo"]["maximum_cost_log_mae_ratio"] = 1.0
        self.search_config["surrogate_mode"] = self.surrogate_mode
        if cost_mode is not None:
            self.search_config["rac_hpo"]["gamma"] = .5 if cost_mode in {"acquisition", "both"} else 0.0

    def score(self, diagnostics):
        regimes = regime_metrics(self.task, diagnostics, self.validation_units)
        result = robust_metrics(regimes, **self.objective_config)
        return {
            "robust_objective": result["robust_objective"],
            "normalized_group_errors": result["normalized_regime_mae"],
        }

    def configuration(self):
        return {
            "protocol": self.protocol, "parent_mode": "original_checkpoint", "base_seed": self.seed,
            "group_error": self.error_name, "space": self.space, "weak_class": self.weak_class,
            "baseline_objective": self.baseline_objective, "search_config": self.search_config,
        }

    def propose(self, metadata, records, *, transfer_records=(), round_index=None, excluded_params=()):
        if round_index is not None and (type(round_index) is not int or round_index < 1):
            raise ValueError("Invalid current round")
        prior_excluded = self._normalize_excluded_params(excluded_params)
        history, history_rounds, excluded = [], [], []
        seen = set()
        for position, record in enumerate(records, start=1):
            number = record.get("round", position) if isinstance(record, dict) else position
            if round_index is not None and (type(number) is not int or not 1 <= number < round_index):
                excluded.append({"round": number, "reason": "non_prior_round"})
                continue
            try:
                trial = self._trial(record)
            except (KeyError, TypeError, ValueError, ArithmeticError) as error:
                if self.protocol == LEGACY_PROTOCOL:
                    raise
                excluded.append({"round": number, "reason": type(error).__name__})
                continue
            if self.protocol == PROTOCOL:
                key = tuple(trial["params"][name] for name in self.space)
                if key in seen:
                    excluded.append({"round": number, "reason": "duplicate_candidate"})
                    continue
                seen.add(key)
            history.append(trial)
            history_rounds.append(number)
        cost_cpu_ready = bool(history) and all(
            isinstance(record.get("training_cpu_seconds"), (int, float))
            and not isinstance(record.get("training_cpu_seconds"), bool)
            and math.isfinite(record["training_cpu_seconds"]) and record["training_cpu_seconds"] > 0
            for record in records if isinstance(record, dict) and record.get("round") in history_rounds)
        if self.cost_mode in {"acquisition", "both"} and cost_cpu_ready:
            by_round = {record["round"]: record for record in records if isinstance(record, dict) and "round" in record}
            for number, trial in zip(history_rounds, history):
                trial["duration_seconds"] = by_round[number]["training_cpu_seconds"]
        elif self.cost_mode in {"acquisition", "both"}:
            self.search_config["rac_hpo"]["maximum_cost_log_mae_ratio"] = None
        seed = self.seed + (len(records) if round_index is None else round_index - 1)
        policy = RACSearchPolicy({**self.search_config, "seed": seed}, self.space,
                                 require_forward_quality=self.require_forward_quality)
        try:
            params, trace = policy.propose(history)
        except (ValueError, FloatingPointError, RuntimeError) as error:
            params = None
            trace = {"method": "tpe_fallback", "reason": "surrogate_error", "error_type": type(error).__name__}

        seen = [trial["params"] for trial in history]
        if params in seen or self._matches_any(params, prior_excluded):
            params = None
            trace.update(method="tpe_fallback", reason="duplicate_candidate")
        transfer_gate = {"reason": "disabled", "used": False, "eligible_count": 0, "excluded": []}
        if self.transfer_mode == "off":
            transfer_records = ()
        elif self.transfer_mode == "gated":
            if round_index is None:
                transfer_records = ()
                transfer_gate["reason"] = "missing_round_index"
            else:
                transfer_records, transfer_gate = filter_transfer(
                    transfer_records, self.objective_config["baseline_errors"], self.objective_config["weights"],
                    round_index, max_distance=.5, parameter_space=self.space, require_complete=True,
                    allowed_strategies={"uniform", "class_focus"} if self.task == "A" else {"uniform", "unit_balanced"},
                    weak_class=self.weak_class)
        else:
            transfer_gate = {"reason": "legacy_unvalidated", "used": False,
                             "eligible_count": 0, "excluded": []}
        transfer = []
        transfer_rounds = []
        for record in transfer_records:
            try:
                number = record["round"]
                if round_index is not None and (type(number) is not int or not 1 <= number < round_index):
                    continue
                params_old = record["rac_params"]
                baseline_j = record["parent_objective"]
                objective = record["robust_objective"]
                duration = record["training_seconds"]
                config = record["configuration"]
                if (not math.isfinite(baseline_j) or baseline_j <= 0 or not math.isfinite(objective)
                        or objective < 0 or not math.isfinite(duration) or duration <= 0
                        or set(params_old) != set(self.space)):
                    continue
                if any(isinstance(params_old[name], bool) or not math.isfinite(params_old[name])
                       or not spec["low"] <= params_old[name] <= spec["high"]
                       or (spec["type"] == "int" and not isinstance(params_old[name], int))
                       for name, spec in self.space.items()):
                    continue
                if config.get("strategy") == "class_focus" and config.get("target_class") != self.weak_class:
                    continue
                transfer.append({"params": params_old, "objective": objective / baseline_j,
                                 "duration_seconds": duration})
                transfer_rounds.append(record["round"])
            except (KeyError, TypeError, ValueError, ArithmeticError):
                continue
        if transfer and len(history) < self.search_config["rac_hpo"]["minimum_history"]:
            if self.transfer_mode == "legacy":
                transfer_gate.update(used=True, eligible_count=len(transfer))
            observations = transfer + [{"params": item["params"],
                                         "objective": item["objective"] / self.baseline_objective,
                                         "duration_seconds": item["duration_seconds"]}
                                        for item in history]
            effective_weight = self.transfer_cost_weight
            if self.cost_mode is not None:
                all_records = [*transfer_records, *(r for r in records if isinstance(r, dict) and r.get("round") in history_rounds)]
                cpu_ready = all_records and all(isinstance(r.get("training_cpu_seconds"), (int, float))
                            and not isinstance(r.get("training_cpu_seconds"), bool)
                            and math.isfinite(r["training_cpu_seconds"]) and r["training_cpu_seconds"] > 0 for r in all_records)
                if not cpu_ready:
                    effective_weight = 0.0
                else:
                    durations = {r["round"]: r["training_cpu_seconds"] for r in all_records}
                    for item, number in zip(observations, transfer_rounds + history_rounds):
                        item["duration_seconds"] = durations[number]
            median_cost = statistics.median(item["duration_seconds"] for item in observations)
            for item in observations:
                log_cost = math.log(item["duration_seconds"]) - math.log(median_cost)
                item["objective"] += effective_weight * max(-2.0, min(2.0, log_cost))
            params = self._fallback(observations, seed, startup_trials=2, extra_seen=prior_excluded)
            trace.update(method="transfer_tpe", reason="parent_normalized_history_cost_heuristic",
                         transfer_cost_method="bounded_log_relative_seconds", transfer_cost_weight=effective_weight,
                         transfer_cost_median_seconds=median_cost, tpe_observations=len(observations),
                         tpe_startup_trials=2, tpe_model_ready=len(observations) >= 2)
        elif not history:
            params = self._checkpoint_reference(metadata, round_index, prior_excluded)
            trace["method"] = "checkpoint_reference"
        elif params is None:
            params = self._fallback(history, seed, extra_seen=prior_excluded)
            trace.update(tpe_observations=len(history), tpe_startup_trials=4,
                         tpe_model_ready=len(history) >= 4)
            if self.bearing_rmse:
                trace["method"] = "bearing_constrained_tpe"
        if not all(math.isfinite(value) and self.space[name]["low"] <= value <= self.space[name]["high"]
                   for name, value in params.items()):
            raise ValueError("Contest RAC candidate outside the saved search space")
        rate, batch, epochs, sampling = (params[name] for name in self.space)
        proposal = validate({
            "learning_rate": float(rate), "batch_size": int(batch), "epochs": int(epochs),
            "reason": f"RAC-HPO decision: {trace['method']} ({trace['reason']}).",
        })
        proposal["strategy"] = "uniform"
        if sampling > 1 and self.task == "A":
            proposal.update(strategy="class_focus", target_class=self.weak_class,
                            sampling_multiplier=int(sampling))
        elif sampling > 1:
            proposal["strategy"] = "unit_balanced"
        trace.update(params=params, decision_seed=seed, group_error=self.error_name)
        trace.update(transfer_mode=self.transfer_mode, transfer_gate=transfer_gate,
                     requested_surrogate_mode=self.requested_surrogate_mode,
                     surrogate_mode=self.surrogate_mode, surrogate_activation_reason=self.activation_reason,
                     requested_cost_mode=self.cost_mode, cpu_cost_history_ready=cost_cpu_ready,
                     cost_prediction_source=("training_cpu_seconds" if self.cost_mode in {"acquisition", "both"}
                                             and cost_cpu_ready else "training_wall_seconds_diagnostic_only"),
                     bearing_mode=self.bearing_mode,
                     bearing_activation_reason="no_forward_validated_feasibility_model" if self.bearing_mode == "active" else None)
        if self.task == "B" and self.bearing_mode != "off":
            bearing_trace = assess_feasibility(records, self.parent_bearing_rmse, params, self.space, round_index)
            bearing_trace["requested_mode"] = self.bearing_mode
            trace["bearing_feasibility"] = bearing_trace
        if self.protocol == PROTOCOL:
            trace.update(history_rounds=history_rounds, excluded_history=excluded,
                         transfer_history_rounds=transfer_rounds if trace["method"] == "transfer_tpe" else [])
        if "predicted_regime_mae" in trace:
            trace["predicted_group_errors"] = trace.pop("predicted_regime_mae")
            trace["predicted_sample_weighted_group_error"] = trace.pop("predicted_overall_mae")
        return proposal, trace

    def _trial(self, record):
        params = record["rac_params"]
        duration = record["training_seconds"]
        objective = record["robust_objective"]
        diagnostics = record["diagnostics"]
        if self.protocol == PROTOCOL:
            if not isinstance(params, dict) or params.keys() != self.space.keys() or any(
                isinstance(params[name], bool) or not spec["low"] <= params[name] <= spec["high"]
                or (spec["type"] == "int" and not isinstance(params[name], int))
                for name, spec in self.space.items()
            ):
                raise ValueError("Invalid historical parameters")
            if isinstance(duration, bool) or not (math.isfinite(duration) and duration > 0):
                raise ValueError("Invalid historical training time")
            if self._diagnostic_counts(diagnostics) != self.validation_counts:
                raise ValueError("Historical validation counts differ")
            rows = self._diagnostic_rows(diagnostics)
            metric = "f1" if self.diagnostic_section == "classes" else "mae"
            upper_bound = 1.0 if metric == "f1" else math.inf
            if any(not (math.isfinite(row[metric]) and 0 <= row[metric] <= upper_bound)
                   for row in rows.values()):
                raise ValueError("Invalid historical group metric")
            if not math.isclose(self.score(diagnostics)["robust_objective"], objective,
                                rel_tol=1e-10, abs_tol=1e-12):
                raise ValueError("Historical objective differs from the fixed objective")
        trial = {
            "status": "completed", "params": params, "objective": objective, "duration_seconds": duration,
            "metrics": {"regimes": regime_metrics(self.task, diagnostics, self.validation_units)},
        }
        if self.bearing_rmse:
            values = {name: diagnostics["groups"][name]["rmse"] for name in self.bearing_rmse}
            if any(not math.isfinite(value) or value < 0 for value in values.values()):
                raise ValueError("Invalid historical bearing RMSE")
            trial["bearing_violation"] = max(
                (values[name] - reference) / max(reference, EPSILON)
                for name, reference in self.bearing_rmse.items()
            )
        return trial

    def _diagnostic_rows(self, diagnostics):
        rows = diagnostics[self.diagnostic_section]
        if not isinstance(rows, dict):
            raise ValueError("Invalid group diagnostics")
        return {"overall": rows} if self.diagnostic_section == "overall" else rows

    def _diagnostic_counts(self, diagnostics):
        return {name: row["samples"] for name, row in self._diagnostic_rows(diagnostics).items()}

    def _clamp_params(self, raw):
        clamped = {}
        for name, spec in self.space.items():
            value = min(max(raw[name], spec["low"]), spec["high"])
            clamped[name] = int(value) if spec["type"] == "int" else float(value)
        return clamped

    def _normalize_excluded_params(self, excluded_params):
        normalized = []
        for item in excluded_params or ():
            if not isinstance(item, dict) or not set(self.space).issubset(item):
                continue
            try:
                cand = {}
                for name, spec in self.space.items():
                    val = item[name]
                    if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val):
                        raise ValueError("invalid param")
                    cand[name] = int(round(val)) if spec["type"] == "int" else float(val)
                normalized.append(self._clamp_params(cand))
            except (TypeError, ValueError):
                continue
        return normalized

    @staticmethod
    def _matches_any(params, candidates):
        if params is None:
            return False
        for item in candidates:
            if (params["batch_size"] == item["batch_size"]
                    and params["epochs"] == item["epochs"]
                    and params["sampling_level"] == item["sampling_level"]
                    and math.isclose(params["learning_rate"], item["learning_rate"], rel_tol=1e-9, abs_tol=1e-12)):
                return True
        return False

    def _checkpoint_reference(self, metadata, round_index, prior_excluded=()):
        base_lr = float(metadata["learning_rate"])
        base_batch = int(metadata["batch_size"])
        default = self._clamp_params({
            "learning_rate": base_lr, "batch_size": base_batch, "epochs": 2, "sampling_level": 1,
        })
        if self.task == "A" or round_index is None:
            schedule = [
                default,
                self._clamp_params({"learning_rate": base_lr, "batch_size": base_batch, "epochs": 1, "sampling_level": 1}),
                self._clamp_params({"learning_rate": base_lr * 0.5, "batch_size": base_batch * 2, "epochs": 1, "sampling_level": 1}),
            ]
        elif self.task == "B":
            # Preserve v8-B's winning checkpoint_reference momentum on B, falling back
            # to 1-epoch gentle steps only if the exact tuple is already excluded.
            schedule = [
                default,
                self._clamp_params({
                    "learning_rate": REGRESSION_LEARNING_RATE_LOW,
                    "batch_size": max(128, base_batch),
                    "epochs": 1,
                    "sampling_level": 1,
                }),
                self._clamp_params({
                    "learning_rate": REGRESSION_LEARNING_RATE_LOW,
                    "batch_size": 192,
                    "epochs": 1,
                    "sampling_level": 1,
                }),
            ]
        else:
            if round_index == 1:
                schedule = [
                    self._clamp_params({
                        "learning_rate": max(base_lr, REGRESSION_LEARNING_RATE_LOW),
                        "batch_size": base_batch, "epochs": 2, "sampling_level": 1,
                    }),
                ]
            else:
                # On C, R1 at lr=3e-3, epochs=2 reaches the basin, after which repeating
                # (3e-3, 256, 2) at stage resets (R2/R4/R7/R9) overshot every time.
                c_pool = [
                    {"learning_rate": 1.0e-3, "batch_size": max(256, base_batch), "epochs": 1, "sampling_level": 1},
                    {"learning_rate": 5.0e-4, "batch_size": max(256, base_batch), "epochs": 1, "sampling_level": 1},
                    {"learning_rate": 2.5e-4, "batch_size": max(256, base_batch), "epochs": 1, "sampling_level": 1},
                    {"learning_rate": 1.5e-4, "batch_size": max(384, base_batch), "epochs": 1, "sampling_level": 1},
                    {"learning_rate": 1.0e-4, "batch_size": max(256, base_batch), "epochs": 1, "sampling_level": 1},
                    {"learning_rate": 7.5e-4, "batch_size": max(384, base_batch), "epochs": 1, "sampling_level": 1},
                ]
                if round_index <= 3:
                    offset = 0
                elif round_index <= 6:
                    offset = 1
                elif round_index <= 8:
                    offset = 2
                else:
                    offset = 3
                ordered = c_pool[offset:] + c_pool[:offset]
                schedule = [self._clamp_params(item) for item in ordered]
        for candidate in schedule:
            if not self._matches_any(candidate, prior_excluded):
                return candidate
        return schedule[0]

    def _fallback(self, history, seed, startup_trials=None, extra_seen=()):
        distributions = {}
        for name, spec in self.space.items():
            distribution = optuna.distributions.IntDistribution if spec["type"] == "int" else (
                optuna.distributions.FloatDistribution
            )
            distributions[name] = distribution(spec["low"], spec["high"], log=spec.get("log", False))
        sampler = self._sampler(seed) if startup_trials is None else optuna.samplers.TPESampler(
            seed=seed, n_startup_trials=startup_trials)
        study = optuna.create_study(direction="minimize", sampler=sampler)
        for trial in history:
            objective = trial["objective"]
            if self.bearing_rmse and "bearing_violation" in trial:
                violation = trial["bearing_violation"]
                objective = 1 + violation if violation > 0 else objective / (1 + objective)
            study.add_trial(optuna.trial.create_trial(
                params=trial["params"], distributions=distributions, value=objective,
            ))
        seen = [trial["params"] for trial in history]
        blocked = [*seen, *extra_seen]
        for _ in range(32):
            trial = study.ask(fixed_distributions=distributions)
            if not self._matches_any(trial.params, blocked):
                return trial.params
            study.tell(trial, state=optuna.trial.TrialState.FAIL)
        for _ in range(32):
            trial = study.ask(fixed_distributions=distributions)
            if trial.params not in seen:
                return trial.params
            study.tell(trial, state=optuna.trial.TrialState.FAIL)
        raise RuntimeError("TPE did not sample a unique contest candidate")

    def _sampler(self, seed):
        return optuna.samplers.TPESampler(seed=seed, n_startup_trials=4)
