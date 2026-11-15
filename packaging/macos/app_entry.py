"""Entry point of the packaged macOS app (智训引擎.app).

Kept separate from main.py: the bundle has no src/ checkout, and the
workspace lives in the user's Application Support folder.
"""
import multiprocessing
import os
import sys


def _main():
    # Must run first: in a frozen app every multiprocessing "spawn" child
    # re-executes this binary, and freeze_support() turns it into the worker.
    multiprocessing.freeze_support()

    from rac_hpo.runtime import default_root

    root = default_root()
    for name in ("matplotlib", "tmp"):
        (root / ".cache" / name).mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(root / ".cache/matplotlib"))
    os.environ.setdefault("TMPDIR", str(root / ".cache/tmp"))
    # Same thread caps as Run-GUI.command.
    os.environ.setdefault("OMP_NUM_THREADS", "4")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "4")

    if os.environ.get("RAC_HPO_VERIFY"):
        # Release self-check driven by packaging/macos/verify_app.py.
        from rac_hpo_app_verify import run
        return run(root, os.environ["RAC_HPO_VERIFY"])

    from rac_hpo.interfaces.gui import launch_gui

    return launch_gui(root)


if __name__ == "__main__":
    sys.exit(_main())
