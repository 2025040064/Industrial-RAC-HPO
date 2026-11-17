"""Stage only verified SDK, reference model code and participant runtime files."""
import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from rac_hpo.contest.packages import digest, write_json

SDK_SHA256 = "c676c8beeef69cece9cbec5a633d05dbb9832eb22b6f761913f2315bd1f85133"
SDK_PREFIX = "contest-harness-sdk-1.0.2/"
BASELINE_CODE = {
    "__init__.py": "3363d6112a78e5b4de3508da13e543708fc6a9019c65f3c8bcecb5178a321d7a",
    "model.py": "325026d80747eb36f39c8df1be02b640ae21b3cd082827c66aacbdf273dd61c5",
    "data.py": "6099e312829ac3aaf48209ec1f618532c4a8552fedf73f09cf31c8876261db65",
}
PROJECT_CODE = (
    "__init__.py", "_io.py", "contest/__init__.py", "contest/continuation.py",
    "contest/packages.py", "contest/policy.py", "contest/rac_policy.py",
    "domain/__init__.py", "domain/metrics.py", "optimization/__init__.py",
)
SDK_FILES = ("pyproject.toml", "README.md", *(
    f"contest_harness/{name}.py" for name in (
        "__init__", "__main__", "cli", "data", "errors", "predict", "protocol", "round", "transport",
    )
))


def stage(sdk, baseline, destination):
    if digest(sdk) != SDK_SHA256:
        raise ValueError("SDK archive SHA-256 differs from the verified 1.0.2 artifact")
    baseline_bytes = {}
    with zipfile.ZipFile(baseline) as archive:
        for name, checksum in BASELINE_CODE.items():
            content = archive.read(f"baselines/{name}")
            if hashlib.sha256(content).hexdigest() != checksum:
                raise ValueError(f"Reference code checksum differs: {name}")
            baseline_bytes[name] = content

    destination.mkdir(parents=True, exist_ok=False)
    app = destination / "app"
    app.mkdir()
    shutil.copyfile(ROOT / "official_submission/Dockerfile", destination / "Dockerfile")
    shutil.copyfile(ROOT / "requirements-contest-local.lock", destination / "requirements.lock")
    shutil.copyfile(ROOT / "official_submission/contest_submission.py", app / "contest_submission.py")
    shutil.copyfile(ROOT / "LICENSE", app / "RAC-HPO-LICENSE")
    (app / "baselines").mkdir()
    for name, content in baseline_bytes.items():
        (app / "baselines" / name).write_bytes(content)
    source = ROOT / "src/rac_hpo"
    rac_core = sorted((source / "optimization/rac_hpo").glob("*.py"))
    for origin in [*(source / name for name in PROJECT_CODE), *rac_core]:
        target = app / "rac_hpo" / origin.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(origin, target)

    with tarfile.open(sdk) as archive:
        for name in (*SDK_FILES, "template/harness.py"):
            member = archive.getmember(SDK_PREFIX + name)
            if not member.isfile():
                raise ValueError(f"Expected regular SDK source file: {name}")
            target = app / "harness.py" if name == "template/harness.py" else destination / "sdk" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source_file, target.open("xb") as output:
                shutil.copyfileobj(source_file, output)

    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True)
    write_json(destination / "source-files.json", {
        "git_head": commit.stdout.strip(), "sdk_archive_sha256": SDK_SHA256,
        "baseline_archive_sha256": digest(baseline),
        "files": {path.relative_to(destination).as_posix(): digest(path)
                  for path in sorted(destination.rglob("*")) if path.is_file()},
    })


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    stage(args.sdk, args.baseline, args.output)
