"""Put this directory on sys.path so `import ui_content` resolves regardless of
how pytest is invoked.

Without this, pytest's default prepend import mode inserts `tests/` (the test
file's own directory, which has no __init__.py) rather than this package root,
so `import ui_content` only worked under `python3 -m pytest` run from here —
which happens to prepend the CWD. A bare `pytest`, or a run from the repo root,
would fail to collect.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
