"""ExtraTrees trial-history models and strictly chronological forward checks."""
import numpy as np
from scipy.stats import spearmanr
from sklearn.ensemble import ExtraTreesRegressor

from rac_hpo.domain.metrics import normalized_objective


def encode(params, space):
    values = []
    for name, specification in space.items():
        value, low, high = params[name], specification["low"], specification["high"]
        if specification.get("log"):
            value, low, high = np.log(value), np.log(low), np.log(high)
        values.append(0.0 if high == low else (value - low) / (high - low))
    return np.array(values, dtype=float)


def decode(vector, space):
    result = {}
    for position, (name, specification) in enumerate(space.items()):
        low, high = specification["low"], specification["high"]
        fraction = float(np.clip(vector[position], 0, 1))
        value = np.exp(np.log(low) + fraction * (np.log(high) - np.log(low))) if specification.get("log") else low + fraction * (high - low)
        if "step" in specification:
            value = low + round((value - low) / specification["step"]) * specification["step"]
        if specification["type"] == "int":
            value = int(round(value))
        result[name] = max(low, min(high, value))
    return result


class TrialSurrogate:
    def __init__(self, history, space, baseline_errors, weights, alpha, epsilon, settings, seed):
        self.regimes = sorted(baseline_errors)
        self.baselines = np.array([baseline_errors[regime] + epsilon for regime in self.regimes])
        raw_weights = np.array([weights[regime] for regime in self.regimes], dtype=float)
        self.weights = raw_weights / raw_weights.sum()
        self.alpha = alpha
        self.X = np.array([encode(trial["params"], space) for trial in history])
        self.Y = np.array([[trial["metrics"]["regimes"][regime]["mae"] for regime in self.regimes]
                           for trial in history]) / self.baselines
        if not np.isfinite(self.X).all() or not np.isfinite(self.Y).all():
            raise ValueError("Surrogate features and targets must be finite")
        raw_costs = np.asarray([trial["duration_seconds"] for trial in history], dtype=float)
        self.cost_valid = bool(np.isfinite(raw_costs).all() and (raw_costs > 0).all())
        self.costs = np.log(np.maximum(raw_costs, 1e-6)) if self.cost_valid else np.zeros(len(history))
        self.settings, self.seed = settings, seed
        self.model = None
        self.cost_model = None
        self.forward_residuals = None

    def _model(self, trees=None):
        return ExtraTreesRegressor(n_estimators=trees or self.settings.surrogate_trees,
                                   min_samples_leaf=2, random_state=self.seed, n_jobs=1)

    def forward_check(self):
        predicted, truth, naive, coverages, prefixes = [], [], [], [], []
        cost_errors, naive_cost_errors, cost_predictions, cost_truth = [], [], [], []
        cost_ratio = self.settings.maximum_cost_log_mae_ratio
        first = max(self.settings.min_forward_train, len(self.X) - self.settings.forward_holdout)
        for index in range(first, len(self.X)):
            target = self.Y[:index, 0] if self.Y.shape[1] == 1 else self.Y[:index]
            model = self._model(trees=24).fit(self.X[:index], target)
            members = np.array([np.atleast_1d(tree.predict(self.X[index:index + 1])[0]) for tree in model.estimators_])
            mean, spread = members.mean(axis=0), members.std(axis=0)
            predicted.append(mean)
            truth.append(self.Y[index])
            naive.append(self.Y[:index].mean(axis=0))
            coverages.append(np.abs(self.Y[index] - mean) <= 1.96 * spread)
            prefixes.append({"training_trials": index, "held_out_trial_position": index})
            if cost_ratio is not None and self.cost_valid:
                prefix_costs = self.costs[:index]
                cost_model = self._model(trees=24).fit(self.X[:index], prefix_costs)
                predicted_cost = cost_model.predict(self.X[index:index + 1])[0]
                cost_errors.append(abs(predicted_cost - self.costs[index]))
                naive_cost_errors.append(abs(np.median(prefix_costs) - self.costs[index]))
                cost_predictions.append(predicted_cost)
                cost_truth.append(self.costs[index])
        if len(predicted) < 3:
            failed = {"passed": False, "reason": "insufficient_forward_holdouts", "forward_splits": prefixes,
                      "rank_correlation": None}
            return {**failed, "performance_validation": dict(failed), "cost_validation": dict(failed)}
        predicted, truth, naive = np.array(predicted), np.array(truth), np.array(naive)
        self.forward_residuals = truth - predicted
        error = float(np.abs(predicted - truth).mean())
        naive_error = float(np.abs(naive - truth).mean())
        scores = normalized_objective(predicted, self.weights, self.alpha)
        observed = normalized_objective(truth, self.weights, self.alpha)
        correlation = float(spearmanr(scores, observed).statistic) if np.ptp(scores) and np.ptp(observed) else None
        passed = (correlation is not None and np.isfinite(correlation)
                  and correlation >= self.settings.minimum_rank_correlation
                  and error <= self.settings.maximum_mae_ratio * max(naive_error, 1e-12))
        result = {"passed": bool(passed), "reason": "passed" if passed else "surrogate_quality_failed",
                  "normalized_mae": error, "naive_normalized_mae": naive_error,
                  "mae_vs_naive_ratio": error / max(naive_error, 1e-12),
                  "rank_correlation": correlation, "approximate_tree_band_coverage": float(np.mean(coverages)),
                  "uncertainty_kind": "uncalibrated tree dispersion; coverage is diagnostic only",
                  "forward_normalized_residuals": self.forward_residuals.tolist(),
                  "forward_splits": prefixes}
        result["performance_validation"] = {key: result[key] for key in (
            "passed", "reason", "normalized_mae", "naive_normalized_mae", "mae_vs_naive_ratio", "rank_correlation", "forward_splits")}
        if cost_ratio is not None and self.cost_valid:
            cost_error = float(np.mean(cost_errors))
            naive_cost_error = float(np.mean(naive_cost_errors))
            cost_passed = cost_error <= 1e-12 or cost_error < cost_ratio * naive_cost_error
            corr = float(spearmanr(cost_predictions, cost_truth).statistic) if (
                np.ptp(cost_predictions) and np.ptp(cost_truth)) else None
            result["cost_validation"] = {
                "passed": bool(cost_passed), "reason": "passed" if cost_passed else "cost_surrogate_quality_failed",
                "log_mae": cost_error, "median_baseline_log_mae": naive_cost_error,
                "mae_vs_naive_ratio": cost_error / max(naive_cost_error, 1e-12),
                "rank_correlation": corr if corr is None or np.isfinite(corr) else None,
                "forward_splits": prefixes, "maximum_log_mae_ratio": cost_ratio,
            }
        else:
            result["cost_validation"] = {"passed": False,
                "reason": "invalid_cost_history" if not self.cost_valid else "cost_validation_disabled",
                "rank_correlation": None, "forward_splits": prefixes}
        return result

    def fit(self):
        target = self.Y[:, 0] if self.Y.shape[1] == 1 else self.Y
        self.model = self._model().fit(self.X, target)
        self.cost_model = self._model().fit(self.X, self.costs) if self.cost_valid else None
        return self

    def predict(self, candidates):
        # Shape: candidates x trees x regimes. Tree dispersion is an approximation.
        members = np.stack([np.atleast_2d(tree.predict(candidates)).reshape(len(candidates), -1)
                            for tree in self.model.estimators_], axis=1)
        if self.forward_residuals is not None:
            # Search-only predictive draws: paired regime residual vectors retain
            # observed cross-regime dependence, without claiming calibrated CIs.
            rng = np.random.default_rng(self.seed + len(self.X))
            indices = rng.integers(0, len(self.forward_residuals), size=members.shape[:2])
            residuals = self.forward_residuals - self.forward_residuals.mean(axis=0)
            members = np.maximum(0, members + residuals[indices])
        costs = np.exp(np.clip(self.cost_model.predict(candidates), -20, 20)) if self.cost_model else np.ones(len(candidates))
        return members, costs
