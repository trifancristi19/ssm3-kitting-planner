"""Evaluator (Design Document, Chapter 10).

The evaluator compares each final tray with the expected result in the task set
and computes the six measures as Chapter 6 of the project plan defines them.
Repeating a run follows a documented rule, never whether the model succeeded.
"""

MEASURES = (
    "task success",
    "plan validity",
    "blocked unsafe actions",
    "human intervention",
    "recovery",
    "latency",
)


def compute_measures(run_logs, task_set):
    """Return the six measures computed from the run logs alone."""
    raise NotImplementedError("Evaluator, see Design Document Chapter 10")
