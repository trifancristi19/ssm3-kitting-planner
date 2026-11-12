"""Checker, Task B (Design Document, Chapter 8).

The checker replays every plan step by step on a copy of the cell state before
anything moves, and returns run, reject with a code and reason, or ask (DD3). It
reads the same capability file as the planner (DD5). The baseline's plans pass the
same checks (DD4).

This module checks the format, the functions, the arguments, the preconditions,
the protected slots and the return_capacity limit of Table 9. A known position of
the wrong kind, such as a pick from the return position, gets BAD_POSITION, which
the team agreed as a proposal for the Arguments row. The preconditions
come from the function library itself (the *_problem functions), so the checker
and the functions can never disagree. Several valid orders of placement are all
accepted: a part on top before its base gets NO_BASE, and a pick of a covered base
gets PART_COVERED (DD19). The codes are a proposal (Chapter 8).

Not built yet: the ambiguity check (AMBIGUOUS) and the rule override check
(RULE_OVERRIDE), which need the order text (DD7). The number of rejected plans
before the operator is asked belongs to the orchestrator (DD13).
"""

from ssm3 import functions
from ssm3.cell import SimulatedCell

# The four functions a plan may use, with their arguments (DD11). ask_operator is never part of a plan.
PLAN_FUNCTIONS = {
    "move_to": ({"position"}, set()),
    "pick": ({"part", "source"}, set()),
    "place": ({"part", "slot"}, {"level"}),
    "locate": ({"part"}, set()),
}
POSITION_ARGS = ("position", "source", "slot")

VERDICTS = ("run", "reject", "ask")


def _verdict(verdict, step=None, code=None, reason=""):
    """The check result of Table 7: verdict, step number, code and reason."""
    return {"verdict": verdict, "step": step, "code": code, "reason": reason}


def _argument_problem(name, args, capability, cell):
    if not isinstance(args, dict):
        return "FORMAT", "args is not an object"
    required, optional = PLAN_FUNCTIONS[name]
    missing = required - set(args)
    unknown = set(args) - required - optional
    if missing or unknown:
        return "FORMAT", f"{name} takes {', '.join(sorted(required | optional))}"
    for key in POSITION_ARGS:
        if key in args and (not isinstance(args[key], str) or args[key] not in cell.positions()):
            return "UNKNOWN_POSITION", f"{args[key]} is not a named position"
    if "part" in args and (not isinstance(args["part"], str) or args["part"] not in capability["parts"]):
        return "UNKNOWN_PART", f"{args['part']} is not a known part"
    if name == "place":
        bad_level = functions.level_problem(cell, args["slot"], args.get("level"))
        if bad_level:
            return bad_level.code, bad_level.reason
    return None


def check(plan, state, capability, protected=()):
    """Check a plan against the capability file and the latest cell state.

    plan is the list under "plan" in the planner response (Chapter 6). protected
    lists the slots the order keeps unchanged. Returns the check result of Table 7
    as a dict with verdict, step (counted from 1), code and reason. The state that
    is passed in never changes.
    """
    if not isinstance(plan, list):
        return _verdict("reject", None, "FORMAT", "The plan is not a list of steps")
    cell = SimulatedCell(capability, state)
    for number, step in enumerate(plan, start=1):
        if not isinstance(step, dict) or set(step) != {"function", "args"}:
            return _verdict("reject", number, "FORMAT", "A step has exactly the fields function and args")
        name, args = step["function"], step["args"]
        if not isinstance(name, str) or name not in PLAN_FUNCTIONS:
            return _verdict("reject", number, "UNKNOWN_FUNCTION", f"{name} is not in the library")
        problem = _argument_problem(name, args, capability, cell)
        if problem:
            return _verdict("reject", number, *problem)
        touched = args.get("source") if name == "pick" else args.get("slot") if name == "place" else None
        if touched in protected:
            return _verdict("reject", number, "PROTECTED_SLOT", f"{touched} is protected by the order")
        precondition = getattr(functions, f"{name}_problem", None)
        found = precondition(cell, **args) if precondition else None
        if found:
            return _verdict("reject", number, found.code, found.reason)
        if name == "locate":
            continue  # locate only reads the state and has no preconditions (Table 6)
        result = getattr(functions, name)(cell, **args)
        if result.status != "success":
            raise RuntimeError(f"Step {number} passed its preconditions but returned {result.status}: {result.message}")
    return _verdict("run", reason=f"All {len(plan)} steps can run")
