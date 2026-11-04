"""Spawn-based task execution. Qt never performs model training."""

import multiprocessing as mp
import queue
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal


def run_worker(root, action, arguments, events, cancel_event):
    """Module-level target, importable by Windows multiprocessing spawn."""
    try:
        from rac_hpo.application.experiment_service import ApplicationService

        service = None if action.startswith('industrial_') else ApplicationService(Path(root))

        def progress(event):
            events.put({"type": "progress", "event": event})

        if action.startswith('industrial_'):
            from rac_hpo.application.industrial_service import IndustrialService
            industrial = IndustrialService(root)
            if action == 'industrial_audit':
                result = industrial.audit(**arguments)
            elif action == 'industrial_fetch':
                result = industrial.fetch(**arguments)
            elif action == 'industrial_run':
                result = industrial.run(**arguments, progress_callback=progress,
                                        cancel_check=cancel_event.is_set)
            else:
                raise ValueError(f'Unknown industrial action: {action}')
        elif action.startswith('loop_'):
            from rac_hpo.application.loop_service import LoopService
            loop = LoopService(root)
            if action == 'loop_create':
                manual = arguments.pop('manual_demo', False)
                session = loop.create_session(**arguments)
                progress({'type': 'loop_session_created', 'session_id': session['id']})
                result = loop.run_session(session['id'], manual_demo=manual,
                                         progress_callback=progress, cancel_check=cancel_event.is_set)
            elif action == 'loop_run':
                result = loop.run_session(**arguments, progress_callback=progress,
                                          cancel_check=cancel_event.is_set)
            elif action in {'loop_promote', 'loop_rollback', 'loop_decline'}:
                operation = {'loop_promote': loop.promote, 'loop_rollback': loop.rollback,
                             'loop_decline': loop.reject_release}[action]
                result = operation(**arguments)
            elif action == 'loop_export':
                result = {'export_path': loop.export_session(**arguments)}
            else:
                raise ValueError(f'Unknown loop action: {action}')
        elif action == "prepare":
            result = service.prepare_dataset(**arguments)
        elif action == "run":
            result = service.run_experiment(
                **arguments,
                progress_callback=progress,
                cancel_check=cancel_event.is_set,
            )
        else:
            raise ValueError(f"Unknown worker action: {action}")
        events.put({"type": "result", "result": result})
    except Exception as exc:
        events.put({"type": "error", "message": str(exc), "traceback": traceback.format_exc()})


class TaskController(QObject):
    progress = Signal(dict)
    finished = Signal(str, dict)
    failed = Signal(str, str)
    state_changed = Signal(str)

    def __init__(self, root, parent=None):
        super().__init__(parent)
        self.root = Path(root)
        self._process = None
        self._events = None
        self._cancel_event = None
        self._pending = None
        self.action = ""
        self.timer = QTimer(self)
        self.timer.setInterval(80)
        self.timer.timeout.connect(self._poll)

    @property
    def running(self):
        return self._process is not None

    def start(self, action, **arguments):
        if self.running:
            raise RuntimeError("Another task is already running")
        context = mp.get_context("spawn")
        self._events = context.Queue()
        self._cancel_event = context.Event()
        self._pending = None
        self.action = action
        self._process = context.Process(
            target=run_worker,
            args=(str(self.root), action, arguments, self._events, self._cancel_event),
            name="rac-hpo-worker",
        )
        try:
            self._process.start()
        except Exception:
            self._process = None
            self._events.close()
            self._events = None
            raise
        self.state_changed.emit("running")
        self.timer.start()

    def cancel(self):
        if self.running:
            self._cancel_event.set()
            self.state_changed.emit("cancelling")

    def _drain_events(self):
        while self._events is not None:
            try:
                event = self._events.get_nowait()
            except queue.Empty:
                break
            if event["type"] == "progress":
                payload = event["event"]
                self.progress.emit(payload if isinstance(payload, dict) else {"message": str(payload)})
            else:
                self._pending = event

    def _poll(self):
        self._drain_events()
        if self._process is None or self._process.is_alive():
            return
        self._process.join()
        # A terminal event can arrive between the first drain and observing exit.
        # The child has now flushed its queue feeder; consume that last event.
        self._drain_events()
        exit_code = self._process.exitcode
        self._process.close()
        self._process = None
        self.timer.stop()
        self._events.close()
        self._events = None
        self._cancel_event = None
        event = self._pending
        self._pending = None
        self.state_changed.emit("idle")
        if event and event["type"] == "result":
            self.finished.emit(self.action, event["result"])
        else:
            message = event.get("message", "") if event else f"Worker exited without a result (exit code {exit_code})"
            trace = event.get("traceback", "") if event else ""
            self.failed.emit(message, trace)
