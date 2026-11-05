"""Function library (Design Document, Chapter 5, Table 6).

Five predefined functions act on the simulated cell. The LLM only chooses them
and sets their order. It never writes robot code or raw coordinates (DD2). Every
function returns a step result with a status, a message and the new cell state
(Table 7), so the planner never decides by itself whether an action worked.

move_to, pick, place and locate work on the simulated cell. A failed or blocked
call never changes the state. ask_operator is still a stub.

Two questions are still open. OD1 asks whether ask_operator may appear inside a
plan or is only called by the orchestrator, so ask_operator stays a stub. OD2
asks whether move_to and locate stay visible to the planner, so all five
functions stay until the design review decides. The rejection codes, retry
counts, budgets and placement order (OD3, OD4, OD10) are not part of this module.
"""

from dataclasses import dataclass

# The statuses come from the feedback design of 30 September 2026 (Chapter 5).
STATUSES = ("success", "failed", "blocked", "not found")


@dataclass(frozen=True)
class StepResult:
    """The result of one step: a status, a plain message and the new cell state."""

    status: str
    message: str
    state: dict
    locations: tuple = ()


def _result(cell, status, message, locations=()):
    assert status in STATUSES
    return StepResult(status, message, cell.state(), tuple(locations))


def move_to(cell, position):
    """Move the arm to a named position from the capability file.

    Precondition: the position exists. Returns success, or blocked when the
    position is unknown.
    """
    if position not in cell.positions():
        return _result(cell, "blocked", f"{position} is not a known position")
    cell.set_arm(position)
    return _result(cell, "success", f"The arm is at {position}")


def pick(cell, part, source):
    """Pick a known part from a bin or a tray slot.

    Preconditions: gripper empty, arm at the source, part at the source. Returns
    success, not found when the part is missing, blocked when the gripper is full,
    or failed when a failure is injected.
    """
    state = cell.state()
    if state["gripper"] is not None:
        return _result(cell, "blocked", f"The gripper already holds {state['gripper']}")
    # Local choice, not in Table 6: raise at the design review.
    if not (cell.is_bin(source) or cell.is_slot(source)):
        return _result(cell, "blocked", f"{source} is not a bin or a tray slot")
    # Local choice, not in Table 6: raise at the design review.
    if state["arm"] != source:
        return _result(cell, "blocked", f"The arm is at {state['arm']}, not at {source}")
    if part not in cell.contents(source):
        return _result(cell, "not found", f"{part} is not at {source}")
    if cell.consume_pick_failure():
        return _result(cell, "failed", f"The pick of {part} from {source} failed")
    cell.take_into_gripper(part, source)
    return _result(cell, "success", f"The gripper holds {part} from {source}")


def place(cell, part, slot):
    """Place the held part in a tray slot or the return position.

    Preconditions: gripper holds the part, arm at the slot, slot free. Returns
    success, or blocked when the slot is occupied.
    """
    state = cell.state()
    # Local choice, not in Table 6: raise at the design review.
    if not (cell.is_slot(slot) or cell.is_return(slot)):
        return _result(cell, "blocked", f"{slot} is not a tray slot or the return position")
    # Local choice, not in Table 6: raise at the design review.
    if state["gripper"] != part:
        return _result(cell, "blocked", f"The gripper does not hold {part}")
    # Local choice, not in Table 6: raise at the design review.
    if state["arm"] != slot:
        return _result(cell, "blocked", f"The arm is at {state['arm']}, not at {slot}")
    if not cell.is_free(slot):
        return _result(cell, "blocked", f"{slot} is occupied")
    cell.release_from_gripper(slot)
    return _result(cell, "success", f"{part} is placed at {slot}")


def locate(cell, part):
    """Report where a part is, or not found. Only reads the state."""
    state = cell.state()
    found = []
    for group in ("bins", "slots"):
        found += [name for name, parts in state[group].items() if part in parts]
    if part in state["return"]:
        found.append(cell.capability["positions"]["return"])
    if state["gripper"] == part:
        found.append("GRIPPER")
    if not found:
        return _result(cell, "not found", f"{part} is not in the cell")
    return _result(cell, "success", f"{part} is at {', '.join(found)}", found)


def ask_operator(question):
    """Ask the operator a plain-text question and return the answer (see OD1)."""
    raise NotImplementedError("ask_operator, see Design Document Table 6 and OD1")
