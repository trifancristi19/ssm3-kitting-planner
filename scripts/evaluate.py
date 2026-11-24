"""Print the six measures of run logs as a table: python scripts/evaluate.py [logs ...] [--tasks task_set.json]

The evaluator itself is in src/ssm3/evaluator.py. This file only puts src on the path, so the
evaluator runs from a fresh clone without installing the package.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ssm3.evaluator import main  # noqa: E402

if __name__ == "__main__":
    main()
