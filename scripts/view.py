"""Write and open the 2D replay of a run log: python scripts/view.py [demo_logs/<run>.jsonl]

The viewer itself is in src/ssm3/viewer.py. This file only puts src on the path, so the
viewer runs from a fresh clone without installing the package.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ssm3.viewer import main  # noqa: E402

if __name__ == "__main__":
    main()
