"""Simulated kitting cell (Design Document, Chapters 4 and 12).

A state-based Python model of the cell: fixed supply bins, a tray with numbered
slots, a return position, a gripper that holds one part and the arm position.
The simulator is the authoritative source of the cell state (Table 2), and it can
inject failures, such as a part moved after planning (FR11).

This module works. The state is a plain dict that can go straight to JSON
(Chapter 6): bins and slots map a name to a list of part IDs, "return" is a list,
"gripper" is a part ID or None and "arm" is a position name. The caller decides
what is in the bins. The cell assumes no supply quantity. Part IDs and kit
variants stay open (OD11), so nothing here lists parts. Only the function library
changes the state, apart from inject_failure. The cell does not decide any open
question, such as rejection codes, retry counts or placement order (OD3, OD4, OD10).
"""

import copy

FAILURE_KINDS = ("move_part", "pick_failure")


def empty_state(capability):
    """Build an empty cell state: nothing anywhere, gripper empty, arm at home."""
    positions = capability["positions"]
    return {
        "bins": {name: [] for name in positions["bins"]},
        "slots": {name: [] for name in positions["slots"]},
        "return": [],
        "gripper": None,
        "arm": positions["home"],
    }


class SimulatedCell:
    """The cell state and its changes. Only the function library changes it."""

    def __init__(self, capability, state):
        self.capability = capability
        self._state = copy.deepcopy(state)
        self._pick_failure_pending = False

    def state(self):
        """Return a deep copy of the current cell state (Table 7, cell state)."""
        return copy.deepcopy(self._state)

    # Names of positions

    def positions(self):
        """Return every valid position: home, the bins, the slots and the return position."""
        names = self.capability["positions"]
        return [names["home"], *names["bins"], *names["slots"], names["return"]]

    def is_bin(self, position):
        return position in self.capability["positions"]["bins"]

    def is_slot(self, position):
        return position in self.capability["positions"]["slots"]

    def is_return(self, position):
        return position == self.capability["positions"]["return"]

    # Contents of places

    def contents(self, position):
        """Return a copy of the part IDs at a bin, slot or the return position."""
        return list(self._contents_list(position))

    def is_free(self, position):
        """A slot or the return position is free while it holds fewer parts than the limit."""
        limit = self.capability["limits"]["parts_per_slot"]
        return len(self._contents_list(position)) < limit

    def _contents_list(self, position):
        if self.is_bin(position):
            return self._state["bins"][position]
        if self.is_slot(position):
            return self._state["slots"][position]
        if self.is_return(position):
            return self._state["return"]
        raise ValueError(f"{position!r} is not a bin, a slot or the return position")

    # Changes, used by the function library

    def set_arm(self, position):
        if position not in self.positions():
            raise ValueError(f"unknown position {position!r}")
        self._state["arm"] = position

    def take_into_gripper(self, part, source):
        """Move a part from a bin or slot into the gripper."""
        self._contents_list(source).remove(part)
        self._state["gripper"] = part

    def release_from_gripper(self, target):
        """Move the held part into a slot or the return position."""
        self._contents_list(target).append(self._state["gripper"])
        self._state["gripper"] = None

    def consume_pick_failure(self):
        """Return True once if a pick failure was injected, then clear it."""
        pending = self._pick_failure_pending
        self._pick_failure_pending = False
        return pending

    # Failure injection

    def inject_failure(self, kind, part=None, source=None, destination=None):
        """Change the cell outside the plan (FR11, Chapter 9).

        "move_part" moves a part from source to destination, as if someone moved
        it after planning. "pick_failure" makes the next pick return failed.
        """
        if kind == "pick_failure":
            self._pick_failure_pending = True
        elif kind == "move_part":
            self._move_part(part, source, destination)
        else:
            raise ValueError(f"unknown failure kind {kind!r}, expected one of {FAILURE_KINDS}")

    def _move_part(self, part, source, destination):
        if part not in self._contents_list(source):
            raise ValueError(f"{part!r} is not at {source!r}")
        if destination == source:
            raise ValueError("source and destination are the same")
        if not self.is_bin(destination) and not self.is_free(destination):
            raise ValueError(f"{destination!r} is not free")
        self._contents_list(source).remove(part)
        self._contents_list(destination).append(part)
