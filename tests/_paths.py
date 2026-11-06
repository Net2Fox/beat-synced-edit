"""Make the skill's runtime modules and the repository root importable in tests.

Import this module first in every test file: ``import _paths  # noqa: F401``.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "beat-sync-edit" / "scripts"

for path in (ROOT, SCRIPTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
