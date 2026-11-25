"""Tests for the recipe table of the baseline and the kit tasks (Design Document, Chapter 11, DD23 and DD24)."""

import itertools
import json
from collections import Counter
from pathlib import Path

import pytest

from ssm3.baseline import load_recipes, plan_from_order, plan_from_recipe, recipe, target_problem
from ssm3.capability import load_capability
from ssm3.cell import SimulatedCell
from ssm3.checker import check
from ssm3.functions import move_to, pick, place
from ssm3.kit_tasks import load_kit_tasks, load_starts, start_state

ROOT = Path(__file__).resolve().parent.parent
KITS = ("KIT_A", "KIT_B", "KIT_C")

# The fields of one task of the task set (DD23): the work order file and the expected result.
TASK_FIELDS = {"order_id", "kit_id", "text", "target", "protected", "expected_outcome", "expected_tray"}


@pytest.fixture
def capability():
    return load_capability(ROOT / "config" / "capability_kitting.json")


@pytest.fixture
def recipes(capability):
    return load_recipes(capability=capability)


def stocked(capability, kit_id=None, recipes=None):
    """Every bin holds two bricks of its own type, and the tray holds kit_id or nothing."""
    starts = {"stock_per_bin": 2, "start_kit": {"X": kit_id or ""}}
    return start_state("X", capability, starts, recipes)


def run(cell, plan):
    names = {"move_to": move_to, "pick": pick, "place": place}
    return [names[s["function"]](cell, **s["args"]).status for s in plan]


# ---------------------------------------------------------------- the recipe table

def test_the_recipe_table_has_the_three_kits_of_dd24(recipes):
    assert sorted(recipes) == list(KITS)


def test_every_recipe_is_a_full_tray_of_the_kitting_cell(recipes, capability):
    for kit_id, target in recipes.items():
        assert target_problem(target, capability) is None, kit_id


def test_no_kit_puts_a_2x4_on_top_of_a_2x2(recipes):
    # A choice for the three kits, not a rule of the cell, so the checker does not test it.
    for kit_id, target in recipes.items():
        for parts in target.values():
            if len(parts) == 2:
                assert not ("_2X2_" in parts[0] and "_2X4_" in parts[1]), kit_id


def test_kit_c_has_near_identical_bricks_side_by_side(recipes):
    # The same colour in both sizes, so an order that names only the colour is ambiguous (DD25).
    bricks = [part for parts in recipes["KIT_C"].values() for part in parts]
    for colour in ("RED", "YELLOW"):
        assert {f"BRICK_2X2_{colour}", f"BRICK_2X4_{colour}"} <= set(bricks)


def test_a_recipe_that_does_not_fit_the_cell_is_an_error(tmp_path, capability):
    bad = {"KIT_X": {"SLOT_1": ["BRICK_2X2_GREEN"], "SLOT_2": [], "SLOT_3": [], "SLOT_4": []}}
    path = tmp_path / "recipes.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="KIT_X.*BRICK_2X2_GREEN"):
        load_recipes(path, capability)


def test_a_recipe_that_misses_a_slot_is_an_error(tmp_path, capability):
    path = tmp_path / "recipes.json"
    path.write_text(json.dumps({"KIT_X": {"SLOT_1": []}}), encoding="utf-8")
    with pytest.raises(ValueError, match="KIT_X.*SLOT_2"):
        load_recipes(path, capability)


def test_an_unknown_kit_is_an_error(recipes):
    with pytest.raises(ValueError, match="KIT_Z"):
        recipe("KIT_Z", recipes)


def test_recipe_returns_a_copy(recipes):
    layout = recipe("KIT_A", recipes)
    layout["SLOT_1"].append("BRICK_2X2_RED")
    assert recipes["KIT_A"]["SLOT_1"] == ["BRICK_2X4_RED"]


# ---------------------------------------------------------------- plan_from_recipe

@pytest.mark.parametrize("kit_id", KITS)
def test_every_kit_is_built_on_an_empty_tray(kit_id, capability, recipes):
    state = stocked(capability, recipes=recipes)
    plan = plan_from_recipe(kit_id, state, capability, recipes=recipes)["plan"]
    target = recipes[kit_id]
    # The baseline's plans pass the same checker as the planner's (DD4), with the kit as target (DD26).
    assert check(plan, state, capability, target=target)["verdict"] == "run"
    cell = SimulatedCell(capability, state)
    assert set(run(cell, plan)) == {"success"}
    assert cell.state()["slots"] == target
    assert cell.state()["return"] == []


@pytest.mark.parametrize("old, new", list(itertools.permutations(KITS, 2)))
def test_every_kit_is_changed_into_every_other_kit(old, new, capability, recipes):
    state = stocked(capability, old, recipes)
    plan = plan_from_recipe(new, state, capability, recipes=recipes)["plan"]
    assert check(plan, state, capability, target=recipes[new])["verdict"] == "run"
    cell = SimulatedCell(capability, state)
    assert set(run(cell, plan)) == {"success"}
    assert cell.state()["slots"] == recipes[new]
    # Nothing is lost: the bricks on the tray and in the return position are the old tray plus the bricks fetched.
    removed = Counter(part for parts in recipes[old].values() for part in parts) - Counter(
        part for parts in recipes[new].values() for part in parts)
    assert Counter(cell.state()["return"]) >= removed


def test_a_kit_already_on_the_tray_gives_an_empty_plan(capability, recipes):
    state = stocked(capability, "KIT_B", recipes)
    assert plan_from_recipe("KIT_B", state, capability, recipes=recipes) == {"plan": []}


