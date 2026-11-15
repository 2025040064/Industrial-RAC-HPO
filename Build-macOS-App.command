#!/bin/zsh
# Double-click in Finder: builds dist/智训引擎.app and the .dmg, then self-checks it.
set -eu
cd -- "${0:A:h}"
./packaging/macos/build_app.sh
if [[ -f datasets/raw/steel_energy/Steel_industry_data.csv ]]; then
  print '==> Self-check: real training inside the built app'
  .cache/build/venv/bin/python packaging/macos/verify_app.py >/dev/null && print '    passed'
fi
open dist
