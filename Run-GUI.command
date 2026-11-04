#!/bin/zsh
set -eu
cd -- "${0:A:h}"
if [[ ! -x .venv/bin/python ]]; then
  print 'Missing project environment. Run ./Setup.command first.'
  exit 1
fi
mkdir -p .cache/matplotlib .cache/tmp
export MPLCONFIGDIR="$PWD/.cache/matplotlib"
export TMPDIR="$PWD/.cache/tmp"
export OMP_NUM_THREADS=4
export OPENBLAS_NUM_THREADS=4
exec .venv/bin/python main.py
