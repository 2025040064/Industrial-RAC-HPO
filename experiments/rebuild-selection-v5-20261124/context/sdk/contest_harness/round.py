"""One workspace v2 round. The host owns measurement, metering and the official prompt."""
import base64
import hashlib
import json
import shutil
import stat
import threading
from pathlib import Path, PurePosixPath

from .data import iter_jsonl
from .errors import HarnessError
from .protocol import PROTOCOL, emit, read_frame

_PATH = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_./-")
_MODEL_OPTIONS = frozenset((
    "messages", "tools", "tool_choice", "max_tokens", "temperature", "top_p", "stop",
    "frequency_penalty", "presence_penalty", "response_format", "parallel_tool_calls",
    "enable_thinking", "seed", "n",
))
_TEXT_LIMIT = 4000
_CONFIG_LIMIT = 65536
_FILE_LIMIT = 64
_BYTE_LIMIT = 64 * 1024 * 1024


def _text(value, limit=_TEXT_LIMIT):
    return isinstance(value, str) and bool(value.strip()) and len(value.encode("utf-8")) <= limit


def _safe_path(name):
    return (isinstance(name, str) and 1 <= len(name) <= 180 and set(name) <= _PATH
            and not name.startswith("/") and all(part not in ("", ".", "..") for part in name.split("/"))
            and len(PurePosixPath(name).parts) <= 8)


def _regular(path, root):
    """Reject symlinks inside root. Ancestors outside root are the platform mount."""
    path = Path(path)
    root = Path(root)
    current = path
    while True:
        if current.is_symlink():
            raise HarnessError("PATH_UNSAFE", str(path))
        if current == root or current.parent == current:
            break
        try:
            current.relative_to(root)
        except ValueError:
            break
        current = current.parent
    if not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
        raise HarnessError("PATH_UNSAFE", str(path))
    return path


class ModelReceipt:
    def __init__(self, call_id, response):
        self.call_id = call_id
        self.response = response

    @property
    def text(self):
        try:
            content = self.response["choices"][0]["message"].get("content")
        except (KeyError, IndexError, TypeError):
            return ""
        return content if isinstance(content, str) else ""


class DataView:
    def __init__(self, contract):
        projection = contract.get("public_projection") if isinstance(contract, dict) else None
        if not isinstance(projection, dict):
            projection = {}
        self.train_path = projection.get("train_path", "/data/train.jsonl")
        self.validation_path = projection.get("validation_path", "/data/validation.jsonl")

    def training_rows(self):
        return iter_jsonl(self.train_path)

    def validation_rows(self):
        return iter_jsonl(self.validation_path)


class ParentView:
    def __init__(self, frame):
        self.artifact_id = frame["parent_artifact"]["artifact_id"]
        self.checkpoint_sha256 = frame["parent_checkpoint_sha256"]
        self.receipt = frame["parent_artifact"]
        self.descriptor = self.receipt["artifact"]
        self.root = Path("/previous")

    def declared_paths(self):
        return list(self.descriptor["checkpoint_paths"]) + list(self.descriptor["code_paths"])

    def path(self, relative, root=None):
        """Return one mounted parent file after checking its declared digest."""
        if not _safe_path(relative):
            raise HarnessError("PARENT_PATH_UNSAFE", str(relative))
        files = self.receipt.get("files")
        item = next((entry for entry in files if entry.get("path") == relative), None) if isinstance(files, list) else None
        if item is None or relative not in self.declared_paths():
            raise HarnessError("PARENT_FILE_NOT_DECLARED", relative)
        base = self.root if root is None else Path(root)
        path = _regular(base / relative, base)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        expected = item.get("sha256", "")
        if expected.startswith("sha256:"):
            expected = expected[7:]
        if digest != expected:
            raise HarnessError("PARENT_DIGEST_MISMATCH", relative)
        return path


