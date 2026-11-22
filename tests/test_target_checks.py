"""Tests for DD25 and DD26 (Design Document 0.5, Table 13, agreed on 22 November 2026).

The order check before planning (AMBIGUOUS), and in the checker RULE_OVERRIDE, TARGET_CHANGED and
TARGET_MISMATCH, on their own and inside the orchestrator loop. The brick tests use the six bricks
of OD11 and their vocabulary (config/capability_kitting.json).
"""

import json
from pathlib import Path

import pytest
from target_helper import CHAPTER_13_START, CHAPTER_13_TARGET, add_target

from ssm3.capability import load_capability
from ssm3.cell import SimulatedCell, empty_state
from ssm3.checker import check
from ssm3.console import ScriptedOperator
from ssm3.logger import RunLog
from ssm3.orchestrator import run_order
from ssm3.order_check import find_ambiguity, vocabulary

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


def unclear(text, bricks, answers=()):
    capability, state = bricks
    return find_ambiguity(text, state, capability, {0: list(answers)})


# Vocabulary

def test_the_vocabulary_comes_from_the_capability_file(bricks):
    capability, _ = bricks
    nouns, describing = vocabulary(capability)
    assert nouns["BRICK_2X4_RED"] == {"brick", "block", "piece", "one"}
    assert {"red", "2x4", "big", "long", "larger"} <= describing["BRICK_2X4_RED"]
    assert {"2x2", "small", "little", "shorter"} <= describing["BRICK_2X2_BLUE"]


def test_without_a_vocabulary_the_words_come_from_the_part_id(capability):
    nouns, describing = vocabulary(capability)
    assert (nouns["SPACER_SHORT"], describing["SPACER_SHORT"]) == ({"spacer"}, {"short"})
    assert (nouns["BOLT"], describing["BOLT"]) == ({"bolt"}, set())


# The order check before planning (AMBIGUOUS)

@pytest.mark.parametrize("text", [
    "Put the red brick in slot 4.",
    "Put a yellow block on top of slot 1.",
    "Place the long brick in slot 3.",
    "Put one red brick in slot 4.",
    "Move the red bricks to the return position.",
])
def test_a_description_that_fits_two_parts_asks(bricks, text):
    number, reason = unclear(text, bricks)
    assert number == 0 and "fits" in reason and reason.endswith("Which part is meant?")


@pytest.mark.parametrize("text", [
    "Put the 2x4 red brick in slot 4.",
    "Put the red 2 by 4 brick in slot 4.",
    "Put the red 2×2 brick in slot 4.",
    "Put the big red one in slot 4.",
    "Put the small yellow piece in slot 2.",
    "Replace the red brick in slot 1 with a blue 2x4 brick.",
    "Put BRICK_2X2_RED in slot 4.",
    "Put any red brick in slot 4.",
    "Put either yellow brick on slot 2.",
    "Move the 2x4 red bricks to the return position.",
    "Empty slot 1.",
    "Move the part in slot 1 to the return position.",
])
def test_a_clear_order_passes(bricks, text):
    assert unclear(text, bricks) is None


@pytest.mark.parametrize("text, clear", [
    # Review of pull request 11: here slot 1 is where the spacer goes, so it settles nothing.
    ("Put a spacer in slot 1.", False),
    ("Take the spacer from slot 1 to the return position.", True),
    ("Move the spacer in slot 1 to slot 4.", True),
    ("Replace the spacer in slot 2 with a long spacer.", True),
    ("Remove the spacer in slot 1.", True),
    ("Put a spacer in slot 4. Move the bolt in slot 3 to slot 4.", False),
])
def test_a_named_slot_settles_a_mention_only_where_the_part_is_now(cell, text, clear):
    # The Chapter 13 start: slot 1 a blue spacer, slot 2 a short spacer, the long spacer in BIN_3.
    assert (find_ambiguity(text, cell.state(), cell.capability) is None) == clear


def test_the_red_brick_named_as_destination_still_asks(bricks):
    # Slot 1 holds the 2x4 red brick, but "put the red brick in slot 1" names where a brick goes.
    assert unclear("Put the red brick in slot 1.", bricks) is not None


def test_an_unknown_word_asks(bricks):
    number, reason = unclear("Put the green brick in slot 4.", bricks)
    assert 'The word "green"' in reason


def test_a_mention_without_a_matching_part_asks(bricks):
    capability, state = bricks
    state["bins"]["BIN_3"], state["bins"]["BIN_4"] = [], []  # no blue brick anywhere
    number, reason = find_ambiguity("Put the blue brick in slot 4.", state, capability)
    assert reason.startswith('No part in the cell fits "blue brick".')


