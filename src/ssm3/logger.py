"""Run logger (Design Document, Chapter 10).

Every run writes one log with the fields of Table 11, and the six measures are
computed from these logs alone (FR12). The log holds one JSON record per event, in
one file per run (proposal). API keys never appear in a log (NFR4).

Every record has the run ID, a sequence number, the time in UTC and the event
kind, plus the fields of that event. The event kinds cover the rows of Table 11:
run_start (task, instruction, variant, model, settings, prompt version),
planner_response (every answer, with its time and token use), check_result,
step_result, feedback (injected failures and what went back to the planner),
intervention (clarification, approval or correction, with waiting time) and
run_end (outcome and final tray).
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

EVENT_KINDS = (
    "run_start",
    "planner_response",
    "check_result",
    "step_result",
    "feedback",
    "intervention",
    "run_end",
)

# Environment variables whose values are secrets. Their values are removed from every record.
SECRET_SUFFIXES = ("_API_KEY", "_TOKEN", "_SECRET")
REMOVED = "[removed]"


def _secrets():
    return [value for name, value in os.environ.items() if name.upper().endswith(SECRET_SUFFIXES) and len(value) >= 8]


def _scrub(value, secrets):
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, REMOVED)
        return value
    if isinstance(value, dict):
        return {key: _scrub(item, secrets) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_scrub(item, secrets) for item in value]
    return value


class RunLog:
    """The log of one run. Keeps the records in memory and, with a folder, appends them to <run_id>.jsonl."""

    def __init__(self, run_id, folder=None, clock=None):
        self.run_id = run_id
        self.records = []
        self._clock = clock or (lambda: datetime.now(UTC))
        self.path = None
        if folder is not None:
            Path(folder).mkdir(parents=True, exist_ok=True)
            self.path = Path(folder) / f"{run_id}.jsonl"

    def event(self, kind, /, **fields):
        """Log one event and return its record. A field may itself be called kind."""
        if kind not in EVENT_KINDS:
            raise ValueError(f"unknown event kind {kind!r}, expected one of {EVENT_KINDS}")
        record = {
            "run_id": self.run_id,
            "seq": len(self.records) + 1,
            "time": self._clock().isoformat(),
            "event": kind,
            **fields,
        }
        record = _scrub(record, _secrets())
        line = json.dumps(record, ensure_ascii=False)  # fails early when a field cannot be stored as JSON
        self.records.append(record)
        if self.path is not None:
            with self.path.open("a", encoding="utf-8") as file:
                file.write(line + "\n")
        return record

    def of_kind(self, kind):
        """Return the records of one event kind, in order."""
        return [record for record in self.records if record["event"] == kind]


def read_log(path):
    """Read a run log file back into a list of records."""
    with Path(path).open(encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]
