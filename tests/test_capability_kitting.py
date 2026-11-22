"""Tests for the kitting capability file with the brick list (Design Document, DD24).

config/capability_kitting.json holds the parts of DD24, agreed by the team on 22
November 2026: two brick sizes, 2x2 and 2x4, in three colours, which gives six part
types. Same-colour bricks of different sizes are near-identical on purpose, so the
ambiguity check can be tested (DD25). The tray, the levels and the limits stay as in
Chapter 6, so only the part list and the bins change.
"""

from pathlib import Path

from ssm3.baseline import plan_from_layout
from ssm3.capability import load_capability
from ssm3.cell import SimulatedCell, empty_state
from ssm3.checker import check
from ssm3.functions import move_to, pick, place
from ssm3.planner import build_prompt

ROOT = Path(__file__).resolve().parent.parent
KITTING = ROOT / "config" / "capability_kitting.json"
EXAMPLE = ROOT / "config" / "capability_example.json"

SIZES = ("2X2", "2X4")
COLOURS = ("RED", "BLUE", "YELLOW")


def kitting():
    return load_capability(KITTING)


def stocked_state(capability, per_bin=2):
    """An empty tray with every bin holding per_bin parts of its own type."""
    state = empty_state(capability)
    for part, source in capability["parts"].items():
        state["bins"][source] = [part] * per_bin
    return state


def run(cell, plan):
    names = {"move_to": move_to, "pick": pick, "place": place}
    return [names[s["function"]](cell, **s["args"]).status for s in plan]


def test_kitting_capability_file_loads_with_the_same_sections():
    assert set(kitting()) == {"positions", "parts", "limits"}


def test_parts_are_two_sizes_in_three_colours():
    expected = {f"BRICK_{size}_{colour}" for size in SIZES for colour in COLOURS}
    assert set(kitting()["parts"]) == expected


def test_every_part_has_its_own_bin_and_every_bin_is_used():
    capability = kitting()
    sources = list(capability["parts"].values())
    assert len(sources) == len(set(sources))
    assert sorted(sources) == sorted(capability["positions"]["bins"])


def test_every_colour_has_a_near_identical_pair():
    # Two bricks of the same colour differ only in size, so an order such as "the red brick" is
    # ambiguous. This is what the ambiguity check must catch (Study 1, OD13).
    parts = kitting()["parts"]
    for colour in COLOURS:
        assert [f"BRICK_{size}_{colour}" in parts for size in SIZES] == [True, True]


def test_only_the_parts_and_bins_differ_from_the_chapter_6_example():
    capability, example = kitting(), load_capability(EXAMPLE)
    assert capability["limits"] == example["limits"]
    for key in ("home", "slots", "return"):
        assert capability["positions"][key] == example["positions"][key]


def test_return_capacity_is_the_number_of_places_in_the_tray():
    # DD20: the return position holds as many parts as the tray.
    capability = kitting()
    places = len(capability["positions"]["slots"]) * capability["limits"]["levels_per_slot"]
    assert capability["limits"]["return_capacity"] == places


def test_prompt_lists_every_brick_with_its_bin():
    # DD5: the planner and the checker read the same file.
    capability = kitting()
    prompt = build_prompt({"order_id": "K-1", "text": "Build kit A"}, stocked_state(capability), capability)
    for part, source in capability["parts"].items():
        assert f"{part} in {source}" in prompt


def test_a_brick_kit_is_planned_checked_and_built():
    capability = kitting()
    state = stocked_state(capability)
    target = {
        "SLOT_1": ["BRICK_2X4_RED", "BRICK_2X2_RED"],
        "SLOT_2": ["BRICK_2X4_BLUE"],
        "SLOT_3": ["BRICK_2X2_YELLOW", "BRICK_2X2_BLUE"],
        "SLOT_4": [],
    }
    plan = plan_from_layout({"order_id": "K-1", "target": target, "protected": []}, state, capability)["plan"]
    assert check(plan, state, capability)["verdict"] == "run"
    cell = SimulatedCell(capability, state)
    assert set(run(cell, plan)) == {"success"}
    assert cell.state()["slots"] == target


def test_a_kit_change_swaps_one_brick_for_its_near_identical_twin():
    # The Chapter 13 kind of change with bricks: the small red brick in slot 2 becomes the large one.
    capability = kitting()
    state = stocked_state(capability)
    state["slots"]["SLOT_1"] = ["BRICK_2X4_BLUE"]
    state["slots"]["SLOT_2"] = ["BRICK_2X2_RED"]
    target = {"SLOT_1": ["BRICK_2X4_BLUE"], "SLOT_2": ["BRICK_2X4_RED"], "SLOT_3": [], "SLOT_4": []}
    plan = plan_from_layout({"order_id": "K-2", "target": target, "protected": ["SLOT_1"]}, state, capability)["plan"]
    assert check(plan, state, capability, protected=("SLOT_1",))["verdict"] == "run"
    cell = SimulatedCell(capability, state)
    assert set(run(cell, plan)) == {"success"}
    assert cell.state()["slots"] == target
    assert cell.state()["return"] == ["BRICK_2X2_RED"]


def test_checker_rejects_a_part_that_is_not_a_brick():
    capability = kitting()
    for part in ("BOLT", "BRICK_2X2_GREEN", "BRICK_2X3_RED"):
        plan = [{"function": "move_to", "args": {"position": "BIN_1"}},
                {"function": "pick", "args": {"part": part, "source": "BIN_1"}}]
        result = check(plan, stocked_state(capability), capability)
        assert (result["verdict"], result["step"], result["code"]) == ("reject", 2, "UNKNOWN_PART")


def test_checker_rejects_picking_a_brick_from_the_wrong_bin():
    # BIN_1 holds the small red brick, so its near-identical twin is not there.
    capability = kitting()
    plan = [{"function": "move_to", "args": {"position": "BIN_1"}},
            {"function": "pick", "args": {"part": "BRICK_2X4_RED", "source": "BIN_1"}}]
    result = check(plan, stocked_state(capability), capability)
    assert (result["verdict"], result["step"], result["code"]) == ("reject", 2, "PART_MISSING")
