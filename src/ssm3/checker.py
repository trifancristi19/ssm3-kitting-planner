"""Checker, Task B (Design Document, Chapter 8).

The checker replays every plan step by step on a copy of the cell state before
anything moves, and returns run, reject with a code and reason, or ask (DD3). It
reads the same capability file as the planner (DD5). The baseline's plans pass the
same checks (DD4).

This module checks the format, the functions, the arguments, the preconditions,
the protected slots, the return_capacity limit, the rule override and the ambiguity
of Table 9, and the final tray against the target (OD14). A known position of
the wrong kind, such as a pick from the return position, gets BAD_POSITION, which
the team agreed as a proposal for the Arguments row. The preconditions
come from the function library itself (the *_problem functions), so the checker
and the functions can never disagree. Several valid orders of placement are all
accepted: a part on top before its base gets NO_BASE, and a pick of a covered base
gets PART_COVERED (DD19). The codes are a proposal (Chapter 8).

Next to the plan, the checker gets the order text and a target tray (OD13,
proposal). The target is the full tray the order asks for: from the structured order,
or for a plain-language order the tray the planner says it intends. The checker
never gets the expected tray of the task set. With them it runs three more checks:

- AMBIGUOUS (DD7). Fixed code matches the part words in the order text against the
  parts in the cell. When one description, such as "the red brick", fits more than
  one kind of part, the check returns ask. A slot named right after the part, as in
  "the red brick in slot 1", settles it when that slot holds exactly one of them.
  The operator's answer is added to the order text as a line "Operator answer: ...",
  and the check passes when the answer narrows the description to one part.
- RULE_OVERRIDE. When the target itself breaks a rule of the cell (more parts in a
  slot than it has levels, an unknown part, or a change to a protected slot), the
  order asked for something the rules forbid. The plan is rejected, and the
  orchestrator tells the operator. A plan that breaks a rule while its target does
  not keeps its usual code.
- TARGET_MISMATCH (OD14). After the replay, the final tray must equal the target.
  The reason names the slots that differ. An empty plan therefore passes only when
  the tray already matches the target.

The part words come from the part ID: BRICK_2X4_RED is a "brick" that is "2x4" and
"red", and SPACER_SHORT a "spacer" that is "short" (proposal). The first word is the
kind of part, the others describe it. A capability file can give other words under
"part_words", for example {"BOLT": ["bolt", "steel"]}. The order of the checks is
Format, Ambiguity, Rule override, the steps of Table 9 and then the final tray
(proposal): what the order means comes before whether the plan fits it.
"""

import re

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


# Ambiguity (OD13, DD7)

ANSWER_PREFIX = "Operator answer:"

# Words that may stand before a part description without describing it, as in "put the red brick" (proposal).
# Any other word right before the description, such as "green" in "the green brick", is taken as a describing
# word that no part has.
FILLER_WORDS = {
    "a", "an", "the", "one", "any", "that", "this", "each", "every", "other", "another", "same", "its", "their",
    "put", "place", "move", "take", "pick", "get", "fetch", "bring", "replace", "swap", "remove", "add", "stack",
    "use", "with", "and", "or", "then", "on", "onto", "in", "into", "from", "to", "for", "by", "of", "at", "top",
}


def _normalise(text):
    """Lower case, "2 x 4" and "2×4" written as "2x4", so the words of the order match the part words."""
    text = text.lower().replace("\u00d7", "x")
    return re.sub(r"(\d)\s*x\s*(\d)", r"\1x\2", text)


def _words(text):
    return re.findall(r"[a-z0-9]+", _normalise(text))


def part_words(capability, part):
    """The words of a part: (kind, set of describing words). From "part_words" in the capability file, else the ID."""
    words = capability.get("part_words", {}).get(part) or _words(part.replace("_", " "))
    return words[0], set(words[1:])


def _parts_in_cell(state):
    found = set()
    for group in ("bins", "slots"):
        for parts in state[group].values():
            found.update(parts)
    found.update(state["return"])
    if state["gripper"] is not None:
        found.add(state["gripper"])
    return found


def _named_slot(words, start, capability):
    """The slot named within a few words after a part, as in "in slot 2" or "from SLOT_2", else None."""
    slots = {name.lower(): name for name in capability["positions"]["slots"]}
    window = words[start:start + 5]
    for index, word in enumerate(window):
        if word == "slot" and index + 1 < len(window) and f"slot_{window[index + 1]}" in slots:
            return slots[f"slot_{window[index + 1]}"]
        if word in ("slot1", "slot2", "slot3", "slot4") and f"slot_{word[4:]}" in slots:
            return slots[f"slot_{word[4:]}"]
    return None


