"""Let ``python -m unittest tests.test_x`` find the shared ``_paths`` helper."""
from pathlib import Path
import sys

_TESTS = str(Path(__file__).resolve().parent)
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)
