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

Next to the plan, the checker gets the target tray (DD25): the full tray
the order asks for, from the structured order or, for a plain-language order, the
tray the planner says it intends. The checker never gets the expected tray of the
task set. With the target it runs three more checks:

- TARGET_CHANGED. The target stays fixed during a run. Once a plan has run, every
  later plan must give the same target, until an operator's answer changes it. The
  orchestrator passes that fixed target.
- RULE_OVERRIDE. A target that itself breaks a rule of the cell (more parts in a
  slot than it has levels, an unknown part, or a change to a protected slot) means
  the order asked for something the rules forbid. The orchestrator tells the
  operator. A plan that breaks a rule while its target does not keeps its usual code.
- TARGET_MISMATCH (DD26). The plan is the full remaining plan: after the replay
  the gripper must be empty and the final tray must equal the target. The reason
  names what differs. An empty plan therefore passes only when the tray is complete.

The ambiguity check (AMBIGUOUS) runs once on the order text before planning, in
order_check.py, so the closed loop does not ask the same question again (DD25). The
number of rejected plans before the operator is asked belongs to the orchestrator
(DD13). The order of the checks is the format, the target, the steps of Table 9 and
then the end of the plan (proposal).
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


# Target tray (DD25, DD26)

def tray_shape_problem(target, capability):
    """The reason when target is not a full tray of this cell, else None (FORMAT)."""
    slots = capability["positions"]["slots"]
    if not (isinstance(target, dict) and all(isinstance(parts, list) for parts in target.values())
            and all(isinstance(part, str) for parts in target.values() for part in parts)):
        return "The target is not an object that maps tray slots to lists of part IDs"
    missing = [slot for slot in slots if slot not in target]
    unknown = [slot for slot in target if slot not in slots]
    if missing or unknown:
        return ("The target must name every tray slot exactly once"
                + (f", it misses {', '.join(missing)}" if missing else "")
                + (f", {', '.join(unknown)} is not a tray slot" if unknown else ""))
    return None


def _rule_override(target, state, capability, protected):
    """The reason when the target itself breaks a rule of the cell, else None (RULE_OVERRIDE)."""
    levels = capability["limits"]["levels_per_slot"]
    for slot, parts in target.items():
        if len(parts) > levels:
            return f"The target puts {len(parts)} parts in {slot}, which has {levels} levels"
        unknown = [part for part in parts if part not in capability["parts"]]
        if unknown:
            return f"The target names {', '.join(unknown)}, which is not a part of this cell"
        if slot in protected and parts != state["slots"][slot]:
            return f"The target changes {slot}, which the order protects"
    return None


def _end_problem(final, target):
    """The reason when the plan does not end at the target with an empty gripper, else None (TARGET_MISMATCH)."""
    problems = []
    if final["gripper"] is not None:
        problems.append(f"the gripper still holds {final['gripper']}")
    problems += [f"{slot} holds {final['slots'][slot] or 'nothing'} but the target is {target[slot] or 'empty'}"
                 for slot in target if final["slots"][slot] != target[slot]]
    return ("After the plan " + ", ".join(problems)) if problems else None


def check(plan, state, capability, protected=(), target=None, fixed_target=None):
    """Check a plan against the capability file and the latest cell state.

    plan is the list under "plan" in the planner response (Chapter 6). protected
    lists the slots the order keeps unchanged. target is the full tray the order asks
    for (DD25), and fixed_target the target this run already holds (TARGET_CHANGED).
    Without a target only the steps are checked, as for a test of the steps alone.
    Returns the check result of Table 7 as a dict with verdict, step (counted from 1),
    code and reason. The state that is passed in never changes.
    """
    if not isinstance(plan, list):
        return _verdict("reject", None, "FORMAT", "The plan is not a list of steps")
    if target is not None:
        shape = tray_shape_problem(target, capability)
        if shape:
            return _verdict("reject", None, "FORMAT", shape)
        if fixed_target is not None and target != fixed_target:
            changed = [slot for slot in fixed_target if target.get(slot) != fixed_target[slot]]
            return _verdict("reject", None, "TARGET_CHANGED",
                            f"The target of this order is fixed, but this plan changes it for {', '.join(changed)}")
        forbidden = _rule_override(target, state, capability, protected)
        if forbidden:
            return _verdict("reject", None, "RULE_OVERRIDE", forbidden)
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
    if target is not None:
        wrong = _end_problem(cell.state(), target)
        if wrong:
            return _verdict("reject", None, "TARGET_MISMATCH", wrong)
        return _verdict("run", reason=f"All {len(plan)} steps can run and the tray ends at the target")
    return _verdict("run", reason=f"All {len(plan)} steps can run")