class Round:
    def __init__(self, frame, reader, writer):
        self.frame = frame
        self.prompt = frame["prompt"]
        self.prompt_version = frame["prompt_version"]
        self.dataset_key = frame["dataset_key"]
        self.round_index = frame["round_index"]
        self.stage_id = frame.get("stage_id", "")
        self.task = frame["task_contract"]
        self.model_name = frame["model_name"]
        self.max_output_tokens = frame["max_output_tokens"]
        self.limits = frame.get("resource_limits", {})
        self.wall_seconds = frame.get("wall_seconds")
        self.data = DataView(self.task)
        self.parent = ParentView(frame)
        self.state_path = frame.get("state_path")
        self.state_sha256 = frame.get("state_sha256") or ""
        self._parent_state_sha256 = self.state_sha256
        self.artifacts = list(frame.get("artifacts") or [])
        self.call_ids = []
        self.history_ids = []
        self._reader = reader
        self._writer = writer
        self._sequence = 0
        self._lock = threading.Lock()
        self._finished = False

    @classmethod
    def start(cls, reader=None, writer=None):
        import sys
        reader = sys.stdin if reader is None else reader
        writer = sys.stdout if writer is None else writer
        frame = read_frame(reader)
        _validate_start(frame)
        return cls(frame, reader, writer)

    def history(self):
        records = self._rpc("history_request", "history_response")["records"]
        if not isinstance(records, list):
            raise HarnessError("HISTORY_INVALID")
        identifiers = []
        for record in records:
            if not isinstance(record, dict) or not isinstance(record.get("id"), str) or not record["id"]:
                raise HarnessError("HISTORY_INVALID")
            identifiers.append(record["id"])
        if len(identifiers) != len(set(identifiers)):
            raise HarnessError("HISTORY_INVALID")
        self.history_ids = identifiers
        return records

    def model(self, messages, **options):
        """Send one model request. Do not prepend the official prompt; the host attaches it once."""
        if self._finished:
            raise HarnessError("ROUND_FINISHED")
        if not isinstance(messages, list) or not messages:
            raise HarnessError("MODEL_MESSAGES_REQUIRED")
        if any(not isinstance(message, dict) or message.get("role") not in ("system", "user", "assistant", "tool") for message in messages):
            raise HarnessError("MODEL_MESSAGE_INVALID")
        unknown = set(options) - (_MODEL_OPTIONS - {"messages"})
        if unknown:
            raise HarnessError("MODEL_OPTION_UNSUPPORTED", ",".join(sorted(unknown)))
        if "max_tokens" not in options:
            options = {**options, "max_tokens": self.max_output_tokens}
        limit = options["max_tokens"]
        if type(limit) is not int or not 1 <= limit <= self.max_output_tokens:
            raise HarnessError("MAX_TOKENS_INVALID")
        if "n" in options and (type(options["n"]) is not int or options["n"] < 1):
            raise HarnessError("MODEL_OPTION_UNSUPPORTED", "n")
        receipt = self._rpc("model_request", "model_response", messages=messages, **options)
        call_id = receipt.get("call_id")
        response = receipt.get("response")
        if not isinstance(call_id, str) or not call_id or call_id in self.call_ids or not isinstance(response, dict):
            raise HarnessError("MODEL_RECEIPT_INVALID")
        self.call_ids.append(call_id)
        return ModelReceipt(call_id, response)

    def transport(self):
        from .transport import model_transport
        return model_transport(self)

    def submit_candidate(self, directory, *, hypothesis, change_summary, configuration, seed,
                         checkpoint_paths, code_paths=(), predict_argv):
        if self._finished:
            raise HarnessError("ROUND_FINISHED")
        _declaration(hypothesis, change_summary, configuration, seed)
        if not isinstance(checkpoint_paths, (list, tuple)) or not checkpoint_paths:
            raise HarnessError("CHECKPOINT_REQUIRED")
        if not isinstance(code_paths, (list, tuple)):
            raise HarnessError("ARTIFACT_INVALID")
        argv = list(predict_argv)
        if not argv or any(not isinstance(arg, str) or not arg or "\x00" in arg for arg in argv):
            raise HarnessError("PREDICT_ARGV_INVALID")
        artifact = {
            "checkpoint_paths": list(checkpoint_paths),
            "code_paths": list(code_paths),
            "predict_argv": argv,
        }
        declared = artifact["checkpoint_paths"] + artifact["code_paths"]
        if any(not _safe_path(name) for name in declared) or len(set(declared)) != len(declared):
            raise HarnessError("ARTIFACT_INVALID")
        reply = self._rpc(
            "candidate_request", "candidate_response",
            parent_artifact_id=self.parent.artifact_id,
            parent_checkpoint_sha256=self.parent.checkpoint_sha256,
            hypothesis=hypothesis, change_summary=change_summary,
            configuration=configuration, seed=seed, artifact=artifact,
            files=_files(directory),
        )
        if not isinstance(reply.get("artifact_id"), str) or not reply["artifact_id"]:
            raise HarnessError("CANDIDATE_RECEIPT_INVALID")
        return reply

    def save_state(self, directory):
        if self._finished:
            raise HarnessError("ROUND_FINISHED")
        reply = self._rpc("state_request", "state_response", parent_state_sha256=self._parent_state_sha256, files=_files(directory, allow_empty=True))
        digest = reply.get("state_sha256")
        if not isinstance(digest, str):
            raise HarnessError("STATE_RECEIPT_INVALID")
        self.state_sha256 = digest
        return digest

    def state_workspace(self, directory):
        """Copy the read-only state mount into a new writable directory."""
        destination = Path(directory)
        if destination.exists() or destination.is_symlink():
            raise HarnessError("STATE_DESTINATION_EXISTS", str(destination))
        source = Path(self.state_path) if self.state_path else None
        files = []
        if source is not None:
            if source.is_symlink() or not source.is_dir():
                raise HarnessError("STATE_DIRECTORY_REQUIRED")
            if destination.resolve().is_relative_to(source.resolve()):
                raise HarnessError("STATE_DESTINATION_INSIDE_SOURCE")
            for item in source.rglob("*"):
                if item.is_symlink():
                    raise HarnessError("PATH_UNSAFE", str(item))
                if item.is_file():
                    files.append((_regular(item, source), item.relative_to(source)))
                elif not item.is_dir():
                    raise HarnessError("PATH_UNSAFE", str(item))
        destination.mkdir(parents=True)
        try:
            for item, relative in files:
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(item, target)
                target.chmod(0o600)
        except BaseException:
            shutil.rmtree(destination, ignore_errors=True)
            raise
        return destination

    def restore_artifact(self, artifact_id, directory):
        if self._finished:
            raise HarnessError("ROUND_FINISHED")
        matches = [item for item in self.artifacts if item.get("artifact_id") == artifact_id]
        if len(matches) != 1:
            raise HarnessError("ARTIFACT_UNKNOWN", str(artifact_id))
        receipt = matches[0]
        manifest, descriptor = receipt.get("files"), receipt.get("artifact")
        if not isinstance(manifest, list) or not 1 <= len(manifest) <= _FILE_LIMIT or not isinstance(descriptor, dict):
            raise HarnessError("ARTIFACT_INVALID")
        if set(descriptor) != {"checkpoint_paths", "code_paths", "predict_argv"}:
            raise HarnessError("ARTIFACT_INVALID")
        declared = list(descriptor["checkpoint_paths"]) + list(descriptor["code_paths"])
        if any(not _safe_path(name) for name in declared) or len(set(declared)) != len(declared):
            raise HarnessError("ARTIFACT_INVALID")
        encoded = json.dumps({"files": manifest, "artifact": descriptor}, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
        if "sha256:" + hashlib.sha256(encoded).hexdigest() != receipt.get("artifact_sha256"):
            raise HarnessError("ARTIFACT_RECEIPT_MISMATCH")
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=False)
        names, total = set(), 0
        try:
            for item in manifest:
                name, size = item["path"], item["size_bytes"]
                if not _safe_path(name) or name in names or type(size) is not int or size < 0:
                    raise HarnessError("ARTIFACT_INVALID")
                names.add(name)
                total += size
                if total > _BYTE_LIMIT:
                    raise HarnessError("ARTIFACT_LIMIT")
                target = root.joinpath(*name.split("/"))
                target.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                offset = 0
                with target.open("xb") as handle:
                    while offset < size:
                        length = min(65536, size - offset)
                        reply = self._rpc("artifact_read_request", "artifact_read_response", artifact_id=artifact_id, path=name, offset=offset, length=length)
                        chunk = base64.b64decode(reply["data_base64"], validate=True)
                        if not chunk or len(chunk) > length or reply.get("eof") is not (offset + len(chunk) == size):
                            raise HarnessError("ARTIFACT_READ_MISMATCH", name)
                        handle.write(chunk)
                        digest.update(chunk)
                        offset += len(chunk)
                expected = item["sha256"]
                if expected.startswith("sha256:"):
                    expected = expected[7:]
                if digest.hexdigest() != expected:
                    raise HarnessError("ARTIFACT_DIGEST_MISMATCH", name)
        except BaseException:
            shutil.rmtree(root, ignore_errors=True)
            raise
        if any(name not in names for name in declared):
            shutil.rmtree(root, ignore_errors=True)
            raise HarnessError("ARTIFACT_INVALID")
        return root

    def finish(self, *, selected_artifact_id, hypothesis, change_summary, reason, configuration, seed,
               history_ids=None, model_call_ids=None):
        if self._finished:
            raise HarnessError("ROUND_FINISHED")
        _declaration(hypothesis, change_summary, configuration, seed)
        if not _text(reason):
            raise HarnessError("REASON_REQUIRED")
        if not isinstance(selected_artifact_id, str) or not selected_artifact_id:
            raise HarnessError("SELECTION_REQUIRED")
        cited_history = list(self.history_ids if history_ids is None else history_ids)
        cited_calls = list(self.call_ids if model_call_ids is None else model_call_ids)
        if not cited_calls:
            raise HarnessError("MODEL_CALL_REQUIRED")
        if any(not isinstance(item, str) or not item for item in cited_history + cited_calls):
            raise HarnessError("REFERENCE_INVALID")
        if len(cited_history) != len(set(cited_history)) or len(cited_calls) != len(set(cited_calls)):
            raise HarnessError("REFERENCE_INVALID")
        if any(item not in self.call_ids for item in cited_calls):
            raise HarnessError("MODEL_CALL_UNKNOWN")
        if any(item not in self.history_ids for item in cited_history):
            raise HarnessError("HISTORY_UNKNOWN")
        with self._lock:
            emit({"type": "round_complete", "record": {
                "selected_artifact_id": selected_artifact_id,
                "hypothesis": hypothesis,
                "change_summary": change_summary,
                "reason": reason,
                "configuration": configuration,
                "history_ids": cited_history,
                "model_call_ids": cited_calls,
                "seed": seed,
            }}, self._writer)
            ack = read_frame(self._reader)
            if ack.get("type") != "round_ack" or ack.get("accepted") is not True:
                raise HarnessError("ROUND_ACK_MISSING")
            self._finished = True
        return ack

    def _rpc(self, kind, expect, **fields):
        with self._lock:
            if self._finished:
                raise HarnessError("ROUND_FINISHED")
            identifier = self._sequence
            self._sequence += 1
            emit({"type": kind, "id": identifier, **fields}, self._writer)
            reply = read_frame(self._reader)
            if reply.get("id") != identifier or reply.get("type") != expect:
                raise HarnessError("RPC_MISMATCH", expect)
            return reply


