"""Function library (Design Document, Chapter 5, Table 6).

Five predefined functions act on the simulated cell. The LLM only chooses them
and sets their order. It never writes robot code or raw coordinates (DD2). Every
function returns a step result with a status, a message and the new cell state
(Table 7), so the planner never decides by itself whether an action worked.

Two questions are still open. OD1 asks whether ask_operator may appear inside a
plan or is only called by the orchestrator. OD2 asks whether move_to and locate
stay visible to the planner. The stubs below keep all five functions until the
design review decides.
"""

# The statuses come from the feedback design of 30 September 2026 (Chapter 5).
STATUSES = ("success", "failed", "blocked", "not found")


def move_to(cell, position):
    """Move the arm to a named position from the capability file.

    Precondition: the position exists. Returns success, or blocked when the
    position is unknown.
    """
    raise NotImplementedError("move_to, see Design Document Table 6")


def pick(cell, part, source):
    """Pick a known part from a bin or a tray slot.

    Preconditions: gripper empty, arm at the source, part at the source. Returns
    success, not found when the part is missing, blocked when the gripper is full,
    or failed when a failure is injected.
    """
    raise NotImplementedError("pick, see Design Document Table 6")


def place(cell, part, slot):
    """Place the held part in a tray slot or the return position.

    Preconditions: gripper holds the part, arm at the slot, slot free. Returns
    success, or blocked when the slot is occupied.
    """
    raise NotImplementedError("place, see Design Document Table 6")


def locate(cell, part):
    """Report where a part is, or not found. Only reads the state."""
    raise NotImplementedError("locate, see Design Document Table 6")


def ask_operator(question):
    """Ask the operator a plain-text question and return the answer (see OD1)."""
    raise NotImplementedError("ask_operator, see Design Document Table 6 and OD1")
