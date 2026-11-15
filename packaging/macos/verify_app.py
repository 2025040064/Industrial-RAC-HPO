"""Launch the built .app's own binary against a fresh workspace and run real work.

Drives the GUI offscreen through Qt (no Python from the checkout is used for the
work itself; it all runs inside the frozen executable and its spawned workers):
open window -> load Steel CSV -> baseline training -> 2-trial TPE search.
Usage: dist/智训引擎.app/Contents/MacOS/RAC-HPO is started with RAC_HPO_VERIFY=1.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "dist/智训引擎.app"
BINARY = APP / "Contents/MacOS/RAC-HPO"
STEEL = ROOT / "datasets/raw/steel_energy/Steel_industry_data.csv"


def main() -> int:
    if not BINARY.is_file():
        print(f"missing {BINARY}; run packaging/macos/build_app.sh first")
        return 1
    home = Path(tempfile.mkdtemp(prefix="rac-hpo-verify-", dir=ROOT / ".cache"))
    if STEEL.is_file():
        target = home / "datasets/raw/steel_energy/Steel_industry_data.csv"
        target.parent.mkdir(parents=True)
        shutil.copy2(STEEL, target)
    report = home / "verify.json"
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("PYTHON", "VIRTUAL_ENV", "DYLD", "UV_"))}
    env.update(RAC_HPO_HOME=str(home), RAC_HPO_VERIFY=str(report),
               QT_QPA_PLATFORM=env.get("QT_QPA_PLATFORM", "offscreen"),
               DYLD_PRINT_LIBRARIES="1")
    started = time.monotonic()
    process = subprocess.run([str(BINARY)], cwd="/", env=env, capture_output=True, text=True,
                             timeout=600)
    loaded = sorted({line.split()[-1] for line in process.stderr.splitlines()
                     if "libomp" in line and line.startswith("dyld")})
    result = json.loads(report.read_text(encoding="utf-8")) if report.is_file() else {}
    result.update(exit_code=process.returncode, seconds=round(time.monotonic() - started, 1),
                  libomp_loaded=loaded, workspace=str(home))
    outside = [path for path in loaded if not path.startswith(str(APP))]
    result["ok"] = (process.returncode == 0 and result.get("passed") is True and loaded and not outside)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        print(process.stderr[-3000:])
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
