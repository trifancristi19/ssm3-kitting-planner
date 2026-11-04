"""Run logger (Design Document, Chapter 10).

Every run writes one log with the fields of Table 11, and the six measures are
computed from these logs alone (FR12). The proposal is one JSON record per event,
in one file per run. API keys never appear in a log (NFR4).
"""


def log_event(run_id, event):
    """Append one event of a run to its log."""
    raise NotImplementedError("Logger, see Design Document Chapter 10, Table 11")
