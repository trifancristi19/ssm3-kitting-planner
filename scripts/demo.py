"""Start the Gate A demo (Design Document, Chapter 13): python scripts/demo.py

The demo itself is in src/ssm3/demo.py. This file only puts src on the path, so the
demo runs from a fresh clone without installing the package.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ssm3.demo import main  # noqa: E402

if __name__ == "__main__":
    main()
