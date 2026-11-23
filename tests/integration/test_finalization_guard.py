"""Synthetic fixtures exercise final-evaluation crash and concurrency behavior."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
from threading import Event

import numpy as np
import pandas as pd
import pytest

from rac_hpo.application.experiment_service import ApplicationService
from rac_hpo.domain.schemas import PreparedDataset


@pytest.fixture
def synthetic_experiment(tmp_path, monkeypatch):
    (tmp_path / "configs").mkdir()
    root = Path(__file__).resolve().parents[2]
    shutil.copy2(root / "configs/default.yaml", tmp_path / "configs/default.yaml")
    values = np.arange(120, dtype=float)
    dataset = PreparedDataset(
        "synthetic_guard", "synthetic.csv", "fixture", ["x"], "y", "unit",
        pd.DataFrame({"x": values}), pd.Series(values % 17),
        pd.Series(["regime"] * 120), pd.Series([str(i // 10) for i in range(120)]),
        {"train": list(range(60)), "validation": list(range(60, 90)), "test": list(range(90, 120))},
        {"purpose": "synthetic finalization regression test"},
    )
    service = ApplicationService(tmp_path)
    monkeypatch.setattr(service, "_prepare", lambda *args, **kwargs: dataset)
    run = service.run_experiment("baseline", overrides={"model": {"n_estimators": 3, "n_jobs": 1}})
    assert run["status"] == "completed"
    return service, run, dataset


def test_failed_finalization_cannot_read_test_twice(synthetic_experiment, monkeypatch):
    service, run, dataset = synthetic_experiment
    original = dataset.split
    accessed = []

    def fail_on_test(name):
        accessed.append(name)
        if name == "test":
            raise RuntimeError("simulated interruption")
        return original(name)

    monkeypatch.setattr(dataset, "split", fail_on_test)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        service.finalize_experiment(run["id"])
    monkeypatch.setattr(dataset, "split", original)
    with pytest.raises(ValueError, match="already started"):
        service.finalize_experiment(run["id"])
    assert accessed.count("test") == 1
    claim = Path(run["directory"]) / "finalization_claim.json"
    assert json.loads(claim.read_text())["experiment_id"] == run["id"]


def test_concurrent_finalization_has_one_owner(synthetic_experiment, monkeypatch):
    service, run, dataset = synthetic_experiment
    entered, release = Event(), Event()

    def prepare(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return dataset

    monkeypatch.setattr(service, "_prepare", prepare)
    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(service.finalize_experiment, run["id"])
        assert entered.wait(10)
        try:
            with pytest.raises(ValueError, match="already started"):
                service.finalize_experiment(run["id"])
        finally:
            release.set()
        assert first.result()["test_rows"] == 30
    assert service.get_experiment(run["id"])["test_evaluation"]["test_rows"] == 30


def test_orphaned_saved_report_blocks_legacy_retry(synthetic_experiment):
    service, run, _ = synthetic_experiment
    (Path(run["directory"]) / "test_evaluation.json").write_text('{"legacy": true}')
    with pytest.raises(ValueError, match="saved test report"):
        service.finalize_experiment(run["id"])


def test_baseline_timeout_is_saved_with_budget_evidence(synthetic_experiment, monkeypatch):
    service, _, _ = synthetic_experiment
    clock = iter([0.0, 2.0])
    monkeypatch.setattr("rac_hpo.training.lightgbm_trainer.perf_counter", lambda: next(clock))
    run = service.run_experiment("random", overrides={"optimization": {"trial_timeout_seconds": 1.0}})
    assert run["status"] == "failed"
    assert run["failure_kind"] == "training_timeout"
    assert run["timeout"]["overrun_seconds"] == 1.0
    assert run["trials"][0]["timeout"] == run["timeout"]
    assert "model" not in run["artifacts"]


@pytest.mark.parametrize("all_failed", [False, True])
def test_search_timeout_retains_trials_and_only_selected_diagnostics(synthetic_experiment, monkeypatch, all_failed):
    from rac_hpo.domain.schemas import TrainingTimeout
    from rac_hpo.training.lightgbm_trainer import train
    service, _, _ = synthetic_experiment
    calls = 0

    def controlled_training(*args, **kwargs):
        nonlocal calls
        calls += 1
        assert kwargs["timeout_seconds"] == .2
        if calls > 1 and (all_failed or calls == 2):
            raise TrainingTimeout(.2, .3, 1)
        kwargs["timeout_seconds"] = None
        return train(*args, **kwargs)

    monkeypatch.setattr("rac_hpo.training.lightgbm_trainer.train", controlled_training)
    run = service.run_experiment("random", overrides={
        "model": {"n_estimators": 3, "n_jobs": 1},
        "optimization": {"max_trials": 3, "trial_timeout_seconds": .2}})
    assert len(run["trials"]) == 4
    assert run["trials"][1]["failure_kind"] == "training_timeout"
    assert run["trials"][0]["training_diagnostics"]["train_rows"] == 60
    if all_failed:
        assert run["status"] == "failed"
        assert "model" not in run["artifacts"]
        assert not run.get("training_diagnostics")
    else:
        assert run["status"] == "completed"
        assert run["best_trial"] in (1, 2)
        selected = next(trial for trial in run["trials"] if trial["number"] == run["best_trial"])
        assert run["training_diagnostics"] == selected["training_diagnostics"]
