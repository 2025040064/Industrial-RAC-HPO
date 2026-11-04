"""Read-only runtime check; all imports are the actual pinned project packages."""
import importlib
import importlib.metadata
import json
import sys
import os
import platform

packages = {
    "numpy": "numpy", "pandas": "pandas", "scipy": "scipy", "scikit-learn": "sklearn",
    "lightgbm": "lightgbm", "optuna": "optuna", "PySide6": "PySide6.QtWidgets",
    "matplotlib": "matplotlib", "pydantic": "pydantic", "PyYAML": "yaml", "pytest": "pytest",
}
versions = {}
for package, module in packages.items():
    importlib.import_module(module)
    versions[package] = importlib.metadata.version(package)
print(json.dumps({"python": sys.version, "executable": sys.executable,
                  "platform": platform.platform(), "machine": platform.machine(),
                  "cpu_count": os.cpu_count(), "regression_threads": 4,
                  "trial_execution": "serial", "packages": versions}, indent=2))