def _validate_start(frame):
    required = ("protocol", "prompt", "prompt_version", "dataset_key", "round_index", "task_contract",
                "model_name", "max_output_tokens", "parent_checkpoint_sha256", "parent_artifact", "artifacts")
    missing = [key for key in required if key not in frame]
    if missing:
        raise HarnessError("START_FIELD_MISSING", ",".join(missing))
    if frame["protocol"] != PROTOCOL or not _text(frame["prompt"], 8000) or not isinstance(frame["prompt_version"], str):
        raise HarnessError("START_INVALID")
    if frame["dataset_key"] not in ("A", "B", "C") or type(frame["round_index"]) is not int or frame["round_index"] < 1:
        raise HarnessError("START_INVALID")
    if not isinstance(frame["task_contract"], dict) or not isinstance(frame["model_name"], str) or not frame["model_name"]:
        raise HarnessError("START_INVALID")
    if type(frame["max_output_tokens"]) is not int or frame["max_output_tokens"] < 1:
        raise HarnessError("START_INVALID")
    parent = frame["parent_artifact"]
    if not isinstance(parent, dict) or not isinstance(parent.get("artifact_id"), str):
        raise HarnessError("START_INVALID")
    artifact = parent.get("artifact")
    if not isinstance(artifact, dict) or not artifact.get("checkpoint_paths"):
        raise HarnessError("START_INVALID")
    if not isinstance(frame["artifacts"], list):
        raise HarnessError("START_INVALID")


