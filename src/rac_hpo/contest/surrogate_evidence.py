"""Fail-closed validation of shadow predictions against subsequently trained trials."""
import math

from scipy.stats import spearmanr


def shadow_evidence(records, parent_sha, round_index):
    observations = []
    seen = set()
    for row in records:
        if not isinstance(row, dict):
            continue
        number, trace = row.get("round"), row.get("trace")
        if (type(number) is not int or not 1 <= number < round_index or number in seen
                or row.get("parent_sha256") != parent_sha or not isinstance(trace, dict)
                or trace.get("surrogate_shadow_rank") is not True
                or not isinstance(row.get("rac_params"), dict)
                or row["rac_params"] != trace.get("shadow_proposal")):
            continue
        values = [trace.get("predicted_objective"), row.get("robust_objective"), row.get("parent_objective")]
        if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in values):
            continue
        seen.add(number)
        observations.append((number, *values))
    observations.sort()
    proof = {"passed": False, "reason": "insufficient_matched_shadow_trials", "observations": len(observations),
             "rounds": [row[0] for row in observations]}
    if len(observations) < 3:
        return proof
    prediction = [row[1] for row in observations]
    truth = [row[2] for row in observations]
    if len(set(prediction)) < 2 or len(set(truth)) < 2:
        proof["reason"] = "flat_shadow_predictions_or_outcomes"
        return proof
    rank = float(spearmanr(prediction, truth).statistic)
    mae = sum(abs(row[1] - row[2]) for row in observations) / len(observations)
    naive = sum(abs(row[3] - row[2]) for row in observations) / len(observations)
    proof.update(rank_correlation=rank, mae=mae, naive_mae=naive)
    proof["passed"] = math.isfinite(rank) and rank >= 0 and mae <= 1.25 * max(naive, 1e-12)
    proof["reason"] = "validated_matched_shadow_trials" if proof["passed"] else "shadow_quality_failed"
    return proof
