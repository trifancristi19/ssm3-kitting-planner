"""Shared test setup.

Tests never use the network, so they can never call an LLM or spend API limits.
Any attempt to open a connection fails the test.

The fixtures below hold the examples of Chapters 6 and 13 of the Design Document.
"""

import copy
import json
import socket
from pathlib import Path

import pytest

from ssm3.capability import load_capability
from ssm3.cell import SimulatedCell, empty_state

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise RuntimeError("Tests must not use the network (no LLM calls in tests or CI)")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


# The Chapter 6 plan of Design Document 0.4, copied exactly. CI cannot read the Design Document,
# so keep this text in step with Chapter 6 by hand.
PLAN_JSON = """
{"plan": [
  {"function": "move_to", "args": {"position": "SLOT_2"}},
  {"function": "pick", "args": {"part": "SPACER_SHORT", "source": "SLOT_2"}},
  {"function": "move_to", "args": {"position": "RETURN"}},
  {"function": "place", "args": {"part": "SPACER_SHORT", "slot": "RETURN"}},
  {"function": "move_to", "args": {"position": "BIN_3"}},
  {"function": "pick", "args": {"part": "SPACER_LONG", "source": "BIN_3"}},
  {"function": "move_to", "args": {"position": "SLOT_2"}},
  {"function": "place", "args": {"part": "SPACER_LONG", "slot": "SLOT_2", "level": "base"}},
  {"function": "move_to", "args": {"position": "HOME"}}
]}
"""


@pytest.fixture
def capability():
    # Chapter 13 has a blue spacer that the Chapter 6 example lacks, so it goes in a fourth bin here.
    # The part list is open (OD11), so the parts in config/ stay as in Chapter 6.
    data = copy.deepcopy(load_capability(ROOT / "config" / "capability_example.json"))
    data["positions"]["bins"].append("BIN_4")
    data["parts"]["SPACER_BLUE"] = "BIN_4"
    return data


@pytest.fixture
def chapter6_plan():
    return json.loads(PLAN_JSON)["plan"]


@pytest.fixture
def cell(capability):
    """The Chapter 13 initial state."""
    state = empty_state(capability)
    state["slots"]["SLOT_1"] = ["SPACER_BLUE"]
    state["slots"]["SLOT_2"] = ["SPACER_SHORT"]
    state["slots"]["SLOT_3"] = ["BOLT"]
    state["bins"]["BIN_3"] = ["SPACER_LONG"]
    return SimulatedCell(capability, state)