def _declaration(hypothesis, change_summary, configuration, seed):
    if not _text(hypothesis) or not _text(change_summary):
        raise HarnessError("EXPERIMENT_RECORD_REQUIRED")
    if not isinstance(configuration, dict):
        raise HarnessError("CONFIG_REQUIRED")
    encoded = json.dumps(configuration, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()
    if len(encoded) > _CONFIG_LIMIT:
        raise HarnessError("CONFIG_LIMIT")
    if type(seed) is not int or not -(2**63) <= seed < 2**63:
        raise HarnessError("SEED_INVALID")


def _files(directory, allow_empty=False):
    root = Path(directory)
    if root.is_symlink() or not root.is_dir():
        raise HarnessError("DIRECTORY_INVALID", str(root))
    files, total = [], 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise HarnessError("PATH_UNSAFE", str(path))
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if not _safe_path(relative):
            raise HarnessError("PATH_UNSAFE", relative)
        content = _regular(path, root).read_bytes()
        total += len(content)
        files.append({"path": relative, "data_base64": base64.b64encode(content).decode()})
        if len(files) > _FILE_LIMIT or total > _BYTE_LIMIT:
            raise HarnessError("ARTIFACT_LIMIT")
    if not files and not allow_empty:
        raise HarnessError("ARTIFACT_EMPTY")
    return files