def test_each_unclear_mention_has_its_own_number(bricks):
    text = "Put the 2x4 blue brick in slot 2 and the yellow brick in slot 3."
    number, reason = unclear(text, bricks)
    assert number == 1 and '"yellow brick"' in reason


@pytest.mark.parametrize("answer, settled", [
    ("the 2x4 one", True),
    ("BRICK_2X2_RED", True),
    ("the small 2 x 2", True),
    ("the bigger one", True),
    ("no further information", False),
    ("the red one", False),
])
def test_an_operator_answer_can_settle_it(bricks, answer, settled):
    assert (unclear("Put the red brick in slot 4.", bricks, [answer]) is None) == settled


def test_an_answer_about_one_part_does_not_settle_another(bricks):
    text = "Put the red brick in slot 3 and the yellow brick in slot 4."
    assert unclear(text, bricks, ["2x2"])[0] == 1


def test_an_answer_can_also_settle_an_unknown_word(bricks):
    assert unclear("Put the green brick in slot 4.", bricks, ["I meant the 2x4 yellow one"]) is None


# The checker: RULE_OVERRIDE, TARGET_CHANGED and TARGET_MISMATCH

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


def test_a_plan_must_end_with_an_empty_gripper(bricks):
    # The planner always sends the full remaining plan (DD26): a plan that stops after a pick is not complete.
    capability, state = bricks
    half = red_2x2_to_slot_4()[:2]
    result = check(half, state, capability, target=tray(state))
    assert result["code"] == "TARGET_MISMATCH" and "the gripper still holds BRICK_2X2_RED" in result["reason"]


def test_an_empty_plan_passes_only_when_the_tray_already_matches(bricks):
    capability, state = bricks
    assert check([], state, capability, target=tray(state))["verdict"] == "run"
    assert check([], state, capability, target=tray(state, SLOT_4=["BRICK_2X2_RED"]))["code"] == "TARGET_MISMATCH"


def test_a_changed_target_is_rejected(bricks):
    capability, state = bricks
    fixed = tray(state, SLOT_4=["BRICK_2X2_RED"])
    result = check(red_2x2_to_slot_4(), state, capability, target=tray(state, SLOT_4=["BRICK_2X2_BLUE"]),
                   fixed_target=fixed)
    assert (result["code"], result["reason"]) == ("TARGET_CHANGED", "The target of this order is fixed, but this "
                                                                     "plan changes it for SLOT_4")
    assert check(red_2x2_to_slot_4(), state, capability, target=fixed, fixed_target=fixed)["verdict"] == "run"


def test_without_a_target_only_the_steps_are_checked(bricks):
    capability, state = bricks
    assert check(red_2x2_to_slot_4()[:2], state, capability)["verdict"] == "run"


# Inside the orchestrator loop

class Planner:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.histories = []

    def __call__(self, order, state, capability, history):
        self.histories.append(history)
        answer = self.answers.pop(0)
        answer = answer(history) if callable(answer) else answer
        return add_target(answer, state, capability)


def plan(steps, target=None):
    return json.dumps({"plan": steps} if target is None else {"plan": steps, "target": target})


def run(capability, state, text, planner, operator=None, variant="open loop", **options):
    log = RunLog("od13")
    operator = operator or ScriptedOperator()
    summary = run_order({"order_id": "K-30", "text": text, **options.pop("order", {})}, variant, planner=planner,
                        cell=SimulatedCell(capability, state), operator=operator, log=log, **options)
    return summary, log, operator


def test_an_unclear_order_is_asked_before_planning_and_the_answer_settles_it(bricks):
    capability, state = bricks
    planner = Planner(plan(red_2x2_to_slot_4()))
    summary, log, _ = run(capability, state, "Put the red brick in slot 4.", planner, ScriptedOperator(["2x2"]))
    assert summary["outcome"] == "done"
    order_check = log.of_kind("check_result")[0]
    assert (order_check["stage"], order_check["code"], order_check["verdict"]) == ("order", "AMBIGUOUS", "ask")
    [intervention] = log.of_kind("intervention")
    assert (intervention["kind"], intervention["source"], intervention["answer"]) == ("clarification",
                                                                                       "order check", "2x2")
    # The planner is called only after the answer, and gets it in its history.
    assert planner.histories[0][0]["answer"] == "2x2"
    assert summary["final_state"]["slots"]["SLOT_4"] == ["BRICK_2X2_RED"]


def test_an_answer_that_does_not_settle_it_stops_the_run_before_planning(bricks):
    capability, state = bricks
    planner = Planner()
    summary, log, operator = run(capability, state, "Put the red brick in slot 4.", planner,
                                 ScriptedOperator(["the red one"]))
    assert summary["outcome"] == "stopped" and "did not settle the order" in summary["reason"]
    assert (summary["planner_calls"], summary["interventions"]) == (0, 1)
    assert operator.questions == [log.of_kind("intervention")[0]["question"]]


