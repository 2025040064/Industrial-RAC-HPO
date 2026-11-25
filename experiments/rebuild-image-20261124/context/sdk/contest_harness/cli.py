"""Process entry. The platform runs this file as describe, train or predict."""
import importlib
import os
import sys
import traceback

from .errors import HarnessError
from .predict import serve_predictions
from .protocol import MODEL_ACCESS, PROTOCOL, SDK_NAME, SDK_VERSION, emit, isolate_stdio


def load_submission():
    name = os.environ.get("CONTEST_SUBMISSION", "contest_submission")
    return importlib.import_module(name)


def describe(submission, writer):
    if not callable(getattr(submission, "train", None)) or not callable(getattr(submission, "predict", None)):
        raise HarnessError("SUBMISSION_INVALID")
    tasks = ("classification", "regression")
    if getattr(submission, "TASKS", None):
        tasks = tuple(submission.TASKS)
    if not tasks or any(task not in ("classification", "regression") for task in tasks):
        raise HarnessError("TASKS_INVALID")
    emit({
        "protocol": PROTOCOL,
        "model_access": MODEL_ACCESS,
        "sdk": SDK_NAME,
        "sdk_version": SDK_VERSION,
        "tasks": list(tasks),
    }, writer)


def fail(error, writer):
    code = error.code if isinstance(error, HarnessError) else "PARTICIPANT_EXCEPTION"
    detail = error.detail if isinstance(error, HarnessError) else "%s: %s" % (type(error).__name__, error)
    traceback.print_exc(file=sys.stderr)
    print(detail, file=sys.stderr)
    emit({"type": "round_failed", "error": code}, writer)


def main(argv):
    command = argv[1] if len(argv) > 1 else ""
    if command in ("-h", "--help"):
        print("usage: python3 /app/harness.py describe|train|predict", file=sys.stderr)
        return 0
    if command in ("-V", "--version"):
        print(SDK_VERSION)
        return 0
    if command == "describe":
        _, writer = isolate_stdio()
        try:
            describe(load_submission(), writer)
        except Exception as error:
            print(error, file=sys.stderr)
            return 1
        return 0
    if command == "train":
        reader, writer = isolate_stdio()
        try:
            from .round import Round
            rnd = Round.start(reader, writer)
            load_submission().train(rnd)
            if not rnd._finished:
                raise HarnessError("ROUND_NOT_FINISHED")
        except Exception as error:
            fail(error, writer)
            return 1
        return 0
    if command == "predict":
        reader, writer = isolate_stdio()
        try:
            serve_predictions(load_submission().predict, reader, writer)
        except Exception as error:
            traceback.print_exc(file=sys.stderr)
            return 1
        return 0
    print("usage: python3 /app/harness.py describe|train|predict", file=sys.stderr)
    return 2


def entry():
    raise SystemExit(main(sys.argv))
