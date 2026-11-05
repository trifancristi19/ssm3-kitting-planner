"""Tests for the simulated cell and the four working library functions."""

import copy
import json
from pathlib import Path

import pytest

from ssm3 import functions
from ssm3.capability import load_capability
from ssm3.cell import SimulatedCell, empty_state
from ssm3.functions import STATUSES, StepResult, locate, move_to, pick, place

ROOT = Path(__file__).resolve().parent.parent

# The Chapter 6 plan, copied exactly.
PLAN_JSON = """
{"plan": [
  {"function": "move_to", "args": {"position": "SLOT_2"}},
  {"function": "pick", "args": {"part": "SPACER_SHORT", "source": "SLOT_2"}},
  {"function": "move_to", "args": {"position": "RETURN"}},
  {"function": "place", "args": {"part": "SPACER_SHORT", "slot": "RETURN"}},
  {"function": "move_to", "args": {"position": "BIN_3"}},
  {"function": "pick", "args": {"part": "SPACER_LONG", "source": "BIN_3"}},
  {"function": "move_to", "args": {"position": "SLOT_2"}},
  {"function": "place", "args": {"part": "SPACER_LONG", "slot": "SLOT_2"}},
  {"function": "move_to", "args": {"position": "HOME"}}
]}
"""


@pytest.fixture
def capability():
    # Chapter 13 has a blue spacer that the Chapter 6 example lacks, so it goes in a fourth bin here.
    # The part list is open (OD11), so config/ stays unchanged.
    data = copy.deepcopy(load_capability(ROOT / "config" / "capability_example.json"))
    data["positions"]["bins"].append("BIN_4")
    data["parts"]["SPACER_BLUE"] = "BIN_4"
    return data


@pytest.fixture
def cell(capability):
    """The Chapter 13 initial state."""
    state = empty_state(capability)
    state["slots"]["SLOT_1"] = ["SPACER_BLUE"]
    state["slots"]["SLOT_2"] = ["SPACER_SHORT"]
    state["slots"]["SLOT_3"] = ["BOLT"]
    state["bins"]["BIN_3"] = ["SPACER_LONG"]
    return SimulatedCell(capability, state)


# Cell

def test_empty_state_is_empty_and_json_friendly(capability):
    state = empty_state(capability)
    assert state["gripper"] is None
    assert state["arm"] == "HOME"
    assert state["return"] == []
    assert all(parts == [] for parts in state["bins"].values())
    assert set(state["slots"]) == {"SLOT_1", "SLOT_2", "SLOT_3", "SLOT_4"}
    assert json.loads(json.dumps(state)) == state


def test_state_returns_a_deep_copy(cell):
    copy_of_state = cell.state()
    copy_of_state["slots"]["SLOT_1"].append("BOLT")
    copy_of_state["arm"] = "BIN_1"
    assert cell.state()["slots"]["SLOT_1"] == ["SPACER_BLUE"]
    assert cell.state()["arm"] == "HOME"


def test_cell_copies_the_state_it_is_given(capability):
    state = empty_state(capability)
    cell = SimulatedCell(capability, state)
    state["return"].append("BOLT")
    assert cell.state()["return"] == []


def test_free_follows_the_capability_limit(capability):
    capability["limits"]["parts_per_slot"] = 2
    state = empty_state(capability)
    state["slots"]["SLOT_1"] = ["BOLT"]
    cell = SimulatedCell(capability, state)
    assert cell.is_free("SLOT_1")
    state["slots"]["SLOT_1"] = ["BOLT", "SPACER_LONG"]
    assert not SimulatedCell(capability, state).is_free("SLOT_1")


def test_unknown_failure_kind_raises(cell):
    with pytest.raises(ValueError):
        cell.inject_failure("explode")


def test_move_part_failure_moves_the_part(cell):
    cell.inject_failure("move_part", part="SPACER_LONG", source="BIN_3", destination="BIN_1")
    state = cell.state()
    assert state["bins"]["BIN_3"] == []
    assert state["bins"]["BIN_1"] == ["SPACER_LONG"]


def test_move_part_failure_rejects_bad_requests(cell):
    with pytest.raises(ValueError):
        cell.inject_failure("move_part", part="BOLT", source="BIN_3", destination="BIN_1")
    with pytest.raises(ValueError):
        cell.inject_failure("move_part", part="SPACER_LONG", source="BIN_3", destination="SLOT_1")


