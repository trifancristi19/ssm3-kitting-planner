"""Capability file loader (Design Document, Chapters 4 and 6).

One capability file feeds both the planner prompt and the checker, so the two can
never describe a different cell (NFR2, decision DD5). The file lists the named
positions, the part IDs and the limits. config/capability_example.json is the
example from Chapter 6, with names invented for illustration. The real list of
parts is open decision OD11.
"""

import json
from pathlib import Path


def load_capability(path):
    """Read a capability file and return its content as a dict."""
    return json.loads(Path(path).read_text(encoding="utf-8"))
