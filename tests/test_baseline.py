"""Tests for the layout comparison baseline (Design Document, Chapter 11)."""

import pytest

from ssm3 import baseline
from ssm3.baseline import plan_from_layout
from ssm3.cell import SimulatedCell
from ssm3.checker import check
from ssm3.functions import move_to, pick, place

CHAPTER_13_ORDER = {
    "order_id": "K-17",
    "target": {"SLOT_1": ["SPACER_BLUE"], "SLOT_2": ["SPACER_LONG"], "SLOT_3": ["BOLT"]},
    "protected": ["SLOT_1", "SLOT_3"],
}


def run(cell, plan):
    names = {"move_to": move_to, "pick": pick, "place": place}
    return [names[s["function"]](cell, **s["args"]).status for s in plan]


def test_chapter_13_order_gives_exactly_the_chapter_6_plan(cell, chapter6_plan):
    # The baseline and the document describe the same plan, so neither can drift from the other.
    assert plan_from_layout(CHAPTER_13_ORDER, cell.state(), cell.capability) == {"plan": chapter6_plan}


def test_nothing_to_change_gives_an_empty_plan(cell):
    order = {"order_id": "K-18", "target": {"SLOT_2": ["SPACER_SHORT"]}, "protected": []}
    assert plan_from_layout(order, cell.state(), cell.capability) == {"plan": []}


def test_full_kit_change_of_two_slots_runs(cell):
    # Mihail Josan found that this was blocked at the second return with one part per position (DD20).
    cell_state = cell.state()
    cell_state["bins"]["BIN_2"] = ["SPACER_SHORT"]
    order = {"order_id": "K-19", "target": {"SLOT_2": ["SPACER_LONG"], "SLOT_3": ["SPACER_SHORT"]},
             "protected": ["SLOT_1"]}
    plan = plan_from_layout(order, cell_state, cell.capability)["plan"]
    assert check(plan, cell_state, cell.capability, protected=order["protected"])["verdict"] == "run"
    changed = SimulatedCell(cell.capability, cell_state)
    assert set(run(changed, plan)) == {"success"}
    final = changed.state()
    assert final["slots"]["SLOT_2"] == ["SPACER_LONG"]
    assert final["slots"]["SLOT_3"] == ["SPACER_SHORT"]
    assert final["return"] == ["SPACER_SHORT", "BOLT"]
    assert final["slots"]["SLOT_1"] == ["SPACER_BLUE"]


def test_full_kit_change_of_two_slots_hits_limit_with_the_old_capacity(cell):
    cell.capability["limits"]["return_capacity"] = 1
    cell_state = cell.state()
    cell_state["bins"]["BIN_2"] = ["SPACER_SHORT"]
    order = {"order_id": "K-19", "target": {"SLOT_2": ["SPACER_LONG"], "SLOT_3": ["SPACER_SHORT"]}}
    plan = plan_from_layout(order, cell_state, cell.capability)["plan"]
    assert check(plan, cell_state, cell.capability)["code"] == "LIMIT"


def test_top_removed_before_base_and_base_placed_before_top(cell):
    state = cell.state()
    state["slots"]["SLOT_2"] = ["SPACER_SHORT", "BOLT"]
    state["bins"]["BIN_1"] = ["BOLT"]
    order = {"order_id": "K-20", "target": {"SLOT_2": ["SPACER_LONG", "BOLT"]}, "protected": ["SLOT_1", "SLOT_3"]}
    plan = plan_from_layout(order, state, cell.capability)["plan"]
    picks = [(s["args"]["part"], s["args"]["source"]) for s in plan if s["function"] == "pick"]
    places = [(s["args"]["part"], s["args"].get("level")) for s in plan if s["function"] == "place"]
    assert picks == [("BOLT", "SLOT_2"), ("SPACER_SHORT", "SLOT_2"), ("SPACER_LONG", "BIN_3"), ("BOLT", "BIN_1")]
    assert places == [("BOLT", None), ("SPACER_SHORT", None), ("SPACER_LONG", "base"), ("BOLT", "top")]
    assert check(plan, state, cell.capability, protected=order["protected"])["verdict"] == "run"


def test_only_the_top_changes(cell):
    state = cell.state()
    state["slots"]["SLOT_2"] = ["SPACER_SHORT", "BOLT"]
    order = {"order_id": "K-21", "target": {"SLOT_2": ["SPACER_SHORT", "SPACER_LONG"]}}
    plan = plan_from_layout(order, state, cell.capability)["plan"]
    picks = [s["args"]["part"] for s in plan if s["function"] == "pick"]
    assert picks == ["BOLT", "SPACER_LONG"]
    assert check(plan, state, cell.capability)["verdict"] == "run"


def test_protected_and_unnamed_slots_are_left_alone(cell):
    order = {"order_id": "K-22", "target": {"SLOT_1": ["BOLT"]}, "protected": ["SLOT_1"]}
    assert plan_from_layout(order, cell.state(), cell.capability) == {"plan": []}


def test_more_parts_than_levels_is_an_error(cell):
    order = {"order_id": "K-23", "target": {"SLOT_4": ["BOLT", "BOLT", "BOLT"]}}
    with pytest.raises(ValueError):
        plan_from_layout(order, cell.state(), cell.capability)


def test_recipe_table_is_still_a_stub():
    with pytest.raises(NotImplementedError):
        baseline.plan_from_recipe("KIT_A")


def test_a_slot_the_capability_file_does_not_know_is_an_error(cell):
    # A typo such as SLOT_9 used to give an empty plan (review of pull request 5).
    order = {"order_id": "K-24", "target": {"SLOT_9": ["BOLT"]}}
    with pytest.raises(ValueError, match="SLOT_9"):
        plan_from_layout(order, cell.state(), cell.capability)


def test_a_part_the_capability_file_does_not_know_is_an_error(cell):
    order = {"order_id": "K-25", "target": {"SLOT_4": ["SPACER_GOLD"]}}
    with pytest.raises(ValueError, match="SPACER_GOLD"):
        plan_from_layout(order, cell.state(), cell.capability)
