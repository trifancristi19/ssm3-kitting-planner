"""Smoke tests for the ssm3 package and the example capability file."""

import importlib
import json
from pathlib import Path

import pytest

from ssm3.capability import load_capability

ROOT = Path(__file__).resolve().parent.parent
MODULES = ["baseline", "capability", "cell", "checker", "console", "evaluator",
           "functions", "logger", "orchestrator", "planner"]


@pytest.mark.parametrize("name", MODULES)
def test_module_imports_and_has_a_docstring(name):
    module = importlib.import_module(f"ssm3.{name}")
    assert "Design Document" in module.__doc__


def test_example_capability_file_loads():
    capability = load_capability(ROOT / "config" / "capability_example.json")
    assert set(capability) == {"positions", "parts", "limits"}
    bins = capability["positions"]["bins"]
    assert all(source in bins for source in capability["parts"].values())


# The example capability file of Chapter 6 in Design Document 0.4, copied exactly. CI cannot read the
# Design Document, so keep this text in step with Chapter 6 by hand.
CHAPTER_6_CAPABILITY = """
{
  "positions": {
    "home": "HOME",
    "bins": ["BIN_1", "BIN_2", "BIN_3"],
    "slots": ["SLOT_1", "SLOT_2", "SLOT_3", "SLOT_4"],
    "return": "RETURN"
  },
  "parts": {"BOLT": "BIN_1", "SPACER_SHORT": "BIN_2", "SPACER_LONG": "BIN_3"},
  "limits": {"levels_per_slot": 2, "parts_in_gripper": 1, "return_capacity": 8, "max_steps": 40}
}
"""


def test_example_capability_file_is_the_chapter_6_example():
    capability = load_capability(ROOT / "config" / "capability_example.json")
    assert capability == json.loads(CHAPTER_6_CAPABILITY)
    assert capability["limits"] == {"levels_per_slot": 2, "parts_in_gripper": 1, "return_capacity": 8, "max_steps": 40}


def test_return_capacity_is_the_number_of_places_in_the_tray():
    # DD20: the return position holds as many parts as the tray, so a full kit change is never blocked.
    capability = load_capability(ROOT / "config" / "capability_example.json")
    places = len(capability["positions"]["slots"]) * capability["limits"]["levels_per_slot"]
    assert capability["limits"]["return_capacity"] == places
