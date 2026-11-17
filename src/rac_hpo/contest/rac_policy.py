"""Adapt fixed-parent contest trials to the shared RAC-HPO search policy."""

import math

import optuna

from rac_hpo.contest.policy import validate
from rac_hpo.domain.metrics import robust_metrics
from rac_hpo.optimization.rac_hpo.search import RACSearchPolicy


LEGACY_PROTOCOL = "contest-rac-hpo-v1"
PROTOCOL = "contest-rac-hpo-v2"
ALPHA = 0.3
EPSILON = 1e-8
SEED = 42


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

    def __init__(self, task, audit, *, protocol=PROTOCOL, seed=SEED, prioritize_bearing_feasibility=False):
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
            "learning_rate": {"type": "float", "low": 1e-5, "high": .01, "log": True},
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

    def propose(self, metadata, records, *, transfer_records=(), round_index=None):
        history, history_rounds, excluded = [], [], []
        seen = set()
        for position, record in enumerate(records, start=1):
            number = record.get("round", position) if isinstance(record, dict) else position
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
        seed = self.seed + (len(records) if round_index is None else round_index - 1)
        policy = RACSearchPolicy({**self.search_config, "seed": seed}, self.space,
                                 require_forward_quality=self.require_forward_quality)
        try:
            params, trace = policy.propose(history)
        except (ValueError, FloatingPointError) as error:
            params = None
            trace = {"method": "tpe_fallback", "reason": "surrogate_error", "error_type": type(error).__name__}

        seen = [trial["params"] for trial in history]
        if params in seen:
            params = None
            trace.update(method="tpe_fallback", reason="duplicate_candidate")
        transfer = []
        transfer_rounds = []
        for record in transfer_records:
            try:
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
                transfer.append({"params": params_old, "objective": objective / baseline_j})
                transfer_rounds.append(record["round"])
            except (KeyError, TypeError, ValueError, ArithmeticError):
                continue
        if transfer and len(history) < self.search_config["rac_hpo"]["minimum_history"]:
            observations = transfer + [{"params": item["params"],
                                         "objective": item["objective"] / self.baseline_objective}
                                        for item in history]
            params = self._fallback(observations, seed, startup_trials=2)
            trace.update(method="transfer_tpe", reason="parent_normalized_history")
        elif not history:
            params = {"learning_rate": metadata["learning_rate"], "batch_size": metadata["batch_size"],
                      "epochs": 2, "sampling_level": 1}
            trace["method"] = "checkpoint_reference"
        elif params is None:
            params = self._fallback(history, seed)
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
        if self.protocol == PROTOCOL:
            trace.update(history_rounds=history_rounds, excluded_history=excluded,
                         transfer_history_rounds=transfer_rounds)
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

    def _fallback(self, history, seed, startup_trials=None):
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
        for _ in range(32):
            trial = study.ask(fixed_distributions=distributions)
            if trial.params not in seen:
                return trial.params
            study.tell(trial, state=optuna.trial.TrialState.FAIL)
        raise RuntimeError("TPE did not sample a unique contest candidate")

    def _sampler(self, seed):
        return optuna.samplers.TPESampler(seed=seed, n_startup_trials=4)
