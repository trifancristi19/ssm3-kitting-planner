"""Non-LLM baseline, Task C (Design Document, Chapter 11).

The baseline turns the same orders into the same kind of plan without a language
model, so the comparison isolates the planning step. It makes no model calls,
and its plans pass the same checker (DD4). Chapter 11 gives two forms, a recipe
table and a layout comparison script (proposal).

Both forms work. The layout comparison reads the structured form of the work
order file of DD23 (agreed by the team on 22 November 2026): an order ID, the
full target tray with the parts of every slot from the base up (the same lists
as the cell state) and the protected slots.

The recipe table holds one fixed layout per kit, looked up by kit ID (Chapter 11).
config/recipe_table.json has the three kits of DD24: KIT_A with one brick per
slot, KIT_B with two stacked slots and KIT_C with near-identical bricks side by
side. No kit puts a 2x4 brick on top of a 2x2 brick. That is a choice for these
kits, not a rule of the cell, so the checker does not test it. A recipe is a full
target tray, so plan_from_recipe looks up the layout and plans it with the layout
comparison, from whatever the tray holds now. A kit is built on an empty tray and
changed into another kit with the same function.

plan_from_order takes a structured order of DD23. With a kit_id it plans that
kit's recipe, and a target in the same order must then be the same tray.
Without a kit_id it plans the target.
"""

import json
from pathlib import Path

from ssm3.cell import level_names
from ssm3.checker import tray_shape_problem

ROOT = Path(__file__).resolve().parents[2]
RECIPE_FILE = ROOT / "config" / "recipe_table.json"


def target_problem(target, capability):
    """The reason when target is not a full tray this cell can hold, else None.

    Every slot is named once, every part is known and no slot has more parts than levels.
    """
    shape = tray_shape_problem(target, capability)
    if shape:
        return shape
    levels = level_names(capability)
    for slot, parts in target.items():
        if len(parts) > len(levels):
            return f"{slot} has {len(levels)} levels, the tray names {len(parts)} parts"
        unknown = [part for part in parts if part not in capability["parts"]]
        if unknown:
            return f"{unknown[0]} in {slot} is not a part in the capability file"
    return None


def load_recipes(path=RECIPE_FILE, capability=None):
    """Read the recipe table, a dict from kit ID to its full target tray.

    With a capability every recipe must be a full tray of that cell (target_problem).
    A file that is not a JSON object of kits, or a recipe that does not fit, raises
    ValueError that names the kit.
    """
    try:
        recipes = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{path} is not valid JSON ({error.msg}, line {error.lineno})") from None
    if not isinstance(recipes, dict) or not recipes:
        raise ValueError(f"{path} must be a JSON object with one entry per kit")
    if capability is not None:
        for kit_id, target in recipes.items():
            problem = target_problem(target, capability)
            if problem:
                raise ValueError(f"Recipe {kit_id}: {problem}")
    return recipes


def recipe(kit_id, recipes=None):
    """Return a copy of the target tray of a kit. An unknown kit ID raises ValueError."""
    recipes = load_recipes() if recipes is None else recipes
    if kit_id not in recipes:
        raise ValueError(f"{kit_id!r} is not a kit in the recipe table, known kits: {', '.join(sorted(recipes))}")
    return {slot: list(parts) for slot, parts in recipes[kit_id].items()}


def plan_from_recipe(kit_id, state, capability, protected=(), recipes=None, order_id=None):
    """Look up the fixed layout of a kit and return a plan that turns the tray into it.

    The plan starts from the tray in state, so the same call builds a kit on an empty
    tray and changes one kit into another. A protected slot is never touched, so a kit
    that needs a protected slot to change gives a plan that does not reach the kit,
    and the checker rejects it (RULE_OVERRIDE). Returns {"plan": [...]} like the
    layout comparison.
    """
    order = {"order_id": order_id or kit_id, "target": recipe(kit_id, recipes), "protected": list(protected)}
    return plan_from_layout(order, state, capability)


def plan_from_order(order, state, capability, recipes=None):
    """Plan a structured order of DD23: its kit's recipe when it has a kit_id, else its target.

    A kit_id together with a target that is a different tray raises ValueError, and so
    does an order with neither (DD23).
    """
    kit_id = order.get("kit_id") or ""
    target = order.get("target") or {}
    if kit_id:
        layout = recipe(kit_id, recipes)
        if target and target != layout:
            wrong = [slot for slot in layout if target.get(slot) != layout[slot]]
            raise ValueError(f"Order {order.get('order_id')}: the target is not the recipe of {kit_id} "
                             f"in {', '.join(wrong) or 'its slots'}")
        target = layout
    elif not target:
        raise ValueError(f"Order {order.get('order_id')}: a structured order needs a kit_id or a target (DD23)")
    structured = {"order_id": order.get("order_id"), "target": target, "protected": list(order.get("protected", ()))}
    return plan_from_layout(structured, state, capability)


def _step(function, **args):
    return {"function": function, "args": args}


def plan_from_layout(order, state, capability):
    """Compare a new part-to-slot mapping with the tray and return a plan.

    order is {"order_id": ..., "target": {slot: [base part, top part]}, "protected": [slots]}
    (proposal, OD7). The target names every slot of the tray. For every
    changed slot that is not protected, the old parts go to the return position
    and the new parts come from their bins (Chapter 11). A top part is removed
    before its base, and a base is placed before its top (DD19). When only the
    base changes, the top part still comes off first and a new one comes from its
    bin, so every bin needs a spare part. Returns the planner response format of
    Chapter 6, {"plan": [...]}. A slot that is missing from the target, a slot or
    part the capability file does not know, or more parts than levels raises
    ValueError.
    """
    positions = capability["positions"]
    levels = level_names(capability)
    missing = [slot for slot in positions["slots"] if slot not in order["target"]]
    if missing:
        raise ValueError(f"The target tray does not name {', '.join(missing)}, it must name every slot")
    for slot, target in order["target"].items():
        if slot not in positions["slots"]:
            raise ValueError(f"{slot} is not a tray slot in the capability file")
        if len(target) > len(levels):
            raise ValueError(f"{slot} has {len(levels)} levels, the target names {len(target)} parts")
        for part in target:
            if part not in capability["parts"]:
                raise ValueError(f"{part} in the target of {slot} is not a part in the capability file")
    protected = set(order.get("protected", ()))
    plan = []
    for slot in positions["slots"]:
        if slot in protected:
            continue
        current = list(state["slots"][slot])
        target = list(order["target"][slot])
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
                _step("place", part=part, slot=slot, level=levels[index]),
            ]
    if plan:
        plan.append(_step("move_to", position=positions["home"]))
    return {"plan": plan}
