"""Target trays for fake planners in the tests (DD25).

Since DD25 every plan of the planner also gives the tray it intends. A fake planner
in a test usually means "the tray my plan builds", so add_target works that out by
replaying the plan on a copy of the cell. A test that needs another target gives
it in the answer itself, and add_target leaves that answer alone.
"""

import json

from ssm3 import functions
from ssm3.cell import SimulatedCell

# The tray order K-17 of Chapter 13 asks for: the long spacer in slot 2, slots 1 and 3 unchanged.
CHAPTER_13_TARGET = {"SLOT_1": ["SPACER_BLUE"], "SLOT_2": ["SPACER_LONG"], "SLOT_3": ["BOLT"], "SLOT_4": []}

# The tray at the start of Chapter 13, before the order: the tray of an order that changes nothing.
CHAPTER_13_START = {"SLOT_1": ["SPACER_BLUE"], "SLOT_2": ["SPACER_SHORT"], "SLOT_3": ["BOLT"], "SLOT_4": []}


def planned_tray(steps, state, capability):
    """The tray after the steps of a plan, replayed on a copy of the cell up to the first step that fails."""
    cell = SimulatedCell(capability, state)
    for step in steps:
        try:
            result = getattr(functions, step["function"])(cell, **step["args"])
        except (AttributeError, KeyError, TypeError):
            break
        if result.status != "success" and step["function"] != "locate":
            break
    return cell.state()["slots"]


def add_target(raw, state, capability):
    """Return the raw answer with the target its plan builds, unless it is no plan or already has a target."""
    try:
        answer = json.loads(raw)
    except (TypeError, ValueError):
        return raw
    if not isinstance(answer, dict) or not isinstance(answer.get("plan"), list) or "target" in answer:
        return raw
    answer["target"] = planned_tray(answer["plan"], state, capability)
    return json.dumps(answer)