def test_two_unclear_mentions_are_asked_one_after_the_other(bricks):
    capability, state = bricks
    text = "Put the red brick in slot 3 and the yellow brick in slot 4."
    steps = red_2x2_to_slot_4()[:2] + [step("move_to", position="SLOT_3"),
                                       step("place", part="BRICK_2X2_RED", slot="SLOT_3", level="base"),
                                       step("move_to", position="BIN_6"),
                                       step("pick", part="BRICK_2X4_YELLOW", source="BIN_6"),
                                       step("move_to", position="SLOT_4"),
                                       step("place", part="BRICK_2X4_YELLOW", slot="SLOT_4", level="base")]
    summary, log, _ = run(capability, state, text, Planner(plan(steps)), ScriptedOperator(["2x2", "the big one"]))
    assert summary["outcome"] == "done" and summary["interventions"] == 2


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


CHAPTER_13_TEXT = ("Replace the short spacer in slot 2 with a long spacer. Put the short spacer in the return "
                   "position. Leave slots 1 and 3 unchanged.")


def remaining(chapter6_plan, target):
    def answer(history):
        done = sum(1 for event in history if event["type"] == "step" and event["status"] == "success")
        return plan(chapter6_plan[done:], target)

    return answer


def test_the_closed_loop_cannot_end_early_on_an_empty_plan(cell, chapter6_plan):
    # DD26: an empty plan before the tray is complete is a TARGET_MISMATCH, so the planner has to go on.
    planner = Planner(plan(chapter6_plan, CHAPTER_13_TARGET), plan([], CHAPTER_13_TARGET),
                      *[remaining(chapter6_plan, CHAPTER_13_TARGET)] * 9)
    summary, log, _ = run(cell.capability, cell.state(), CHAPTER_13_TEXT, planner, variant="closed loop",
                          protected=("SLOT_1", "SLOT_3"), expected_plan=chapter6_plan)
    assert [record["code"] for record in log.of_kind("check_result")][:2] == [None, "TARGET_MISMATCH"]
    assert summary["outcome"] == "done"
    assert summary["final_state"]["slots"]["SLOT_2"] == ["SPACER_LONG"]


def test_the_target_is_fixed_once_a_plan_has_run(cell, chapter6_plan):
    # After the first step the planner changes its mind about the tray: TARGET_CHANGED, the run does not follow.
    other = dict(CHAPTER_13_TARGET, SLOT_4=["BOLT"])
    goes_elsewhere = plan(chapter6_plan[1:] + [], other)
    planner = Planner(plan(chapter6_plan, CHAPTER_13_TARGET), goes_elsewhere,
                      *[remaining(chapter6_plan, CHAPTER_13_TARGET)] * 9)
    summary, log, _ = run(cell.capability, cell.state(), CHAPTER_13_TEXT, planner, variant="closed loop",
                          protected=("SLOT_1", "SLOT_3"), expected_plan=chapter6_plan)
    assert [record["code"] for record in log.of_kind("check_result")][:2] == [None, "TARGET_CHANGED"]
    assert summary["outcome"] == "done"


def test_an_operator_answer_lets_the_target_change(cell, chapter6_plan):
    # The planner asks during the run, and after the answer a new target is fine.
    keep = dict(CHAPTER_13_START)
    planner = Planner(plan(chapter6_plan, CHAPTER_13_TARGET), '{"ask": "Should slot 2 really change?"}',
                      plan([step("move_to", position="HOME")], keep), plan([], keep))
    summary, log, _ = run(cell.capability, cell.state(), CHAPTER_13_TEXT, planner, ScriptedOperator(["No, stop"]),
                          variant="closed loop", protected=("SLOT_1", "SLOT_3"))
    codes = [record["code"] for record in log.of_kind("check_result")]
    assert "TARGET_CHANGED" not in codes
    assert summary["final_state"]["slots"]["SLOT_2"] == ["SPACER_SHORT"]


def test_a_structured_order_gives_the_target_and_the_log_keeps_it(cell, chapter6_plan):
    # The planner claims the tray it starts from, but the structured order asks for the Chapter 13 tray.
    planner = Planner(plan(chapter6_plan, CHAPTER_13_START))
    summary, log, _ = run(cell.capability, cell.state(), "Kit change K-17", planner,
                          order={"target": CHAPTER_13_TARGET})
    first = log.of_kind("check_result")[0]
    assert first["verdict"] == "run" and first["target"] == CHAPTER_13_TARGET
    assert summary["outcome"] == "done"
