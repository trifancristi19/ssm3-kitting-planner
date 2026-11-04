"""Simulated kitting cell (Design Document, Chapters 4 and 12).

A state-based Python model of the cell: fixed supply bins, a tray with numbered
slots, a return position, a gripper that holds one part and the arm position.
The simulator is the authoritative source of the cell state (Table 2), and it can
inject failures, such as a part moved after planning (FR11).

Not built yet. The first version reuses the cell model of Study 1
(study1.tasks.simulate), as Chapter 12 says. Part IDs come from the capability
file, because the parts and kit variants are still open (OD11).
"""


class SimulatedCell:
    """The cell state and its changes. Only the function library changes it."""

    def __init__(self, capability):
        self.capability = capability

    def state(self):
        """Return a copy of the current cell state (Table 7, cell state)."""
        raise NotImplementedError("Simulated cell, see Design Document Chapters 4 and 12")

    def inject_failure(self, kind):
        """Change the state outside the plan, for example move a part (FR11, Chapter 9)."""
        raise NotImplementedError("Failure injection, see Design Document Chapter 9")
