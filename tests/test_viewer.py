"""Tests for the 2D replay page of a run log (viewer.py). They only write and read files."""

import json
import re

from ssm3 import demo, viewer
from ssm3.logger import read_log


def never_read(prompt):
    raise AssertionError("the demo waited for input")


def page_data(page):
    match = re.search(r'<script id="run-data" type="application/json">(.*?)</script>', page, re.S)
    return json.loads(match.group(1))


def test_the_demo_writes_a_page_next_to_every_log(tmp_path):
    results = demo.main(["--no-pause", "--log-dir", str(tmp_path)], out=lambda line: None, read=never_read)
    for _, log in results:
        page = log.path.with_suffix(".html")
        assert page.exists()
        data = page_data(page.read_text(encoding="utf-8"))
        assert data["records"] == read_log(log.path)
        assert data["initial_state"] == log.records[0]["initial_state"]


def test_scenario_1_starts_from_the_chapter_13_tray(tmp_path):
    [(_, log)] = demo.main(["--no-pause", "--scenario", "1", "--log-dir", str(tmp_path)], out=lambda line: None,
                           read=never_read)
    state = viewer.initial_state(read_log(log.path))
    assert state["slots"]["SLOT_2"] == ["SPACER_SHORT"]
    assert state["bins"]["BIN_3"] == ["SPACER_LONG"]
    assert (state["gripper"], state["arm"]) == (None, "HOME")


def test_an_older_log_without_a_start_state_is_worked_out_from_the_first_step(tmp_path):
    [(_, log)] = demo.main(["--no-pause", "--scenario", "1", "--log-dir", str(tmp_path)], out=lambda line: None,
                           read=never_read)
    records = read_log(log.path)
    expected = records[0].pop("initial_state")
    assert viewer.initial_state(records) == expected


def test_undoing_a_pick_and_a_place():
    after_pick = {"event": "step_result", "function": "pick", "status": "success",
                  "args": {"part": "SPACER_SHORT", "source": "SLOT_2"},
                  "state": {"bins": {}, "slots": {"SLOT_2": []}, "return": [], "gripper": "SPACER_SHORT",
                            "arm": "SLOT_2"}}
    before = viewer.initial_state([after_pick])
    assert (before["slots"]["SLOT_2"], before["gripper"]) == (["SPACER_SHORT"], None)
    after_place = {"event": "step_result", "function": "place", "status": "success",
                   "args": {"part": "SPACER_SHORT", "slot": "RETURN"},
                   "state": {"bins": {}, "slots": {}, "return": ["SPACER_SHORT"], "gripper": None, "arm": "RETURN"}}
    before = viewer.initial_state([after_place])
    assert (before["return"], before["gripper"]) == ([], "SPACER_SHORT")


def test_text_in_the_log_cannot_close_the_script_element(tmp_path):
    records = [{"event": "run_start", "order_id": "K-1", "instruction": "x", "variant": "open loop"},
               {"event": "planner_response", "call": 1, "raw": "</script><script>alert(1)</script>", "seconds": 0.1}]
    page = viewer.build_html(records)
    assert "<script>alert(1)" not in page
    assert page_data(page)["records"][1]["raw"] == "</script><script>alert(1)</script>"


def test_view_opens_the_last_page(tmp_path):
    opened = []
    results = demo.main(["--no-pause", "--scenario", "2", "--view", "--log-dir", str(tmp_path)],
                        out=lambda line: None, read=never_read, show=opened.append)
    assert opened == [results[-1][1].path.with_suffix(".html").resolve().as_uri()]


def test_the_script_writes_a_page_for_the_newest_log(tmp_path, monkeypatch):
    demo.main(["--no-pause", "--scenario", "1", "--log-dir", str(tmp_path)], out=lambda line: None, read=never_read)
    monkeypatch.setattr(viewer, "DEFAULT_LOG_DIR", tmp_path)
    opened = []
    page = viewer.main([str(viewer.newest_log(tmp_path))], out=lambda line: None, show=opened.append)
    assert page.exists() and opened == [page.resolve().as_uri()]
