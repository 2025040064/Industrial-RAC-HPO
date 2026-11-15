"""Executed inside the frozen app when RAC_HPO_VERIFY is set. Real work only."""
import json
import time
from pathlib import Path


def _wait(app, window, timeout):
    deadline = time.monotonic() + timeout
    while window.controller.running and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)
    if window.controller.running:
        raise TimeoutError("worker did not finish")


def run(root: Path, report_path: str) -> int:
    from PySide6.QtWidgets import QApplication
    from rac_hpo.interfaces.gui.main_window import MainWindow
    from rac_hpo.interfaces.gui.theme import apply_theme

    report = {"root": str(root), "steps": {}, "passed": False}
    errors = []
    try:
        app = QApplication.instance() or QApplication([])
        apply_theme(app)
        window = MainWindow(root)
        window.show()
        window.controller.failed.connect(lambda message, trace: errors.append(message))
        report["steps"]["window"] = {"pages": window.pages.count(), "title": window.windowTitle()}
        expected = root / "datasets/raw/steel_energy/Steel_industry_data.csv"
        window.data_page.dataset_combo.setCurrentIndex(1)
        window.data_page.dataset_combo.setCurrentIndex(0)
        report["steps"]["default_path_in_workspace"] = window.data_page.path_edit.text() == str(expected)

        window.fetch_dataset("steel_energy")  # reuses the hash-verified file when present
        _wait(app, window, 180)
        report["steps"]["fetch"] = window.data_page.path_edit.text()

        window.import_dataset(window.data_page.path_edit.text())
        _wait(app, window, 120)
        report["steps"]["import_rows"] = (window.latest_result or {}).get("row_count")

        overrides = {"model": {"n_estimators": 20, "n_jobs": 2},
                     "optimization": {"max_trials": 2, "timeout_seconds": 60}}
        window.start_experiment("baseline", overrides)
        _wait(app, window, 180)
        baseline = window.latest_result or {}
        report["steps"]["baseline"] = {"status": baseline.get("status"),
                                       "overall_mae": baseline.get("metrics", {}).get("overall_mae")}
        window.start_experiment("tpe", overrides)
        _wait(app, window, 300)
        search = window.latest_result or {}
        report["steps"]["tpe"] = {"status": search.get("status"), "best_value": search.get("best_value"),
                                  "trials": len([t for t in search.get("trials", []) if t.get("number", -1) >= 0])}
        environment = json.loads(Path(search["directory"], "environment.json").read_text(encoding="utf-8"))
        report["steps"]["environment"] = {key: environment.get(key) for key in ("code_commit", "source_sha256")}
        report["steps"]["environment"]["kind"] = environment.get("distribution", {}).get("kind")
        report["passed"] = (not errors and report["steps"]["import_rows"] == 35040
                            and baseline.get("status") == "completed"
                            and search.get("status") == "completed"
                            and report["steps"]["tpe"]["trials"] == 2
                            and report["steps"]["environment"]["kind"] == "macos-app")
        window.navigation.setCurrentRow(0)
        window.resize(1280, 820)
        app.processEvents()
        shot = Path(report_path).with_name("window.png")
        window.grab().save(str(shot))
        report["steps"]["screenshot"] = str(shot)
        window.close()
    except Exception as exc:  # report, never hide
        import traceback
        report["exception"] = traceback.format_exc()
    report["errors"] = errors
    Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return 0 if report["passed"] else 1
