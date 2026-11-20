"""Tests for the 2D and 3D replay page of a run log (viewer.py). They only write and read files."""

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


# The 3D view: three.js and cell3d.js are put into the page, so it works offline

THREE_HEADER = "Copyright 2010-2022 Three.js Authors"


def test_the_page_holds_three_js_and_the_3d_view_once(tmp_path):
    [(_, log)] = demo.main(["--no-pause", "--scenario", "1", "--log-dir", str(tmp_path)], out=lambda line: None,
                           read=never_read)
    page = log.path.with_suffix(".html").read_text(encoding="utf-8")
    assert page.count(THREE_HEADER) == 1
    assert page.count("function createCell3D(") == 1
    assert not re.search(r"__(TITLE|DATA|THREE_JS|CELL3D_JS)__", page)
    # The 2D drawing hands every call to the 3D view as well
    for call in ("view3d.drawStatic()", "view3d.drawParts(state)", "view3d.drawArm(ax, ay, holding)",
                 "view3d.drawFlag(pos, kind)", "view3d.drawLoose(name, cx, bottom)"):
        assert call in page
    # Both views draw the arm from one pose function, and the gantry of the first demo is gone.
    assert page.count("function cellArmPose(") == 1
    assert "cellArmPose({ W, TABLE }, ax, ay)" in page and "cellArmPose(L, ax, ay)" in page
    source = viewer.PAGE_FILE.read_text(encoding="utf-8") + viewer.CELL3D_FILE.read_text(encoding="utf-8")
    assert "RAIL" not in source


def test_a_replay_of_a_gripper_fault_has_its_own_words(tmp_path):
    results = demo.main(["--no-pause", "--scenario", "5", "--log-dir", str(tmp_path)], out=lambda line: None,
                        read=never_read)
    page = results[-1][1].path.with_suffix(".html").read_text(encoding="utf-8")
    assert '"failure": "drop_part"' in page and "slips out of the gripper" in page
    assert "function animateDrop(" in page


def test_the_vendored_library_keeps_its_licence_and_cannot_end_a_script_element():
    library = viewer.THREE_FILE.read_text(encoding="utf-8")
    assert library.startswith("/**\n * @license\n * " + THREE_HEADER)
    licence = viewer.THREE_FILE.with_name("three.LICENSE").read_text(encoding="utf-8")
    assert licence.startswith("The MIT License")
    for text in (viewer.CELL3D_FILE.read_text(encoding="utf-8"), library):
        assert not re.search(r"</script|<script|<!--", text, re.I)


def test_placeholders_are_filled_in_one_pass():
    assert viewer.fill("__A__ __B__", {"__A__": "__B__", "__B__": "b"}) == "__B__ b"


def test_a_placeholder_typed_in_an_order_stays_text(tmp_path):
    records = [{"event": "run_start", "order_id": "X", "instruction": "__THREE_JS__ __DATA__", "initial_state": None}]
    page = viewer.build_html(records)
    assert page.count(THREE_HEADER) == 1
    assert page_data(page)["records"][0]["instruction"] == "__THREE_JS__ __DATA__"
