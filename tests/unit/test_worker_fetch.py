"""The desktop app must be able to fetch the pinned public datasets without a terminal."""
import queue
import threading

import pytest

from rac_hpo.interfaces.gui.workers import run_worker


def _run(root, arguments):
    events = queue.Queue()
    run_worker(str(root), "fetch", arguments, events, threading.Event())
    return events.get_nowait()


def test_fetch_action_downloads_into_the_workspace(monkeypatch, tmp_path):
    calls = []

    def fake_download(dataset_id, root):
        calls.append((dataset_id, str(root)))
        return tmp_path / "datasets/raw/steel_energy/Steel_industry_data.csv"

    monkeypatch.setattr("rac_hpo.data.registry.download", fake_download)
    event = _run(tmp_path, {"dataset_id": "steel_energy"})
    assert event["type"] == "result", event
    assert calls == [("steel_energy", str(tmp_path))]
    assert event["result"] == {"dataset_id": "steel_energy",
                               "path": str(tmp_path / "datasets/raw/steel_energy/Steel_industry_data.csv")}


@pytest.mark.parametrize("dataset_id", ["../etc", "secom", ""])
def test_fetch_action_rejects_unknown_datasets(tmp_path, dataset_id):
    event = _run(tmp_path, {"dataset_id": dataset_id})
    assert event["type"] == "error"
    assert "Unsupported dataset" in event["message"]
