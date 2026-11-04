import os
import subprocess
import sys
from pathlib import Path


def test_python_starts_from_chinese_project_path_without_utf8_environment():
    environment = dict(os.environ)
    environment.pop("PYTHONUTF8", None)
    result = subprocess.run([sys.executable, "-c", "import rac_hpo; print(rac_hpo.__version__)"],
                            env=environment, capture_output=True)
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    from rac_hpo import __version__
    assert __version__.encode() in result.stdout


def test_cli_emits_utf8_for_the_chinese_project_path():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run([sys.executable, "-m", "rac_hpo", "fetch"], cwd=root, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert str(root) in result.stdout.decode("utf-8").replace("\\\\", "\\")
