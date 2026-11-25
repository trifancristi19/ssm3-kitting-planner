"""Kit tasks of the task set (Design Document, Chapter 10, DD23 and DD24).

config/task_set_kits.json holds nine orders for the three kits of the recipe table,
in the task format of DD23: the five fields of the work order file (order_id,
kit_id, text, target, protected) and the expected result (expected_outcome and
expected_tray). Three orders build a kit on an empty tray (K-A, K-B and K-C), and
six change one kit into another (K-A-B is kit A into kit B, and so on). The text
describes the whole kit in plain words, with small for a 2x2 brick and large for a
2x4 brick, so the LLM planner gets the same information as the baseline, which
gets the kit ID. Every order is clear, so every expected outcome is done.

The expected tray names the slots only, not the return position, because the
order in which the removed bricks reach the return position is not part of the
task.

A run also needs the tray it starts from, which the DD23 format has no field for.
config/task_starts_kits.json gives it per order: the kit already on the tray, or
an empty tray, with stock_per_bin bricks of its own type in every bin.
"""

import json
from pathlib import Path

from ssm3.baseline import load_recipes, recipe
from ssm3.cell import empty_state

ROOT = Path(__file__).resolve().parents[2]
TASK_FILE = ROOT / "config" / "task_set_kits.json"
START_FILE = ROOT / "config" / "task_starts_kits.json"


def load_kit_tasks(path=TASK_FILE):
    """Read the kit tasks, a dict from order ID to a task in the format of DD23."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_starts(path=START_FILE):
    """Read the start trays: {"stock_per_bin": n, "start_kit": {order_id: kit ID, or "" for an empty tray}}."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def start_state(order_id, capability, starts=None, recipes=None):
    """The cell state an order starts from: its start kit on the tray and every bin stocked.

    An order that is not in the start file raises ValueError.
    """
    starts = load_starts() if starts is None else starts
    recipes = load_recipes(capability=capability) if recipes is None else recipes
    if order_id not in starts["start_kit"]:
        raise ValueError(f"{order_id!r} has no start tray in the start file")
    state = empty_state(capability)
    for part, source in capability["parts"].items():
        state["bins"][source] = [part] * starts["stock_per_bin"]
    kit_id = starts["start_kit"][order_id]
    if kit_id:
        state["slots"] = recipe(kit_id, recipes)
    return state
