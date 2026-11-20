"""Tests for OD13 and OD14: the checker gets the order and the target tray (Design Document, Table 14).

AMBIGUOUS, RULE_OVERRIDE and TARGET_MISMATCH, on their own and inside the orchestrator loop.
The brick tests use the six bricks of OD11 (config/capability_kitting.json).
"""

import json
from pathlib import Path

import pytest
from target_helper import CHAPTER_13_START, CHAPTER_13_TARGET, add_target

from ssm3.capability import load_capability
from ssm3.cell import SimulatedCell, empty_state
from ssm3.checker import ambiguity, check, part_words
from ssm3.console import ScriptedOperator
from ssm3.logger import RunLog
from ssm3.orchestrator import run_order

ROOT = Path(__file__).resolve().parent.parent


def step(function, **args):
    return {"function": function, "args": args}


@pytest.fixture
def bricks():
    """The OD11 cell: every brick in its own bin, a 2x4 red brick on the base of slot 1."""
    capability = load_capability(ROOT / "config" / "capability_kitting.json")
    state = empty_state(capability)
    for part, source in capability["parts"].items():
        state["bins"][source] = [part]
    state["slots"]["SLOT_1"] = ["BRICK_2X4_RED"]
    return capability, state


def tray(state, **changes):
    target = {slot: list(parts) for slot, parts in state["slots"].items()}
    target.update(changes)
    return target


def red_2x2_to_slot_4():
    return [step("move_to", position="BIN_1"), step("pick", part="BRICK_2X2_RED", source="BIN_1"),
            step("move_to", position="SLOT_4"), step("place", part="BRICK_2X2_RED", slot="SLOT_4", level="base")]


# Part words

def test_part_words_come_from_the_part_id(bricks):
    capability, _ = bricks
    assert part_words(capability, "BRICK_2X4_RED") == ("brick", {"2x4", "red"})
    assert part_words({"parts": {}}, "SPACER_SHORT") == ("spacer", {"short"})


def test_the_capability_file_can_give_other_words():
    capability = {"parts": {"BOLT": "BIN_1"}, "part_words": {"BOLT": ["bolt", "steel"]}}
    assert part_words(capability, "BOLT") == ("bolt", {"steel"})


# AMBIGUOUS

@pytest.mark.parametrize("text", [
    "Put the red brick in slot 4.",
    "Put a yellow brick on top of slot 1.",
    "Place the blue brick in SLOT_3.",
])
def test_a_description_that_fits_two_parts_is_ambiguous(bricks, text):
    capability, state = bricks
    reason = ambiguity(text, state, capability)
    assert reason and "Which one is meant?" in reason


@pytest.mark.parametrize("text", [
    "Put the 2x4 red brick in slot 4.",
    "Put the red 2 x 4 brick in slot 4.",
    "Put the red 2×2 brick in slot 4.",
    "Replace the red brick in slot 1 with a blue 2x4 brick.",
    "Put BRICK_2X2_RED in slot 4.",
    "Move all bricks to the return position.",
    "Put the green brick in slot 4.",
])
def test_a_description_that_fits_one_part_or_none_is_not_ambiguous(bricks, text):
    capability, state = bricks
    assert ambiguity(text, state, capability) is None


def test_only_parts_in_the_cell_count(bricks):
    capability, state = bricks
    state["bins"]["BIN_1"] = []  # no 2x2 red brick anywhere
    state["slots"]["SLOT_1"] = []
    state["bins"]["BIN_2"] = ["BRICK_2X4_RED"]
    assert ambiguity("Put the red brick in slot 4.", state, capability) is None


@pytest.mark.parametrize("answer, settled", [
    ("the 2x4 one", True),
    ("BRICK_2X2_RED", True),
    ("the small 2 x 2", True),
    ("no further information", False),
    ("the red one", False),
])
def test_an_operator_answer_can_settle_it(bricks, answer, settled):
    capability, state = bricks
    text = f"Put the red brick in slot 4.\nOperator answer: {answer}"
    assert (ambiguity(text, state, capability) is None) == settled


def test_the_checker_asks_before_it_looks_at_the_plan(bricks):
    capability, state = bricks
    result = check(red_2x2_to_slot_4(), state, capability, order_text="Put the red brick in slot 4.",
                   target=tray(state, SLOT_4=["BRICK_2X2_RED"]))
    assert (result["verdict"], result["code"]) == ("ask", "AMBIGUOUS")
    assert "BRICK_2X2_RED, BRICK_2X4_RED" in result["reason"]


