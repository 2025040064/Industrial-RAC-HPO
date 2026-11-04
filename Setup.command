#!/bin/zsh
set -eu
cd -- "${0:A:h}"
export UV_CACHE_DIR="$PWD/.cache/uv"
export UV_PYTHON_INSTALL_DIR="$PWD/.python"
export TMPDIR="$PWD/.cache/tmp"
export MPLCONFIGDIR="$PWD/.cache/matplotlib"
mkdir -p "$TMPDIR" "$MPLCONFIGDIR"
if command -v uv >/dev/null 2>&1; then
  UV_BIN=$(command -v uv)
elif [[ -x .cache/bootstrap/bin/uv ]]; then
  UV_BIN="$PWD/.cache/bootstrap/bin/uv"
else
  print 'Install uv first: https://docs.astral.sh/uv/getting-started/installation/'
  exit 1
fi
if [[ $(uname -m) == arm64 && ! -f /opt/homebrew/opt/libomp/lib/libomp.dylib ]]; then
  print 'LightGBM requires OpenMP. Install with: brew install libomp'
  exit 1
fi
"$UV_BIN" sync --frozen --extra test --python 3.11
.venv/bin/python scripts/verify_environment.py
print 'Ready. Launch ./Run-GUI.command. Download datasets explicitly using the CLI fetch command.'