def test_a_kit_that_needs_a_protected_slot_is_rejected_by_the_checker(capability, recipes):
    # The baseline never touches a protected slot, so the plan cannot reach the kit, and the
    # target itself changes a protected slot, which no order may do (RULE_OVERRIDE, DD25).
    state = stocked(capability, "KIT_A", recipes)
    plan = plan_from_recipe("KIT_C", state, capability, protected=("SLOT_1",), recipes=recipes)["plan"]
    assert all(step["args"].get("slot") != "SLOT_1" and step["args"].get("source") != "SLOT_1" for step in plan)
    result = check(plan, state, capability, protected=("SLOT_1",), target=recipes["KIT_C"])
    assert (result["verdict"], result["code"]) == ("reject", "RULE_OVERRIDE")


def test_the_plan_uses_the_order_id_only_for_the_order(capability, recipes):
    state = stocked(capability, recipes=recipes)
    first = plan_from_recipe("KIT_A", state, capability, recipes=recipes, order_id="K-99")
    assert first == plan_from_recipe("KIT_A", state, capability, recipes=recipes)


# ---------------------------------------------------------------- plan_from_order (DD23)

def test_an_order_with_only_a_kit_id_plans_the_recipe(capability, recipes):
    state = stocked(capability, recipes=recipes)
    order = {"order_id": "K-1", "kit_id": "KIT_C", "target": {}, "protected": []}
    assert plan_from_order(order, state, capability, recipes) == plan_from_recipe("KIT_C", state, capability,
                                                                                  recipes=recipes)


def test_an_order_with_a_kit_id_and_the_same_target_is_planned(capability, recipes):
    state = stocked(capability, recipes=recipes)
    order = {"order_id": "K-2", "kit_id": "KIT_A", "target": recipe("KIT_A", recipes), "protected": []}
    assert plan_from_order(order, state, capability, recipes)["plan"]


def test_an_order_whose_target_is_not_its_kit_is_an_error(capability, recipes):
    state = stocked(capability, recipes=recipes)
    order = {"order_id": "K-3", "kit_id": "KIT_A", "target": recipe("KIT_C", recipes), "protected": []}
    with pytest.raises(ValueError, match="K-3.*KIT_A"):
        plan_from_order(order, state, capability, recipes)


def test_an_order_without_a_kit_id_plans_its_target(capability, recipes):
    state = stocked(capability, recipes=recipes)
    target = {"SLOT_1": ["BRICK_2X2_BLUE"], "SLOT_2": [], "SLOT_3": [], "SLOT_4": []}
    order = {"order_id": "K-4", "kit_id": "", "target": target, "protected": []}
    cell = SimulatedCell(capability, state)
    run(cell, plan_from_order(order, state, capability, recipes)["plan"])
    assert cell.state()["slots"] == target


def test_an_order_with_neither_kit_id_nor_target_is_an_error(capability, recipes):
    state = stocked(capability, recipes=recipes)
    with pytest.raises(ValueError, match="kit_id or a target"):
        plan_from_order({"order_id": "K-5", "kit_id": "", "target": {}, "protected": []}, state, capability, recipes)


# ---------------------------------------------------------------- the kit tasks

def test_the_kit_tasks_have_the_fields_of_dd23():
    for order_id, task in load_kit_tasks().items():
        assert set(task) == TASK_FIELDS, order_id
        assert task["order_id"] == order_id
        assert task["expected_outcome"] == "done"
        assert task["text"].strip()


def test_there_is_a_build_task_for_every_kit_and_a_change_task_for_every_pair(recipes):
    tasks = load_kit_tasks()
    builds = {task["kit_id"] for order_id, task in tasks.items() if order_id.count("-") == 1}
    changes = [order_id for order_id in tasks if order_id.count("-") == 2]
    assert builds == set(KITS)
    assert len(changes) == len(KITS) * (len(KITS) - 1)


def test_the_target_and_the_expected_tray_of_every_task_are_its_kit(recipes):
    # DD23: the kit_id and the target of an order must agree, and a done task ends at its target.
    for order_id, task in load_kit_tasks().items():
        assert task["target"] == recipes[task["kit_id"]], order_id
        assert task["expected_tray"]["slots"] == task["target"], order_id


def test_every_task_has_a_start_tray():
    starts = load_starts()
    assert set(starts["start_kit"]) == set(load_kit_tasks())
    for order_id, kit_id in starts["start_kit"].items():
        assert kit_id in ("", *KITS), order_id


def test_the_text_names_every_brick_of_the_kit(recipes):
    # The planner gets only the text, so it must describe the same tray as the kit ID.
    words = {"2X2": "small", "2X4": "large"}
    for order_id, task in load_kit_tasks().items():
        for slot, parts in recipes[task["kit_id"]].items():
            for part in parts:
                _, size, colour = part.split("_")
                assert f"{words[size]} {colour.lower()} brick" in task["text"], (order_id, slot, part)


def test_the_baseline_solves_every_kit_task_from_its_start_tray(capability, recipes):
    for order_id, task in load_kit_tasks().items():
        state = start_state(order_id, capability, recipes=recipes)
        plan = plan_from_order(task, state, capability, recipes)["plan"]
        assert check(plan, state, capability, protected=task["protected"], target=task["target"])["verdict"] == "run"
        cell = SimulatedCell(capability, state)
        assert set(run(cell, plan)) == {"success"}, order_id
        assert cell.state()["slots"] == task["expected_tray"]["slots"], order_id


def test_a_change_task_starts_from_the_old_kit(capability, recipes):
    state = start_state("K-A-B", capability, recipes=recipes)
    assert state["slots"] == recipes["KIT_A"]
    assert all(len(parts) == 2 for parts in state["bins"].values())


def test_an_order_without_a_start_tray_is_an_error(capability, recipes):
    with pytest.raises(ValueError, match="K-Z"):
        start_state("K-Z", capability, recipes=recipes)
