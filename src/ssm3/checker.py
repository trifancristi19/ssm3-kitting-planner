"""Checker, Task B (Design Document, Chapter 8).

The checker replays every plan step by step on a copy of the cell state before
anything moves, and returns run, reject with a code and reason, or ask (DD3). It
reads the same capability file as the planner (DD5). It detects ambiguity itself,
and no instruction can change a cell rule (DD7). The baseline's plans pass the
same checks (DD4).

Not built yet. The first version reuses the Study 1 checker in study1.tasks
(Chapter 12). The rejection codes in Table 9 are a proposal, and the number of
attempts before the operator is asked is open decision OD3, so neither is fixed
here.
"""


def check(plan, state, capability):
    """Check a plan against the capability file and the latest cell state.

    Returns the check result of Table 7: verdict, step number, code and reason.
    """
    raise NotImplementedError("Checker, see Design Document Chapter 8")