def test_the_chapter_13_order_is_not_ambiguous(cell, chapter6_plan):
    text = ("Replace the short spacer in slot 2 with a long spacer. Put the short spacer in the return position. "
            "Leave slots 1 and 3 unchanged.")
    result = check(chapter6_plan, cell.state(), cell.capability, ("SLOT_1", "SLOT_3"), text, CHAPTER_13_TARGET)
    assert result["verdict"] == "run"


# RULE_OVERRIDE

@pytest.mark.parametrize("change, words", [
    ({"SLOT_4": ["BRICK_2X4_RED", "BRICK_2X2_RED", "BRICK_2X2_BLUE"]}, "3 parts in SLOT_4"),
    ({"SLOT_4": ["BRICK_2X4_GREEN"]}, "BRICK_2X4_GREEN"),
    ({"SLOT_1": []}, "SLOT_1, which the order protects"),
])
def test_a_target_that_breaks_a_rule_is_a_rule_override(bricks, change, words):
    capability, state = bricks
    result = check([], state, capability, protected=("SLOT_1",), target=tray(state, **change))
    assert (result["verdict"], result["code"]) == ("reject", "RULE_OVERRIDE")
    assert words in result["reason"]


def test_a_plan_that_breaks_a_rule_while_its_target_does_not_keeps_its_own_code(bricks):
    capability, state = bricks
    takes_from_slot_1 = [step("move_to", position="SLOT_1"), step("pick", part="BRICK_2X4_RED", source="SLOT_1")]
    result = check(takes_from_slot_1, state, capability, protected=("SLOT_1",), target=tray(state))
    assert result["code"] == "PROTECTED_SLOT"


@pytest.mark.parametrize("target", [
    {"SLOT_1": ["BRICK_2X4_RED"]},
    {"SLOT_1": ["BRICK_2X4_RED"], "SLOT_2": [], "SLOT_3": [], "SLOT_4": [], "SLOT_9": []},
    {"SLOT_1": "BRICK_2X4_RED", "SLOT_2": [], "SLOT_3": [], "SLOT_4": []},
    ["SLOT_1"],
])
def test_a_target_of_the_wrong_shape_is_a_format_error(bricks, target):
    capability, state = bricks
    assert check([], state, capability, target=target)["code"] == "FORMAT"


# TARGET_MISMATCH (OD14)

def test_a_plan_that_ends_at_its_target_runs(bricks):
    capability, state = bricks
    result = check(red_2x2_to_slot_4(), state, capability, target=tray(state, SLOT_4=["BRICK_2X2_RED"]))
    assert result["verdict"] == "run" and "ends at the target" in result["reason"]


def test_legal_steps_that_end_at_the_wrong_tray_are_a_target_mismatch(bricks):
    capability, state = bricks
    result = check(red_2x2_to_slot_4(), state, capability, target=tray(state, SLOT_3=["BRICK_2X2_RED"]))
    assert (result["verdict"], result["code"]) == ("reject", "TARGET_MISMATCH")
    assert "SLOT_3 holds nothing but the target is ['BRICK_2X2_RED']" in result["reason"]
    assert "SLOT_4 holds ['BRICK_2X2_RED'] but the target is empty" in result["reason"]


def test_an_empty_plan_passes_only_when_the_tray_already_matches(bricks):
    capability, state = bricks
    assert check([], state, capability, target=tray(state))["verdict"] == "run"
    assert check([], state, capability, target=tray(state, SLOT_4=["BRICK_2X2_RED"]))["code"] == "TARGET_MISMATCH"


def test_without_order_text_and_target_only_the_steps_are_checked(bricks):
    capability, state = bricks
    assert check(red_2x2_to_slot_4(), state, capability)["verdict"] == "run"


# Inside the orchestrator loop

class Planner:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.histories = []

    def __call__(self, order, state, capability, history):
        self.histories.append(history)
        return add_target(self.answers.pop(0), state, capability)


def plan(steps, target=None):
    return json.dumps({"plan": steps} if target is None else {"plan": steps, "target": target})


