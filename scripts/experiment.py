"""Run the task with the baseline, open loop and closed loop, then print the evaluator tables.

Start it with: python scripts/experiment.py

The runner itself is in src/ssm3/experiment.py. This file only puts src on the path, so it runs from a fresh clone.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ssm3.experiment import main  # noqa: E402

if __name__ == "__main__":
    main()