def _answer_settles(candidates, answers, capability):
    """True when one operator answer narrows the candidates to exactly one part."""
    describing = _describing_words(capability)
    for answer in answers:
        named = [part for part in candidates if part.lower() in _normalise(answer)]
        if len(named) == 1:
            return True
        said = set(_words(answer)) & describing
        fitting = [part for part in candidates if said and said <= part_words(capability, part)[1]]
        if len(fitting) == 1:
            return True
    return False


def _describing_words(capability):
    words = set()
    for part in capability["parts"]:
        words |= part_words(capability, part)[1]
    return words


def ambiguity(order_text, state, capability):
    """Return the reason when a part description in the order fits more than one part in the cell, else None.

    order_text may end with lines "Operator answer: ..." that the orchestrator added (OD13).
    """
    lines = order_text.split("\n")
    order = " ".join(line for line in lines if not line.startswith(ANSWER_PREFIX))
    answers = [line[len(ANSWER_PREFIX):] for line in lines if line.startswith(ANSWER_PREFIX)]
    present = _parts_in_cell(state)
    kinds = {part_words(capability, part)[0] for part in capability["parts"]}
    describing = _describing_words(capability)
    # A part named by its ID, such as BRICK_2X2_RED, names exactly one part, so it is taken out first.
    order = _normalise(order)
    for part in capability["parts"]:
        order = order.replace(part.lower(), " ")
    words = _words(order)
    for index, word in enumerate(words):
        if word not in kinds:
            continue
        said = []
        back = index - 1
        while back >= 0 and words[back] in describing and len(said) < 3:
            said.insert(0, words[back])
            back -= 1
        # A describing word no part has, as in "the green brick", fits no part: the planner or the
        # checker deals with that as an unknown part, not as an ambiguity (proposal).
        if back >= 0 and words[back] not in FILLER_WORDS:
            continue
        candidates = sorted(part for part in present & set(capability["parts"])
                            if part_words(capability, part)[0] == word and set(said) <= part_words(capability, part)[1])
        if len(candidates) < 2:
            continue
        slot = _named_slot(words, index + 1, capability)
        if slot is not None and len([part for part in candidates if part in state["slots"][slot]]) == 1:
            continue
        if _answer_settles(candidates, answers, capability):
            continue
        phrase = " ".join([*said, word])
        return f'"{phrase}" fits more than one part in the cell: {", ".join(candidates)}. Which one is meant?'
    return None


# Target tray (OD13, OD14)

def _tray_shape_problem(target, capability):
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


def _mismatch(final, target):
    differ = [slot for slot in target if final[slot] != target[slot]]
    if not differ:
        return None
    return "After the plan " + ", ".join(
        f"{slot} holds {final[slot] or 'nothing'} but the target is {target[slot] or 'empty'}" for slot in differ)


def check(plan, state, capability, protected=(), order_text=None, target=None):
    """Check a plan against the capability file and the latest cell state.

    plan is the list under "plan" in the planner response (Chapter 6). protected
    lists the slots the order keeps unchanged. order_text is the order as the
    operator gave it, with any operator answers added, and target the full tray the
    order asks for (OD13). Without them the AMBIGUOUS, RULE_OVERRIDE and
    TARGET_MISMATCH checks are skipped, as for a test of the steps alone. Returns
    the check result of Table 7 as a dict with verdict, step (counted from 1), code
    and reason. The state that is passed in never changes.
    """
    if not isinstance(plan, list):
        return _verdict("reject", None, "FORMAT", "The plan is not a list of steps")
    if target is not None:
        shape = _tray_shape_problem(target, capability)
        if shape:
            return _verdict("reject", None, "FORMAT", shape)
    if order_text:
        unclear = ambiguity(order_text, state, capability)
        if unclear:
            return _verdict("ask", None, "AMBIGUOUS", unclear)
    if target is not None:
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
        wrong = _mismatch(cell.state()["slots"], target)
        if wrong:
            return _verdict("reject", None, "TARGET_MISMATCH", wrong)
        return _verdict("run", reason=f"All {len(plan)} steps can run and the tray ends at the target")
    return _verdict("run", reason=f"All {len(plan)} steps can run")
