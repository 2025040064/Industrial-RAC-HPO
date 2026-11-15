# PyInstaller spec for 智训引擎.app. Run through packaging/macos/build_app.sh.
# -*- mode: python -*-
import importlib.metadata
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, copy_metadata

ROOT = Path(SPECPATH).resolve().parents[1]
BUILD = Path(os.environ["RAC_HPO_BUILD_DIR"])
VERSION = os.environ["RAC_HPO_VERSION"]

# environment_snapshot() records every installed distribution and calls
# importlib.metadata.version(); ship the dist-info of the whole runtime set.
metadata = []
for distribution in importlib.metadata.distributions():
    name = distribution.metadata["Name"]
    if name and name.lower() not in {"pyinstaller", "pyinstaller-hooks-contrib", "altgraph",
                                     "macholib", "setuptools", "packaging"}:
        metadata += copy_metadata(name)

datas = [
    (str(ROOT / "configs/default.yaml"), "configs"),
    (str(ROOT / "uv.lock"), "."),
    (str(ROOT / "LICENSE"), "."),
    (str(BUILD / "build_info.json"), "."),
    *metadata,
]
# OpenMP: build_app.sh has already re-pointed LightGBM/XGBoost's @rpath at
# scikit-learn's bundled libomp, so PyInstaller resolves and ships exactly
# one libomp (macOS 11+) and no Homebrew copy.
binaries = []

hiddenimports = (
    collect_submodules("rac_hpo")  # pages and services are imported lazily
    + ["rac_hpo_app_verify"]
    + collect_submodules("optuna")
    + ["sklearn.ensemble", "sklearn.compose", "sklearn.impute", "sklearn.pipeline",
       "sklearn.preprocessing", "sklearn.model_selection", "xgboost", "ucimlrepo",
       "matplotlib.backends.backend_agg", "matplotlib.backends.backend_qtagg"]
)
excludes = ["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtQml", "PySide6.QtQuick",
            "PySide6.Qt3DCore", "IPython", "pytest", "torch", "cupy", "dask"]

analysis = Analysis(
    [str(ROOT / "packaging/macos/app_entry.py")],
    pathex=[str(ROOT / "src"), str(ROOT / "packaging/macos")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(analysis.pure)
executable = EXE(
    pyz, analysis.scripts, [],
    exclude_binaries=True,
    name="RAC-HPO",
    console=False,
    argv_emulation=False,
    target_arch="arm64",
    codesign_identity=None,
)
collected = COLLECT(executable, analysis.binaries, analysis.datas, name="RAC-HPO")
app = BUNDLE(
    collected,
    name="智训引擎.app",
    icon=str(BUILD / "icon/AppIcon.icns"),
    bundle_identifier="io.github.yraguo.rac-hpo",
    version=VERSION,
    info_plist={
        "CFBundleDisplayName": "智训引擎",
        "CFBundleName": "智训引擎",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSMinimumSystemVersion": os.environ.get("RAC_HPO_MIN_MACOS", "14.0"),
        "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": "Copyright 2026 Yraguo · Apache-2.0",
        "LSApplicationCategoryType": "public.app-category.developer-tools",
    },
)
