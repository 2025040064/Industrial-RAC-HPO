"""Run the desktop client from this checkout: python main.py."""

import sys
from pathlib import Path


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root / "src"))
    from rac_hpo.interfaces.gui import launch_gui

    raise SystemExit(launch_gui(root))
