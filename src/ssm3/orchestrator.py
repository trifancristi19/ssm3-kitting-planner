"""Orchestrator loop (Design Document, Chapter 9).

The orchestrator calls every other component, so every message passes one place
where it is checked and logged (Chapter 4). Nothing moves before the checker says
run. Table 10 lists what it does in each case for the open loop and the closed
loop.

Still open: the number of attempts before the operator is asked (OD3), the step
and time budget that stops a run safely (OD4), scripted or live operator answers
(OD5) and what the open loop does after a failed step (OD6).
"""

VARIANTS = ("open loop", "closed loop")


def run_order(order, variant):
    """Run one order from planning to the final tray and return the run log."""
    raise NotImplementedError("Orchestrator, see Design Document Chapter 9, Table 10")
