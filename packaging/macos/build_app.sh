#!/bin/zsh
# Build dist/智训引擎.app and dist/智训引擎-<version>-macOS-arm64.dmg.
# The result runs on any Apple Silicon Mac with macOS 14+, without Python,
# uv, Homebrew or a terminal. Everything temporary stays under .cache/build.
set -eu
cd -- "${0:A:h}/../.."
ROOT=$PWD
BUILD="$ROOT/.cache/build"
VENV="$BUILD/venv"
export UV_CACHE_DIR="$ROOT/.cache/uv"
export UV_PYTHON_INSTALL_DIR="$ROOT/.python"
export UV_PROJECT_ENVIRONMENT="$VENV"
export TMPDIR="$ROOT/.cache/tmp"
export MPLCONFIGDIR="$ROOT/.cache/matplotlib"
export QT_QPA_PLATFORM=offscreen
mkdir -p "$BUILD" "$TMPDIR" "$MPLCONFIGDIR"

if [[ $(uname -m) != arm64 ]]; then
  print 'This build script targets Apple Silicon (arm64) only.'; exit 1
fi

# 1. uv: system copy, or a private one under .cache/bootstrap.
if command -v uv >/dev/null 2>&1; then
  UV=$(command -v uv)
elif [[ -x .cache/bootstrap/bin/uv ]]; then
  UV="$ROOT/.cache/bootstrap/bin/uv"
else
  print '==> Installing a private uv into .cache/bootstrap'
  /usr/bin/python3 -m pip install --quiet --target .cache/bootstrap/pylib uv
  mkdir -p .cache/bootstrap/bin
  ln -sf "$ROOT/.cache/bootstrap/pylib/bin/uv" .cache/bootstrap/bin/uv
  UV="$ROOT/.cache/bootstrap/bin/uv"
fi

# 2. Isolated build environment from the frozen lock (dev .venv untouched).
print '==> Syncing build environment from uv.lock'
"$UV" sync --frozen --no-editable --python 3.11 --quiet
"$UV" pip install --quiet --python "$VENV/bin/python" \
  'pyinstaller==6.22.3' 'pyinstaller-hooks-contrib==2026.10'
PY="$VENV/bin/python"
SITE=$("$PY" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
VERSION=$("$PY" -c 'import sys; sys.path.insert(0, "src"); import rac_hpo; print(rac_hpo.__version__)')

# 3. OpenMP. LightGBM/XGBoost wheels find libomp only via Homebrew/MacPorts
#    rpaths. Point them at scikit-learn's bundled libomp (same LLVM runtime,
#    exports every symbol they import) so only one OpenMP is shipped/loaded.
print '==> Re-pointing LightGBM/XGBoost OpenMP to scikit-learn libomp'
SKOMP="$SITE/sklearn/.dylibs/libomp.dylib"
[[ -f $SKOMP ]] || { print "missing $SKOMP"; exit 1; }
for lib in "$SITE/lightgbm/lib/lib_lightgbm.dylib" "$SITE/xgboost/lib/libxgboost.dylib"; do
  for rpath in $(otool -l "$lib" | awk '/LC_RPATH/{getline; getline; print $2}'); do
    install_name_tool -delete_rpath "$rpath" "$lib"
  done
  install_name_tool -add_rpath "@loader_path/../../sklearn/.dylibs" "$lib"
  codesign --force --sign - "$lib" 2>/dev/null
done
"$PY" -c 'import lightgbm, xgboost; print("    lightgbm", lightgbm.__version__, "xgboost", xgboost.__version__, "import ok")'

# 4. Build provenance: the app has no checkout, so record commit + source digest.
COMMIT=unversioned
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  COMMIT=$(git rev-parse --short=12 HEAD 2>/dev/null || print unversioned)
  [[ -n $(git status --porcelain -- src configs pyproject.toml uv.lock 2>/dev/null) ]] && COMMIT="$COMMIT-dirty"
fi
export RAC_HPO_BUILD_DIR="$BUILD" RAC_HPO_VERSION="$VERSION" RAC_HPO_COMMIT="$COMMIT"
"$PY" - <<'EOF'
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, "src")
from rac_hpo.infrastructure.artifacts import source_fingerprint
info = {"kind": "macos-app", "app_version": os.environ["RAC_HPO_VERSION"],
        "code_commit": os.environ["RAC_HPO_COMMIT"], "source_sha256": source_fingerprint(Path.cwd()),
        "built_at": datetime.now(timezone.utc).isoformat(), "target": "macOS 14+ arm64"}
Path(os.environ["RAC_HPO_BUILD_DIR"], "build_info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
print("    build", info["code_commit"], info["source_sha256"][:12])
EOF

# 5. Icon and bundle.
print '==> Rendering icon'
"$PY" packaging/macos/make_icon.py "$BUILD/icon" >/dev/null
print '==> Running PyInstaller (a few minutes)'
APP="dist/智训引擎.app"
rm -rf "$BUILD/work" "dist/RAC-HPO" "$APP"
"$PY" -m PyInstaller --noconfirm --log-level WARN \
  --distpath dist --workpath "$BUILD/work" packaging/macos/rac_hpo.spec
rm -rf "dist/RAC-HPO"   # intermediate COLLECT folder; the .app is the product

# 6. Self-check: no runtime dependency outside the bundle and macOS itself.
print '==> Checking linked libraries'
LEAKS=$(find "$APP" -type f \( -name '*.dylib' -o -name '*.so' -o -perm -u+x \) -print0 |
  xargs -0 otool -L 2>/dev/null | grep -E '^\s+/(opt|usr/local|Users|Library/Frameworks/Python)' || true)
if [[ -n $LEAKS ]]; then print "External library references found:\n$LEAKS"; exit 1; fi
codesign --force --deep --sign - "$APP" >/dev/null 2>&1
codesign --verify --deep --strict "$APP"

# 7. Disk image with a drag-to-Applications shortcut.
print '==> Creating disk image'
DMG="dist/智训引擎-$VERSION-macOS-arm64.dmg"
STAGE="$BUILD/dmg"
rm -rf "$STAGE" "$DMG"; mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -quiet -volname "智训引擎 $VERSION" -srcfolder "$STAGE" -fs HFS+ -format UDZO "$DMG"
rm -rf "$STAGE"
print "Done:\n  $ROOT/$APP ($(du -sh "$APP" | cut -f1))\n  $ROOT/$DMG ($(du -sh "$DMG" | cut -f1))"