# move_to

def test_move_to_success(cell):
    result = move_to(cell, "BIN_2")
    assert result.status == "success"
    assert result.state["arm"] == "BIN_2"
    assert cell.state() == result.state


def test_move_to_unknown_position_is_blocked_and_keeps_state(cell):
    before = cell.state()
    result = move_to(cell, "MOON")
    assert result.status == "blocked"
    assert result.state == before
    assert cell.state() == before


# pick

def test_pick_success(cell):
    move_to(cell, "BIN_3")
    result = pick(cell, "SPACER_LONG", "BIN_3")
    assert result.status == "success"
    assert result.state["gripper"] == "SPACER_LONG"
    assert result.state["bins"]["BIN_3"] == []


def test_pick_from_a_slot(cell):
    move_to(cell, "SLOT_3")
    assert pick(cell, "BOLT", "SLOT_3").status == "success"
    assert cell.state()["slots"]["SLOT_3"] == []


def test_pick_blocked_when_gripper_is_full(cell):
    move_to(cell, "BIN_3")
    pick(cell, "SPACER_LONG", "BIN_3")
    move_to(cell, "SLOT_3")
    before = cell.state()
    result = pick(cell, "BOLT", "SLOT_3")
    assert result.status == "blocked"
    assert cell.state() == before


def test_pick_not_found_when_part_is_not_at_source(cell):
    move_to(cell, "BIN_1")
    before = cell.state()
    result = pick(cell, "BOLT", "BIN_1")
    assert result.status == "not found"
    assert result.state == before
    assert cell.state() == before


def test_pick_failed_when_failure_injected_then_works_again(cell):
    move_to(cell, "BIN_3")
    cell.inject_failure("pick_failure")
    before = cell.state()
    result = pick(cell, "SPACER_LONG", "BIN_3")
    assert result.status == "failed"
    assert cell.state() == before
    assert pick(cell, "SPACER_LONG", "BIN_3").status == "success"


def test_pick_blocked_for_unknown_source(cell):
    before = cell.state()
    result = pick(cell, "SPACER_LONG", "NOWHERE")
    assert result.status == "blocked"
    assert cell.state() == before


def test_pick_blocked_for_return_position_as_source(cell):
    move_to(cell, "RETURN")
    assert pick(cell, "BOLT", "RETURN").status == "blocked"


def test_pick_blocked_when_arm_is_not_at_source(cell):
    before = cell.state()
    result = pick(cell, "SPACER_LONG", "BIN_3")
    assert result.status == "blocked"
    assert cell.state() == before


# place

def _hold(cell, part, source):
    move_to(cell, source)
    assert pick(cell, part, source).status == "success"


def test_place_success_in_slot_and_in_return(cell):
    _hold(cell, "SPACER_LONG", "BIN_3")
    move_to(cell, "SLOT_4")
    result = place(cell, "SPACER_LONG", "SLOT_4")
    assert result.status == "success"
    assert result.state["slots"]["SLOT_4"] == ["SPACER_LONG"]
    assert result.state["gripper"] is None
    _hold(cell, "BOLT", "SLOT_3")
    move_to(cell, "RETURN")
    assert place(cell, "BOLT", "RETURN").state["return"] == ["BOLT"]


def test_place_blocked_when_slot_is_occupied(cell):
    _hold(cell, "SPACER_LONG", "BIN_3")
    move_to(cell, "SLOT_2")
    before = cell.state()
    result = place(cell, "SPACER_LONG", "SLOT_2")
    assert result.status == "blocked"
    assert cell.state() == before


def test_place_blocked_when_gripper_does_not_hold_the_part(cell):
    move_to(cell, "SLOT_4")
    assert place(cell, "SPACER_LONG", "SLOT_4").status == "blocked"
    _hold(cell, "SPACER_LONG", "BIN_3")
    move_to(cell, "SLOT_4")
    before = cell.state()
    assert place(cell, "BOLT", "SLOT_4").status == "blocked"
    assert cell.state() == before


def test_place_blocked_when_arm_is_not_at_slot(cell):
    _hold(cell, "SPACER_LONG", "BIN_3")
    before = cell.state()
    result = place(cell, "SPACER_LONG", "SLOT_4")
    assert result.status == "blocked"
    assert cell.state() == before


