"""JSONL framing shared with the workspace v2 host."""
import json
import os
import sys

from .errors import HarnessError

PROTOCOL = "contest.harness.workspace.v2"
SDK_NAME = "contest_harness"
SDK_VERSION = "1.0.2"
MODEL_ACCESS = "host_gateway_rpc"


def dump(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def emit(value, writer):
    writer.write(dump(value) + "\n")
    writer.flush()


def read_frame(reader):
    line = reader.readline()
    if not line:
        raise HarnessError("HOST_STREAM_CLOSED")
    try:
        frame = json.loads(line)
    except json.JSONDecodeError as exc:
        raise HarnessError("HOST_FRAME_INVALID") from exc
    if not isinstance(frame, dict):
        raise HarnessError("HOST_FRAME_INVALID")
    return frame


def isolate_stdio():
    """Keep protocol frames on a private copy of stdout. Training logs use stderr."""
    sys.stdout.flush()
    protocol = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    os.dup2(2, 1)
    sys.stdout = open(1, "w", encoding="utf-8", buffering=1, closefd=False)
    return sys.stdin, protocol
