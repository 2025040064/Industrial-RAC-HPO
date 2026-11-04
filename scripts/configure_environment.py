"""Run with python -S after editable install to support Python 3.11 Chinese paths."""
import os
import sys
from pathlib import Path


def repair_editable_path(root: Path) -> bool:
    if os.name != "nt":
        return False
    path = root / ".venv/Lib/site-packages/_editable_impl_industrial_rac_hpo.pth"
    if not path.is_file():
        return False
    # Python 3.11 site reads .pth with the Windows locale. Escapes keep it ASCII.
    path.write_text(f"import sys; sys.path.insert(0, {ascii(str(root / 'src'))})\n", encoding="ascii")
    return True


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[1]
    print(f"Editable path compatibility configured: {repair_editable_path(project_root)}")
