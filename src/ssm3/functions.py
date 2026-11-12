"""Function library (Design Document, Chapter 5, Table 6).

Five predefined functions act on the simulated cell. The LLM only chooses four of
them and sets their order. It never writes robot code or raw coordinates (DD2).
Every function returns a step result with a status, a message and the new cell
state (Table 7), so the planner never decides by itself whether an action worked.

move_to, pick, place and locate work on the simulated cell. A failed or blocked
call never changes the state. ask_operator is only called by the orchestrator,
never inside a plan (DD11). It passes the question to the operator of the console.

The preconditions of each function live in one place, the *_problem functions
below. The function turns a problem into a status of Table 6, and the checker
reports the same problem with its code of Table 9, so the two can never disagree
(DD5). Every tray slot has a base and a top level (DD18). The order of placement
follows from two preconditions, NO_BASE and PART_COVERED, with no extra field (DD19).
"""

from dataclasses import dataclass

# The statuses come from the feedback design of 30 September 2026 (Chapter 5).
STATUSES = ("success", "failed", "blocked", "not found")

# Not a position in the capability file: raise at the design review.
GRIPPER = "GRIPPER"


@dataclass(frozen=True)
class StepResult:
    """The result of one step: a status, a plain message and the new cell state.

    Table 7 also lists a step number. The orchestrator adds it, because it owns the numbering.
    """

    status: str
    message: str
    state: dict
    locations: tuple = ()


@dataclass(frozen=True)
class Problem:
    """A precondition that does not hold: the status of Table 6, the code of Table 9 and a reason."""

    status: str
    code: str
    reason: str


def _result(cell, status, message, locations=()):
    assert status in STATUSES
    return StepResult(status, message, cell.state(), tuple(locations))


# Preconditions, shared with the checker

def move_to_problem(cell, position):
    """The position exists (Table 6)."""
    if position not in cell.positions():
        return Problem("blocked", "UNKNOWN_POSITION", f"{position} is not a known position")
    return None


def pick_problem(cell, part, source):
    """Gripper empty, source a bin or slot, arm at the source, part there, nothing on top of it (Table 6)."""
    state = cell.state()
    if state["gripper"] is not None:
        return Problem("blocked", "GRIPPER_FULL", f"The gripper already holds {state['gripper']}")
    # Local choice, not in Table 6 or Table 9: raise at the design review.
    if not (cell.is_bin(source) or cell.is_slot(source)):
        return Problem("blocked", "UNKNOWN_POSITION", f"{source} is not a bin or a tray slot")
    if state["arm"] != source:
        return Problem("blocked", "ARM_NOT_THERE", f"The arm is at {state['arm']}, not at {source}")
    if part not in cell.contents(source):
        return Problem("not found", "PART_MISSING", f"{part} is not at {source}")
    if cell.is_covered(part, source):
        top = cell.contents(source)[-1]
        return Problem("blocked", "PART_COVERED", f"{top} lies on top of {part} at {source}")
    return None


def level_problem(cell, slot, level):
    """A level only for a tray slot, and only base or top (BAD_LEVEL, Chapters 5 and 8)."""
    if cell.is_return(slot) and level is not None:
        return Problem("blocked", "BAD_LEVEL", f"{slot} has no levels, so no level may be given")
    if cell.is_slot(slot) and level is not None and level not in cell.levels():
        return Problem("blocked", "BAD_LEVEL", f"{level} is not a level, expected one of {', '.join(cell.levels())}")
    return None


def place_problem(cell, part, slot, level=None):
    """Gripper holds the part, arm at the slot, level free, base before top, room in the return position (Table 6)."""
    state = cell.state()
    # Local choice, not in Table 6 or Table 9: raise at the design review.
    if not (cell.is_slot(slot) or cell.is_return(slot)):
        return Problem("blocked", "UNKNOWN_POSITION", f"{slot} is not a tray slot or the return position")
    bad_level = level_problem(cell, slot, level)
    if bad_level:
        return bad_level
    # Local choice, not in Table 6 or Table 9: raise at the design review.
    if state["gripper"] is None or state["gripper"] != part:
        return Problem("blocked", "PART_MISSING", f"The gripper does not hold {part}")
    if state["arm"] != slot:
        return Problem("blocked", "ARM_NOT_THERE", f"The arm is at {state['arm']}, not at {slot}")
    if cell.is_return(slot):
        if not cell.is_free(slot):
            return Problem("blocked", "LIMIT", f"{slot} is full (return_capacity)")
        return None
    # A place without a level means the base, only so that older plans stay valid (Chapter 5).
    level = level or "base"
    index = cell.levels().index(level)
    filled = len(cell.contents(slot))
    if filled > index:
        return Problem("blocked", "SLOT_OCCUPIED", f"The {level} of {slot} holds {cell.contents(slot)[index]}")
    if filled < index:
        return Problem("blocked", "NO_BASE", f"The base of {slot} is empty, so nothing can go on top")
    return None


# The functions of Table 6

def move_to(cell, position):
    """Move the arm to a named position from the capability file.

    Precondition: the position exists. Returns success, or blocked when the
    position is unknown.
    """
    problem = move_to_problem(cell, position)
    if problem:
        return _result(cell, problem.status, problem.reason)
    cell.set_arm(position)
    return _result(cell, "success", f"The arm is at {position}")


def pick(cell, part, source):
    """Pick a known part from a bin or a tray slot.

    Preconditions: gripper empty, arm at the source, part at the source, no part
    on top of it. Returns success, not found when the part is missing, blocked
    when the gripper is full or a part is on top of it, or failed when a failure
    is injected.
    """
    problem = pick_problem(cell, part, source)
    if problem:
        return _result(cell, problem.status, problem.reason)
    if cell.consume_pick_failure():
        return _result(cell, "failed", f"The pick of {part} from {source} failed")
    cell.take_into_gripper(part, source)
    return _result(cell, "success", f"The gripper holds {part} from {source}")


def place(cell, part, slot, level=None):
    """Place the held part on a level of a tray slot, or in the return position.

    level is "base" or "top", only for a tray slot. Left out, it means the base.
    Preconditions: gripper holds the part, arm at the slot, the level is free, the
    base holds a part before a place on top, the return position has room. Returns
    success, or blocked when the level is occupied, the base is missing, the return
    position is full or the level is not valid.
    """
    problem = place_problem(cell, part, slot, level)
    if problem:
        return _result(cell, problem.status, problem.reason)
    cell.release_from_gripper(slot)
    where = slot if cell.is_return(slot) else f"the {level or 'base'} of {slot}"
    return _result(cell, "success", f"{part} is placed at {where}")


def locate(cell, part):
    """Report where a part is, or not found. Only reads the state."""
    state = cell.state()
    found = []
    for group in ("bins", "slots"):
        found += [name for name, parts in state[group].items() if part in parts]
    if part in state["return"]:
        found.append(cell.capability["positions"]["return"])
    if state["gripper"] is not None and state["gripper"] == part:
        found.append(GRIPPER)
    if not found:
        return _result(cell, "not found", f"{part} is not in the cell")
    return _result(cell, "success", f"{part} is at {', '.join(found)}", found)


def ask_operator(question, operator):
    """Ask the operator a plain-text question and return the answer (DD11, Chapter 9).

    operator is a console operator (console.py). Only the orchestrator calls this.
    """
    return operator.ask(question)
