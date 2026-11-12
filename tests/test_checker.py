"""Tests for the checker (Design Document, Chapter 8, Table 9) and the Chapter 13 variations."""

import copy

import pytest

from ssm3.checker import check

PROTECTED = ("SLOT_1", "SLOT_3")


def step(function, **args):
    return {"function": function, "args": args}


def remove(part, slot):
    """Move a part from a slot to the return position."""
    return [step("move_to", position=slot), step("pick", part=part, source=slot),
            step("move_to", position="RETURN"), step("place", part=part, slot="RETURN")]


def add(part, source, slot, level):
    """Move a part from its bin to a level of a slot."""
    return [step("move_to", position=source), step("pick", part=part, source=source),
            step("move_to", position=slot), step("place", part=part, slot=slot, level=level)]


def stacked_state(cell):
    """Chapter 13, variation "A part lies on top": a bolt lies on the short spacer in slot 2."""
    state = cell.state()
    state["slots"]["SLOT_2"] = ["SPACER_SHORT", "BOLT"]
    return state


# The worked example

def test_chapter_6_plan_runs(cell, chapter6_plan):
    result = check(chapter6_plan, cell.state(), cell.capability, protected=PROTECTED)
    assert result["verdict"] == "run"
    assert result["code"] is None


def test_check_result_has_the_fields_of_table_7(cell, chapter6_plan):
    assert set(check(chapter6_plan, cell.state(), cell.capability)) == {"verdict", "step", "code", "reason"}


def test_check_never_changes_the_state_it_is_given(cell, chapter6_plan):
    state = cell.state()
    before = copy.deepcopy(state)
    check(chapter6_plan, state, cell.capability)
    check(chapter6_plan[:1] + [step("pick", part="BOLT", source="SLOT_1")], state, cell.capability)
    assert state == before


# Format, functions and arguments

@pytest.mark.parametrize("plan, code", [
    ("not a list", "FORMAT"),
    (["move_to HOME"], "FORMAT"),
    ([{"function": "move_to"}], "FORMAT"),
    ([step("move_to")], "FORMAT"),
    ([step("move_to", position="HOME", speed=5)], "FORMAT"),
    ([step("ask_operator", question="Which slot?")], "UNKNOWN_FUNCTION"),
    ([step("weld", part="BOLT")], "UNKNOWN_FUNCTION"),
    ([step("move_to", position="MOON")], "UNKNOWN_POSITION"),
    ([step("move_to", position=[0.1, 0.2, 0.3])], "UNKNOWN_POSITION"),
    ([step("locate", part="GHOST")], "UNKNOWN_PART"),
])
def test_format_function_and_argument_codes(cell, plan, code):
    result = check(plan, cell.state(), cell.capability)
    assert result["verdict"] == "reject"
    assert result["code"] == code


def test_locate_of_a_missing_part_never_rejects(cell):
    # Table 6 gives locate no preconditions. It only reads the state, even when the part is not in the cell.
    state = cell.state()
    state["bins"]["BIN_3"] = []
    result = check([step("locate", part="SPACER_LONG")], state, cell.capability)
    assert result["verdict"] == "run"


@pytest.mark.parametrize("plan", [
    None, {}, [None], [[]], [{"function": None, "args": {}}], [{"function": ["move_to"], "args": {}}],
    [step("move_to", position={"x": 1})], [step("pick", part=["BOLT"], source="BIN_1")],
    [step("place", part="BOLT", slot="SLOT_1", level={"top": 1})],
])
def test_odd_plans_always_get_a_check_result(cell, plan):
    result = check(plan, cell.state(), cell.capability)
    assert result["verdict"] == "reject"
    assert result["code"]


def test_step_numbers_count_from_one(cell, chapter6_plan):
    plan = chapter6_plan[:3] + [step("move_to", position="MOON")]
    assert check(plan, cell.state(), cell.capability)["step"] == 4


# BAD_LEVEL (Chapters 5 and 8)

def test_bad_level_for_the_return_position(cell):
    plan = remove("SPACER_SHORT", "SLOT_2")
    plan[3] = step("place", part="SPACER_SHORT", slot="RETURN", level="base")
    result = check(plan, cell.state(), cell.capability)
    assert (result["verdict"], result["step"], result["code"]) == ("reject", 4, "BAD_LEVEL")


@pytest.mark.parametrize("level", ["middle", "BASE", "", 1])
def test_bad_level_for_a_value_other_than_base_or_top(cell, level):
    plan = add("SPACER_LONG", "BIN_3", "SLOT_4", "base")
    plan[3]["args"]["level"] = level
    result = check(plan, cell.state(), cell.capability)
    assert result["code"] == "BAD_LEVEL"
    assert result["step"] == 4


def test_a_place_without_a_level_is_still_valid(cell):
    plan = add("SPACER_LONG", "BIN_3", "SLOT_4", "base")
    del plan[3]["args"]["level"]
    assert check(plan, cell.state(), cell.capability)["verdict"] == "run"


# Preconditions

def test_gripper_full(cell):
    plan = add("SPACER_LONG", "BIN_3", "SLOT_4", "base")[:2] + [step("move_to", position="SLOT_2"),
                                                                 step("pick", part="SPACER_SHORT", source="SLOT_2")]
    assert check(plan, cell.state(), cell.capability)["code"] == "GRIPPER_FULL"


def test_arm_not_there(cell):
    plan = [step("pick", part="SPACER_LONG", source="BIN_3")]
    assert check(plan, cell.state(), cell.capability)["code"] == "ARM_NOT_THERE"


def test_slot_occupied(cell):
    plan = add("SPACER_LONG", "BIN_3", "SLOT_2", "base")
    result = check(plan, cell.state(), cell.capability)
    assert (result["step"], result["code"]) == (4, "SLOT_OCCUPIED")


