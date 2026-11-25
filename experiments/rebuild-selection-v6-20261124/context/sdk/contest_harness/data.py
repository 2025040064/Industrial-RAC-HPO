"""Read the public JSONL projection. Hidden rows are never mounted here."""
import json
from pathlib import Path

from .errors import HarnessError


def iter_jsonl(path):
    """Yield objects from a UTF-8 JSONL file. Blank lines are skipped."""
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise HarnessError("DATA_FILE_MISSING", str(source))
    with source.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise HarnessError("DATA_ROW_INVALID", "line %d" % number) from exc
            if not isinstance(row, dict) or not isinstance(row.get("id"), str) or "inputs" not in row:
                raise HarnessError("DATA_ROW_INVALID", "line %d" % number)
            yield row
