"""Non-LLM baseline, Task C (Design Document, Chapter 11).

The baseline turns the same orders into the same kind of plan without a language
model, so the comparison isolates the planning step. It makes no model calls,
and its plans pass the same checker (DD4). Chapter 11 gives two forms, a recipe
table and a layout comparison script (proposal).

The layout comparison works. The fields of the work order file are still open
(OD7), so the structured order it reads is a proposal: an order ID, the target
parts of each slot from the base up (the same lists as the cell state) and the
protected slots. The recipe table waits for the list of kits (OD11).
"""

from ssm3.cell import LEVELS


def plan_from_recipe(kit_id):
    """Look up the fixed layout of a kit and return a plan."""
    raise NotImplementedError("Recipe table, see Design Document Chapter 11")


def _step(function, **args):
    return {"function": function, "args": args}


def plan_from_layout(order, state, capability):
    """Compare a new part-to-slot mapping with the tray and return a plan.

    order is {"order_id": ..., "target": {slot: [base part, top part]}, "protected": [slots]}
    (proposal, OD7). A slot the target does not name stays as it is. For every
    changed slot that is not protected, the old parts go to the return position
    and the new parts come from their bins (Chapter 11). A top part is removed
    before its base, and a base is placed before its top (DD19). When only the
    base changes, the top part still comes off first and a new one comes from its
    bin. Returns the planner response format of Chapter 6, {"plan": [...]}.
    """
    positions = capability["positions"]
    levels_per_slot = capability["limits"]["levels_per_slot"]
    protected = set(order.get("protected", ()))
    plan = []
    for slot in positions["slots"]:
        if slot not in order["target"] or slot in protected:
            continue
        current = list(state["slots"][slot])
        target = list(order["target"][slot])
        if len(target) > levels_per_slot:
            raise ValueError(f"{slot} has {levels_per_slot} levels, the target names {len(target)} parts")
        keep = 0
        while keep < min(len(current), len(target)) and current[keep] == target[keep]:
            keep += 1
        for part in reversed(current[keep:]):
            plan += [
                _step("move_to", position=slot),
                _step("pick", part=part, source=slot),
                _step("move_to", position=positions["return"]),
                _step("place", part=part, slot=positions["return"]),
            ]
        for index, part in enumerate(target[keep:], start=keep):
            source = capability["parts"][part]
            plan += [
                _step("move_to", position=source),
                _step("pick", part=part, source=source),
                _step("move_to", position=slot),
                _step("place", part=part, slot=slot, level=LEVELS[index]),
            ]
    if plan:
        plan.append(_step("move_to", position=positions["home"]))
    return {"plan": plan}
