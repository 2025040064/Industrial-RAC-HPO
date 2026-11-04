"""Render native Qt workspace from real saved experiments in an isolated local root."""

import argparse
import json
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--native", action="store_true")
    parser.add_argument("--exercise", action="store_true")
    parser.add_argument("--scale",type=float,default=1.0)
    parser.add_argument("--sizes", default="800x600,1280x880,1920x1080")
    args = parser.parse_args()
    session = ROOT / "workspace/verification/ui" / f"session-{time.time_ns()}"
    session.mkdir(parents=True)
    (session / "tmp").mkdir()
    os.environ["TEMP"] = os.environ["TMP"] = str(session / "tmp")
    os.environ["MPLCONFIGDIR"] = str(session / "matplotlib")
    os.environ["QT_SCALE_FACTOR"]=str(args.scale)
    os.environ["QT_QPA_PLATFORM"] = "windows" if args.native else "offscreen"
    sys.path.insert(0, str(ROOT / "src"))
    from PySide6.QtCore import QPoint, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QScrollArea, QWidget
    from rac_hpo.application.experiment_service import ApplicationService
    from rac_hpo.interfaces.gui.main_window import MainWindow
    from rac_hpo.interfaces.gui.theme import apply_theme

    (session / "configs").mkdir()
    shutil.copy2(ROOT / "configs/default.yaml", session / "configs/default.yaml")
    database = ROOT / "workspace/database/experiments.sqlite3"
    connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    try:
        connection.execute("BEGIN")
        records = [json.loads(row[0]) for row in connection.execute(
            "SELECT payload FROM experiments ORDER BY created_at DESC LIMIT 20",
        )]
        if not any(record.get("algorithm") == "baseline" for record in records):
            baseline_row = connection.execute(
                "SELECT payload FROM experiments WHERE algorithm='baseline' AND status='completed' ORDER BY created_at DESC LIMIT 1",
            ).fetchone()
            if baseline_row:
                records.append(json.loads(baseline_row[0]))
        for record in records:
            record["trials"] = [json.loads(row[0]) for row in connection.execute(
                "SELECT payload FROM trials WHERE experiment_id=? ORDER BY number", (record["id"],),
            )]
    finally:
        connection.close()
    service = ApplicationService(session)
    for record in records:
        service.repository.save_experiment(record)
        for trial in record["trials"]:
            service.repository.save_trial(record["id"], trial)
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    window = MainWindow(session)
    source = ROOT / "datasets/raw/steel_energy/Steel_industry_data.csv"
    summary = service.prepare_dataset(str(source))
    window.data_path = str(source)
    window._imported_dataset=summary["dataset_id"]
    window._imported_row_count=summary["row_count"]
    window.data_page.show_summary(summary)
    window.optimize_page.set_data_context(summary["dataset_id"])
    window.dataset_badge.setText(f"已导入：{summary['dataset_id']} · {summary['row_count']} 条")
    baseline = next((item for item in records if item["algorithm"] == "baseline" and item["status"] == "completed"), None)
    search = next((item for item in records if item["algorithm"] != "baseline" and item["status"] == "completed"), None)
    if baseline:
        window._snapshots[baseline["id"]]=baseline
        window.train_page.show_result(baseline)
    if search:
        window.open_workspace(search["id"])
        log = Path(search.get("directory", "")) / "logs/experiment.log"
        if log.is_file():
            for line in log.read_text(encoding="utf-8").splitlines()[-40:]:
                window.logs_page.append(line)
    window.show()
    QTest.qWait(100)
    report = {"scale":args.scale,"device_pixel_ratio":window.devicePixelRatioF(),"platform": app.platformName(), "session": str(session), "screenshots": [],
              "historical_experiment": search["id"] if search else None, "checks": [], "runs": []}
    pages = ["data", "training", "optimization", "history", "logs"]
    for size in args.sizes.split(","):
        width, height = map(int, size.split("x"))
        window.resize(width, height)
        for index, name in enumerate(pages):
            window.navigation.setCurrentRow(index)
            QTest.qWait(60)
            image = session / f"{name}-{size}.png"
            assert window.grab().save(str(image))
            overflow = [scroll.horizontalScrollBar().maximum() for scroll in window.pages.currentWidget().findChildren(QScrollArea)
                        if scroll.isVisible() and scroll.horizontalScrollBar().maximum() > 0]
            check = {"page": name, "requested_size": [width, height],
                     "actual_size": [window.width(), window.height()], "rail_width":window.sidebar.width(), "topbar_height":window.findChild(QWidget,"topbar").height(), "outer_horizontal_overflow": overflow}
            report["checks"].append(check)
            report["screenshots"].append(str(image))
            if name == "optimization":
                optimize = window.optimize_page
                for suffix,target in (("parallel",optimize.parallel_panel),("panels",optimize.panel_grid)):
                    optimize.scroll.ensureWidgetVisible(target)
                    QTest.qWait(40)
                    detail_image=session/f"optimization-{suffix}-{size}.png"
                    window.grab().save(str(detail_image));report["screenshots"].append(str(detail_image))
                if not optimize.workbench._wide:
                    optimize.workbench.open_records();QTest.qWait(40)
                    drawer_image=session/f"optimization-trials-drawer-{size}.png"
                    optimize.workbench.list_dialog.grab().save(str(drawer_image))
                    report["screenshots"].append(str(drawer_image));optimize.workbench.list_dialog.close()
                optimize.scroll.verticalScrollBar().setValue(0)
    if search:
        window.resize(1280, 880)
        window.open_workspace(search["id"])
        window.optimize_page.drawer.show_experiment(search)
        QTest.qWait(60)
        image = session / "run-detail-1280x880.png"
        window.grab().save(str(image))
        report["screenshots"].append(str(image))
        window.optimize_page.drawer.close_drawer()
    report['interaction_checks']=[]
    initial_input=(window.data_path,window.optimize_page.algorithm_combo.currentData(),window.optimize_page.seed_spin.value())
    if len(records)>=2:
        window.resize(1440,900);window.navigation.setCurrentRow(3);QTest.qWait(60)
        compare=window.compare_page
        compare.history_table.view.selectRow(0)
        observed=compare.experiment_id
        for record in records[:2]:compare.history_table.toggle_checked(record['id'])
        assert compare.experiment_id==observed
        compare.compare_selected();assert compare.comparison.count==2
        assert '不排名' in compare.comparison.scope_label.text()
        QTest.qWait(40)
        image=session/'runs-comparison-1440x900.png';window.grab().save(str(image));report['screenshots'].append(str(image))
        report['interaction_checks'].append({'check':'real_runs_side_by_side','passed':True,'ids':[r['id'] for r in records[:2]]})
        compare.history_table.details_button.click();QTest.qWait(40)
        assert compare.drawer.experiment_id==observed
        compare.drawer.close_drawer()
    if search:
        window.open_workspace(search['id']);page=window.optimize_page
        actual_trials=page.trial_table.records
        if len(actual_trials)>=2:
            for record in actual_trials[:2]:page.trial_table.toggle_checked(record['_id'])
            page.compare_trials();assert page.comparison.count==2
            QTest.qWait(40)
            image=session/'trials-comparison-1440x900.png';window.grab().save(str(image));report['screenshots'].append(str(image))
            report['interaction_checks'].append({'check':'real_trial_comparison','passed':True,'experiment_id':search['id']})
            page.comparison.hide()
            for record in actual_trials[:2]:page.trial_table.toggle_checked(record['_id'])
        schema=search.get('config',{}).get('optimization',{}).get('search_space',{})
        if schema:
            parameter=next(iter(schema))
            values=sorted(float(t['params'][parameter]) for t in search.get('trials',[]) if t.get('number',-1)>=0 and parameter in t.get('params',{}))
            if values:
                history_numbers=list(page.chart.trial_numbers)
                page.set_brush(parameter,values[0],values[len(values)//2])
                assert page.chart.trial_numbers==history_numbers
                assert page.trial_table.filtered_count<=len(actual_trials)
                page.scroll.ensureWidgetVisible(page.parallel_panel);QTest.qWait(40)
                image=session/'optimization-filtered-1440x900.png';window.grab().save(str(image));report['screenshots'].append(str(image))
                report['interaction_checks'].append({'check':'real_filter_scope','passed':True,'visible':page.trial_table.filtered_count,'total':len(actual_trials)})
                page.clear_brush()
        page.maximize_parallel();dialog=page._maximized[-1];QTest.qWait(40)
        assert dialog.experiment_id==search['id']
        image=session/'parallel-maximized.png';dialog.grab().save(str(image));report['screenshots'].append(str(image))
        QTest.keyClick(dialog,Qt.Key.Key_Escape)
        app.processEvents()
        assert not page._maximized
        report['interaction_checks'].append({'check':'parallel_maximized_context_and_escape','passed':True})
    assert initial_input==(window.data_path,window.optimize_page.algorithm_combo.currentData(),window.optimize_page.seed_spin.value())
    report['interaction_checks'].append({'check':'history_view_preserves_new_task_input','passed':True})
    if search:
        import copy
        fixture=copy.deepcopy(search);fixture['id']='FIXTURE-performance-only'
        template=next((t for t in fixture['trials'] if t.get('number',-1)>=0 and t.get('status')=='completed'),None)
        if template:
            fixture['trials']=[{**copy.deepcopy(template),'number':i,'objective':float(1+i%23)} for i in range(1000)]
            window.navigation.setCurrentRow(2);window.resize(1440,900)
            window.optimize_page.show_result(fixture)
            window.optimize_page.scroll.ensureWidgetVisible(window.optimize_page.parallel_panel)
            QTest.qWait(80)
            measurements=[]
            for row in (1,5,10,15):
                started=time.perf_counter()
                window.optimize_page.trial_table.view.selectRow(row);app.processEvents()
                measurements.append((time.perf_counter()-started)*1000)
            report['selection_benchmark']={'source':'test fixture; never stored or exported','trials':1000,'milliseconds':measurements,'target_ms':200,'passed':max(measurements)<=200}
            window.open_workspace(search['id'])
    if args.exercise:
        ticks = []
        heartbeat = QTimer()
        heartbeat.setInterval(20)
        heartbeat.timeout.connect(lambda: ticks.append(time.monotonic()))
        heartbeat.start()
        errors = []
        window.controller.failed.connect(lambda message, trace: errors.append(message))

        def wait_for_task():
            deadline = time.monotonic() + 90
            while window.controller.running and time.monotonic() < deadline:
                QTest.qWait(20)
            assert not window.controller.running, "Worker did not finish"
            assert not errors, errors

        for algorithm in ("baseline", "random", "tpe", "tpe_robust", "rac_hpo"):
            window.start_experiment(algorithm, {"model": {"n_estimators": 30, "n_jobs": 1},
                                              "optimization": {"max_trials": 3, "timeout_seconds": 30}})
            wait_for_task()
            result = window.latest_result
            assert result["status"] == "completed", result.get("failure_reason")
            assert result['config']['model']['n_estimators']==30
            assert result['config']['model']['n_jobs']==1
            assert result['config']['optimization']['max_trials']==3
            assert result['config']['optimization']['timeout_seconds']==30
            exported = window.export_experiment(result["id"], str(session / "exports"))
            assert (Path(exported) / "trials.csv").is_file()
            report["runs"].append({"id": result["id"], "algorithm": algorithm, "status": result["status"],
                                   "best_value": result["best_value"], "target_unit": result["target_unit"],
                                   "duration_seconds": result["duration_seconds"], "export": exported})
        cancelled = []

        def request_cancel(event):
            if event.get("type") == "trial_completed" and not cancelled:
                cancelled.append(True)
                window.controller.cancel()

        window.controller.progress.connect(request_cancel)
        window.start_experiment("tpe", {"model": {"n_estimators": 300, "n_jobs": 1},
                                        "optimization": {"max_trials": 1000, "timeout_seconds": 60}})
        wait_for_task()
        assert window.latest_result["status"] == "cancelled"
        report["runs"].append({"id": window.latest_result["id"], "status": "cancelled"})
        heartbeat.stop()
        report["heartbeat_ticks"] = len(ticks)
        report["heartbeat_max_gap_seconds"] = max((b - a for a, b in zip(ticks, ticks[1:])), default=0)
    window.close()
    app.processEvents()
    (session / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    failures = [item for item in report["checks"] if item["actual_size"] != item["requested_size"] or item["outer_horizontal_overflow"] or item["rail_width"]!=56 or item["topbar_height"]!=56]
    performance_failed=not report.get("selection_benchmark",{}).get("passed",True)
    print(json.dumps({"report": str(session / "verification.json"), "layout_failures": failures, "performance_failed":performance_failed,
                      "screenshots": len(report["screenshots"]), "runs": len(report["runs"])}, ensure_ascii=True))
    return bool(failures) or performance_failed


if __name__ == "__main__":
    raise SystemExit(main())
