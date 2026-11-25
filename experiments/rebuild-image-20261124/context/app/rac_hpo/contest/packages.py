"""Verify immutable input packages and preserve separate task directories."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import tempfile
import zipfile

from rac_hpo._io import atomic_text

CHECKPOINTS = {
    "A": "fd1e08b2aad08b2e9754f9b2dfdc029481c0da7ecdedca0abb0ec6fcc818c757",
    "B": "c7d819fcee9d25459c583b5ffdb35593d4a47b524ed152d0226bf81a283314b4",
    "C": "98ec6e30e38aee56ca15b7d624a8f412226d46fe97b170667a567601c700bc4e",
}


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    atomic_text(path, json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
                overwrite=False)


def prepare(archive, destination, task):
    """Extract only into a new directory after validating all archive entries."""
    destination = Path(destination)
    with zipfile.ZipFile(archive) as source:
        entries = source.infolist()
        names = set()
        for entry in entries:
            name = PurePosixPath(entry.filename)
            mode = entry.external_attr >> 16
            if (name.is_absolute() or ".." in name.parts or "\\" in entry.filename
                    or ":" in entry.filename or entry.filename in names
                    or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR))):
                raise ValueError("Unsafe or duplicate ZIP member")
            names.add(entry.filename)
        if len(entries) > 10000 or sum(e.file_size for e in entries) > 2_000_000_000:
            raise ValueError("Package exceeds extraction limits")
        info = json.loads(source.read("baseline-info.json"))
        checksum = hashlib.sha256(source.read("checkpoint.npz")).hexdigest()
        if (info["dataset_key"] != task or checksum != CHECKPOINTS[task]
                or info["checkpoint_sha256"] != "sha256:" + checksum):
            raise ValueError("Task or baseline checkpoint identity mismatch")
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".package-", dir=destination.parent) as temporary:
            staging = Path(temporary) / "package"
            staging.mkdir()
            source.extractall(staging)
            manifest = {e.filename: digest(staging / e.filename) for e in entries if not e.is_dir()}
            write_json(staging / "package-manifest.json",
                       {"archive_sha256": digest(archive), "task": task, "files": manifest})
            staging.rename(destination)
    return verify(destination, task)


def verify(package, task):
    package = Path(package)
    manifest = json.loads((package / "package-manifest.json").read_text())
    if manifest["task"] != task:
        raise ValueError("Wrong package task")
    for name, checksum in manifest["files"].items():
        path = package / name
        if path.is_symlink() or not path.is_file() or digest(path) != checksum:
            raise ValueError(f"Package changed: {name}")
    if digest(package / "checkpoint.npz") != CHECKPOINTS[task]:
        raise ValueError("Baseline changed")
    return manifest