def test_no_base(cell):
    plan = add("SPACER_LONG", "BIN_3", "SLOT_4", "top")
    result = check(plan, cell.state(), cell.capability)
    assert (result["verdict"], result["step"], result["code"]) == ("reject", 4, "NO_BASE")


def test_part_covered(cell):
    plan = remove("SPACER_SHORT", "SLOT_2")
    result = check(plan, stacked_state(cell), cell.capability)
    assert (result["verdict"], result["step"], result["code"]) == ("reject", 2, "PART_COVERED")


def test_protected_slot(cell):
    plan = remove("SPACER_BLUE", "SLOT_1")
    result = check(plan, cell.state(), cell.capability, protected=PROTECTED)
    assert (result["step"], result["code"]) == (2, "PROTECTED_SLOT")
    plan = add("SPACER_LONG", "BIN_3", "SLOT_3", "top")
    assert check(plan, cell.state(), cell.capability, protected=PROTECTED)["code"] == "PROTECTED_SLOT"


def test_limit_when_the_return_position_is_full(cell):
    state = cell.state()
    state["return"] = ["BOLT"] * cell.capability["limits"]["return_capacity"]
    result = check(remove("SPACER_SHORT", "SLOT_2"), state, cell.capability)
    assert (result["verdict"], result["step"], result["code"]) == ("reject", 4, "LIMIT")


# Several valid orders of placement are all accepted (DD19)

def test_several_valid_orders_are_all_accepted(cell):
    state = cell.state()
    state["bins"]["BIN_1"] = ["BOLT"]
    state["bins"]["BIN_2"] = ["SPACER_SHORT"]
    base_then_top_per_slot = (add("SPACER_LONG", "BIN_3", "SLOT_4", "base")
                              + add("BOLT", "BIN_1", "SLOT_4", "top")
                              + add("SPACER_SHORT", "BIN_2", "SLOT_2", "top"))
    other_slot_first = (add("SPACER_SHORT", "BIN_2", "SLOT_2", "top")
                        + add("SPACER_LONG", "BIN_3", "SLOT_4", "base")
                        + add("BOLT", "BIN_1", "SLOT_4", "top"))
    for plan in (base_then_top_per_slot, other_slot_first):
        assert check(plan, state, cell.capability)["verdict"] == "run"


# The four variations of Chapter 13

def test_variation_long_spacer_missing_is_part_missing_before_the_first_move(cell, chapter6_plan):
    state = cell.state()
    state["bins"]["BIN_3"] = []
    result = check(chapter6_plan, state, cell.capability, protected=PROTECTED)
    assert (result["verdict"], result["code"]) == ("reject", "PART_MISSING")


def test_variation_return_position_full_is_limit(cell, chapter6_plan):
    state = cell.state()
    state["return"] = ["BOLT"] * cell.capability["limits"]["return_capacity"]
    result = check(chapter6_plan, state, cell.capability, protected=PROTECTED)
    assert (result["verdict"], result["step"], result["code"]) == ("reject", 4, "LIMIT")


def test_variation_part_moved_after_planning_fails_the_replay_of_the_old_plan(cell, chapter6_plan):
    assert check(chapter6_plan, cell.state(), cell.capability)["verdict"] == "run"
    cell.inject_failure("move_part", part="SPACER_LONG", source="BIN_3", destination="BIN_1")
    result = check(chapter6_plan, cell.state(), cell.capability)
    assert (result["step"], result["code"]) == (6, "PART_MISSING")


def test_variation_part_on_top(cell):
    state = stacked_state(cell)
    first_the_spacer = remove("SPACER_SHORT", "SLOT_2") + add("SPACER_LONG", "BIN_3", "SLOT_2", "base")
    result = check(first_the_spacer, state, cell.capability, protected=PROTECTED)
    assert (result["step"], result["code"]) == (2, "PART_COVERED")
    top_part_first = (remove("BOLT", "SLOT_2") + remove("SPACER_SHORT", "SLOT_2")
                      + add("SPACER_LONG", "BIN_3", "SLOT_2", "base") + [step("move_to", position="HOME")])
    assert check(top_part_first, state, cell.capability, protected=PROTECTED)["verdict"] == "run"


# BAD_POSITION, agreed by the team for a known position of the wrong kind (Table 9, Arguments, proposal)

def test_bad_position_for_a_pick_from_the_return_position(cell):
    state = cell.state()
    state["return"] = ["BOLT"]
    plan = [step("move_to", position="RETURN"), step("pick", part="BOLT", source="RETURN")]
    result = check(plan, state, cell.capability)
    assert (result["verdict"], result["step"], result["code"]) == ("reject", 2, "BAD_POSITION")


def test_bad_position_for_a_place_into_a_bin(cell):
    plan = add("SPACER_LONG", "BIN_3", "SLOT_4", "base")[:2] + [step("place", part="SPACER_LONG", slot="BIN_3")]
    result = check(plan, cell.state(), cell.capability)
    assert (result["step"], result["code"]) == (3, "BAD_POSITION")


def test_bad_position_for_a_pick_from_home(cell):
    assert check([step("pick", part="BOLT", source="HOME")], cell.state(), cell.capability)["code"] == "BAD_POSITION"


def test_a_place_with_the_wrong_part_in_the_gripper_names_both_parts(cell):
    plan = add("SPACER_LONG", "BIN_3", "SLOT_4", "base")[:3] + [step("place", part="BOLT", slot="SLOT_4")]
    result = check(plan, cell.state(), cell.capability)
    assert result["code"] == "PART_MISSING"
    assert "SPACER_LONG" in result["reason"] and "BOLT" in result["reason"]