def run(capability, state, text, planner, operator=None, variant="open loop", **options):
    log = RunLog("od13")
    operator = operator or ScriptedOperator()
    summary = run_order({"order_id": "K-30", "text": text, **options.pop("order", {})}, variant, planner=planner,
                        cell=SimulatedCell(capability, state), operator=operator, log=log, **options)
    return summary, log, operator


def test_an_ambiguous_order_asks_the_operator_and_the_answer_settles_it(bricks):
    capability, state = bricks
    planner = Planner(plan(red_2x2_to_slot_4()), plan(red_2x2_to_slot_4()))
    operator = ScriptedOperator(["the 2x2 one"])
    summary, log, _ = run(capability, state, "Put the red brick in slot 4.", planner, operator)
    assert summary["outcome"] == "done"
    assert [record["code"] for record in log.of_kind("check_result")] == ["AMBIGUOUS", None]
    [intervention] = log.of_kind("intervention")
    assert (intervention["kind"], intervention["source"], intervention["answer"]) == ("clarification", "checker",
                                                                                       "the 2x2 one")
    assert summary["final_state"]["slots"]["SLOT_4"] == ["BRICK_2X2_RED"]


def test_a_planner_question_also_settles_the_ambiguity(bricks):
    capability, state = bricks
    planner = Planner('{"ask": "The 2x2 or the 2x4 red brick?"}', plan(red_2x2_to_slot_4()))
    summary, log, _ = run(capability, state, "Put the red brick in slot 4.", planner, ScriptedOperator(["2x2"]))
    assert summary["outcome"] == "done"
    assert summary["interventions"] == 1


def test_a_rule_override_is_rejected_and_the_operator_is_told(bricks):
    capability, state = bricks
    empties_slot_1 = [step("move_to", position="SLOT_1"), step("pick", part="BRICK_2X4_RED", source="SLOT_1"),
                      step("move_to", position="RETURN"), step("place", part="BRICK_2X4_RED", slot="RETURN")]
    planner = Planner(plan(empties_slot_1), '{"refuse": "Slot 1 stays as it is"}')
    summary, log, operator = run(capability, state, "Empty slot 1 even though it is protected.", planner,
                                 protected=("SLOT_1",))
    assert log.of_kind("check_result")[0]["code"] == "RULE_OVERRIDE"
    assert any("No order can change a rule of the cell" in message for message in operator.messages)
    assert planner.histories[1][-1]["code"] == "RULE_OVERRIDE"
    assert summary["outcome"] == "refused" and summary["final_state"]["slots"]["SLOT_1"] == ["BRICK_2X4_RED"]


def test_the_closed_loop_cannot_end_early_on_an_empty_plan(cell, chapter6_plan):
    # OD14: an empty plan before the tray is complete is a TARGET_MISMATCH, so the planner has to go on.
    def remaining(history):
        done = sum(1 for event in history if event["type"] == "step" and event["status"] == "success")
        return plan(chapter6_plan[done:], CHAPTER_13_TARGET)

    # First a one-step plan, then an empty plan although slot 2 still holds the short spacer, then the rest.
    first_two = [plan(chapter6_plan[:1], CHAPTER_13_TARGET), plan([], CHAPTER_13_TARGET)]

    def scripted(order, state, capability, history):
        return first_two.pop(0) if first_two else remaining(history)

    text = ("Replace the short spacer in slot 2 with a long spacer. Put the short spacer in the return position. "
            "Leave slots 1 and 3 unchanged.")
    summary, log, _ = run(cell.capability, cell.state(), text, scripted, variant="closed loop",
                          protected=("SLOT_1", "SLOT_3"), expected_plan=chapter6_plan)
    codes = [record["code"] for record in log.of_kind("check_result")]
    assert codes[1] == "TARGET_MISMATCH"
    assert summary["outcome"] == "done"
    assert summary["final_state"]["slots"]["SLOT_2"] == ["SPACER_LONG"]


def test_a_structured_order_gives_the_target_and_the_log_keeps_it(cell, chapter6_plan):
    # The planner claims the tray it starts from, but the structured order asks for the Chapter 13 tray.
    planner = Planner(plan(chapter6_plan, CHAPTER_13_START))
    summary, log, _ = run(cell.capability, cell.state(), "Kit change K-17", planner,
                          order={"target": CHAPTER_13_TARGET})
    first = log.of_kind("check_result")[0]
    assert first["verdict"] == "run" and first["target"] == CHAPTER_13_TARGET
    assert summary["outcome"] == "done"
