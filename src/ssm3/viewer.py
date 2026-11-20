"""Visual replay of a run log in a 2D or 3D view of the cell (proposal).

The Design Document plans a 3D view in RoboDK as a Could item (FR14, Chapter 12)
that reads the cell state. This module is a smaller step in the same direction:
it turns one run log (Chapter 10) into a single HTML page that replays the run
in a browser. The page shows the bins, the tray with its two levels, the return
position and the arm, and next to them every planner answer, every verdict of
the checker and every step. It reads only the log file, so it cannot move or
change anything, and the page needs no internet connection and no extra package.

A switch on the page picks the 2D side view or the 3D view, which Mrs Johnson
asked for at Gate A. The 3D view (cell3d.js) draws with three.js, which is kept
in vendor/ with its MIT licence and put into the page, so it still works offline.

Run it on a log with:

    .venv\\Scripts\\python scripts\\view.py demo_logs\\<run>.jsonl

Without a file it takes the newest log in demo_logs. The demo writes a page next
to every log it writes, and --view opens the last one.
"""

import argparse
import copy
import html
import json
import re
import webbrowser
from pathlib import Path

from ssm3.logger import read_log

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOG_DIR = ROOT / "demo_logs"
# The page itself (HTML, CSS and JavaScript) is a separate file next to this one.
PAGE_FILE = Path(__file__).with_name("viewer_page.html")
CELL3D_FILE = Path(__file__).with_name("cell3d.js")
THREE_FILE = Path(__file__).parent / "vendor" / "three.min.js"


def scripts_3d():
    """The three.js library and the 3D view, keyed by the placeholders the pages use for them."""
    return {"__THREE_JS__": THREE_FILE.read_text(encoding="utf-8"),
            "__CELL3D_JS__": CELL3D_FILE.read_text(encoding="utf-8")}


def fill(page, values):
    """Put every value in place of its placeholder in one pass.

    One pass means a value never becomes a placeholder itself: a log text or the
    library may contain "__DATA__", and it stays as it is.
    """
    pattern = re.compile("|".join(re.escape(key) for key in values))
    return pattern.sub(lambda match: values[match.group(0)], page)


def _stack(state, position):
    """The list of parts at a position of the state, or None for a position without parts."""
    if position in state["bins"]:
        return state["bins"][position]
    if position in state["slots"]:
        return state["slots"][position]
    if position == "RETURN":
        return state["return"]
    return None


def _undo(record):
    """The state before one successful step, worked out from the state after it."""
    state = copy.deepcopy(record["state"])
    if record.get("status") != "success":
        return state
    args = record.get("args", {})
    if record["function"] == "move_to":
        # Only used for the first step of a run, and every run starts at HOME (Chapter 4).
        state["arm"] = "HOME"
    elif record["function"] == "pick":
        source = _stack(state, args.get("source"))
        if source is not None and state.get("gripper") == args.get("part"):
            source.append(state["gripper"])
            state["gripper"] = None
    elif record["function"] == "place":
        target = _stack(state, args.get("slot"))
        if target and target[-1] == args.get("part"):
            state["gripper"] = target.pop()
    return state


def initial_state(records):
    """The state at the start of the run.

    The demo stores it in the run_start record. For an older log without it, the
    state before the first step is worked out from that step, and a run without
    steps keeps its final state.
    """
    for record in records:
        if record["event"] == "run_start" and record.get("initial_state"):
            return copy.deepcopy(record["initial_state"])
    for record in records:
        if record["event"] == "feedback" and record.get("kind") == "injected failure":
            break
        if record["event"] == "step_result":
            return _undo(record)
    for record in records:
        if record["event"] == "run_end":
            return copy.deepcopy(record["final_state"])
    return None


def build_html(records):
    """Return the replay page for the records of one run log."""
    start = next((record for record in records if record["event"] == "run_start"), {})
    title = f"SSM3 cell replay, order {start.get('order_id', '?')}"
    payload = {"records": records, "initial_state": initial_state(records)}
    # Every "<" is written as <, so no text in the log can end the script element early.
    data = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    page = PAGE_FILE.read_text(encoding="utf-8")
    return fill(page, {"__TITLE__": html.escape(title), "__DATA__": data, **scripts_3d()})


def write_html(log_path, html_path=None):
    """Write the replay page next to the log (same name, .html) and return its path."""
    log_path = Path(log_path)
    html_path = Path(html_path) if html_path else log_path.with_suffix(".html")
    html_path.write_text(build_html(read_log(log_path)), encoding="utf-8")
    return html_path


def newest_log(folder=DEFAULT_LOG_DIR):
    logs = sorted(Path(folder).glob("*.jsonl"), key=lambda path: path.stat().st_mtime)
    if not logs:
        raise SystemExit(f"No run logs in {folder}. Run scripts\\demo.py first.")
    return logs[-1]


def main(argv=None, out=print, show=webbrowser.open):
    parser = argparse.ArgumentParser(description="Write and open a 2D and 3D replay of a run log")
    parser.add_argument("log", nargs="?", help="a .jsonl run log, by default the newest one in demo_logs")
    parser.add_argument("--no-open", action="store_true", help="write the page without opening a browser")
    args = parser.parse_args(argv)
    page = write_html(Path(args.log) if args.log else newest_log())
    out(f"Replay written to: {page}")
    if not args.no_open:
        show(page.resolve().as_uri())
    return page