def test_place_blocked_when_target_is_not_a_slot_or_return(cell):
    _hold(cell, "SPACER_LONG", "BIN_3")
    before = cell.state()
    assert place(cell, "SPACER_LONG", "BIN_3").status == "blocked"
    assert place(cell, "SPACER_LONG", "NOWHERE").status == "blocked"
    assert cell.state() == before


# locate

def test_locate_success_lists_every_place(cell):
    result = locate(cell, "SPACER_LONG")
    assert result.status == "success"
    assert result.locations == ("BIN_3",)
    _hold(cell, "SPACER_LONG", "BIN_3")
    assert locate(cell, "SPACER_LONG").locations == ("GRIPPER",)
    assert locate(cell, "BOLT").locations == ("SLOT_3",)


def test_locate_finds_a_part_in_several_places_and_in_return(cell):
    cell.inject_failure("move_part", part="SPACER_SHORT", source="SLOT_2", destination="RETURN")
    assert locate(cell, "SPACER_SHORT").locations == ("RETURN",)
    state = cell.state()
    state["bins"]["BIN_2"] = ["SPACER_SHORT"]
    twice = SimulatedCell(cell.capability, state)
    assert locate(twice, "SPACER_SHORT").locations == ("BIN_2", "RETURN")


def test_locate_not_found_and_does_not_change_state(cell):
    before = cell.state()
    result = locate(cell, "GHOST")
    assert result.status == "not found"
    assert result.locations == ()
    assert cell.state() == before


# Step results and stubs

def test_step_result_is_frozen_and_uses_known_statuses(cell):
    result = move_to(cell, "BIN_1")
    assert isinstance(result, StepResult)
    assert result.status in STATUSES
    with pytest.raises(AttributeError):
        result.status = "failed"


def test_result_state_is_a_copy(cell):
    result = move_to(cell, "BIN_1")
    result.state["arm"] = "HOME"
    assert cell.state()["arm"] == "BIN_1"


def test_ask_operator_is_still_a_stub():
    with pytest.raises(NotImplementedError):
        functions.ask_operator("Which slot?")


# Chapter 13 worked example

def run_plan(cell, plan):
    """Send each step to the function of that name. Stop at the first step that is not a success."""
    results = []
    for step in plan:
        result = getattr(functions, step["function"])(cell, **step["args"])
        results.append(result)
        if result.status != "success":
            break
    return results


def test_chapter_13_integration(cell):
    plan = json.loads(PLAN_JSON)["plan"]
    results = run_plan(cell, plan)
    assert len(results) == len(plan)
    assert all(result.status == "success" for result in results)
    state = cell.state()
    assert state["slots"]["SLOT_2"] == ["SPACER_LONG"]
    assert state["return"] == ["SPACER_SHORT"]
    assert state["slots"]["SLOT_1"] == ["SPACER_BLUE"]
    assert state["slots"]["SLOT_3"] == ["BOLT"]
    assert state["gripper"] is None
    assert state["arm"] == "HOME"


def test_variation_long_spacer_missing(cell):
    state = cell.state()
    state["bins"]["BIN_3"] = []
    missing = SimulatedCell(cell.capability, state)
    move_to(missing, "BIN_3")
    assert pick(missing, "SPACER_LONG", "BIN_3").status == "not found"


def test_variation_return_position_occupied(cell):
    # A part left in the return position before the order. Slots 1 and 3 stay untouched, as in Chapter 13.
    state = cell.state()
    state["return"] = ["BOLT"]
    occupied = SimulatedCell(cell.capability, state)
    plan = json.loads(PLAN_JSON)["plan"]
    results = run_plan(occupied, plan)
    assert results[-1].status == "blocked"
    assert len(results) == 4
    assert occupied.state()["slots"]["SLOT_1"] == ["SPACER_BLUE"]
    assert occupied.state()["slots"]["SLOT_3"] == ["BOLT"]


def test_variation_part_moved_after_planning(cell):
    plan = json.loads(PLAN_JSON)["plan"]
    results = run_plan(cell, plan[:4])
    assert all(result.status == "success" for result in results)
    cell.inject_failure("move_part", part="SPACER_LONG", source="BIN_3", destination="BIN_1")
    results = run_plan(cell, plan[4:])
    assert results[-1].status == "not found"
