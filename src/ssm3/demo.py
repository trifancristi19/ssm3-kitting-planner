"""Terminal demo for the client meeting at Gate A (Design Document, Chapters 6, 9 and 13).

The demo runs the worked example of Chapter 13 through the real cell, checker,
orchestrator loop and run log. The five scenarios use a scripted planner, which
reads the cell state and writes a plan from it, so they call no language model and
no network. The loop, the checker and the feedback are the same code the language
model uses.

--live runs the same order once with the real model on Groq instead (DD17), in the
closed loop. It uses the Groq free-tier limit, needs GROQ_API_KEY and is never run
by the tests. If the key is missing or a call fails, the demo says why and offers
the scripted version of the same order. --live --local uses a local model through
Ollama instead of Groq (proposal, demo only), which needs no key and no free-tier limit.

Run it from the repository folder on Windows with:

    .venv\\Scripts\\python scripts\\demo.py
    .venv\\Scripts\\python scripts\\demo.py --live

Scenarios 4 and 5 answer a question of Mrs Johnson at Gate A: what happens when a
step is allowed but the gripper fails, because it gets no hold on the part or the
part slips out after it was lifted. Each runs in both loops, so the log shows the
failed step, the feedback and what the system did next.

Options: --no-pause runs without the "press Enter" pauses, --scenario 1 to 5
runs one scenario, and --log-dir sets the folder for the run logs (demo_logs by
default, which git ignores). With --live: --variant open runs the open loop (one
model call), --model changes the model and --delay sets the seconds between model
calls (2.5 by default, as in the model tests).

Every run also gets a replay page in 2D and 3D next to its log (viewer.py), and --view
opens the page of the last run in the browser.
"""

import argparse
import copy
import json
import textwrap
import time
import webbrowser
from datetime import datetime
from pathlib import Path

from ssm3 import planner as planner_module
from ssm3 import viewer
from ssm3.capability import load_capability
from ssm3.cell import LEVELS, SimulatedCell, empty_state
from ssm3.console import ScriptedOperator, TerminalOperator
from ssm3.logger import RunLog
from ssm3.orchestrator import run_order

ROOT = Path(__file__).resolve().parents[2]
CAPABILITY_FILE = ROOT / "config" / "capability_example.json"

ORDER = {
    "order_id": "K-17",
    "text": "Replace the short spacer in slot 2 with a long spacer. Put the short spacer in the return position. "
            "Leave slots 1 and 3 unchanged.",
}
PROTECTED = ("SLOT_1", "SLOT_3")
SLOT = "SLOT_2"
TARGET = ["SPACER_LONG"]

PLANNER_NOTE = "Planner: scripted (no language model in this run). Cell, checker, loop and run log: real code."
WIDTH = 64


# The cell of Chapter 13

def demo_capability():
    """The Chapter 6 capability file, with a fourth bin for the blue spacer of Chapter 13."""
    capability = copy.deepcopy(load_capability(CAPABILITY_FILE))
    capability["positions"]["bins"].append("BIN_4")
    capability["parts"]["SPACER_BLUE"] = "BIN_4"
    return capability


def chapter_13_state(capability, part_on_top=None):
    """The Chapter 13 start: slot 1 a blue spacer, slot 2 a short spacer, slot 3 a bolt, the long spacer in BIN_3."""
    state = empty_state(capability)
    state["slots"]["SLOT_1"] = ["SPACER_BLUE"]
    state["slots"]["SLOT_2"] = ["SPACER_SHORT"]
    state["slots"]["SLOT_3"] = ["BOLT"]
    state["bins"]["BIN_1"] = ["BOLT"]
    state["bins"]["BIN_3"] = ["SPACER_LONG"]
    if part_on_top:
        state["slots"]["SLOT_2"].append(part_on_top)
    return state


# The scripted planner

def _step(function, **args):
    return {"function": function, "args": args}


def target_tray(state):
    """The tray order K-17 asks for: slot 2 holds the long spacer, every other slot stays as it is (DD25)."""
    tray = {slot: list(parts) for slot, parts in state["slots"].items()}
    tray[SLOT] = list(TARGET)
    return tray


def plan_from_state(state):
    """Write the remaining plan for order K-17 from the cell state, the way the planner should.

    The plan empties slot 2 from the top down into the return position, fetches the
    long spacer from whichever bin holds it now, places it on the base and moves the
    arm home. When the order is complete it is an empty plan, which ends the closed loop.
    """
    steps = []
    arm = state["arm"]
    held = state["gripper"]
    current = list(state["slots"][SLOT])

    def go(position):
        nonlocal arm
        if arm != position:
            steps.append(_step("move_to", position=position))
            arm = position

    keep = 0
    while keep < min(len(current), len(TARGET)) and current[keep] == TARGET[keep]:
        keep += 1
    if held is not None:
        if keep == len(current) and len(current) < len(TARGET) and held == TARGET[len(current)]:
            go(SLOT)
            steps.append(_step("place", part=held, slot=SLOT, level=LEVELS[len(current)]))
            current.append(held)
            keep += 1
        else:
            go("RETURN")
            steps.append(_step("place", part=held, slot="RETURN"))
    for part in reversed(current[keep:]):
        go(SLOT)
        steps.append(_step("pick", part=part, source=SLOT))
        go("RETURN")
        steps.append(_step("place", part=part, slot="RETURN"))
    for index, part in enumerate(TARGET[keep:], start=keep):
        source = next((name for name, parts in state["bins"].items() if part in parts), None)
        if source is None:
            return {"refuse": f"{part} is in none of the bins"}
        go(source)
        steps.append(_step("pick", part=part, source=source))
        go(SLOT)
        steps.append(_step("place", part=part, slot=SLOT, level=LEVELS[index]))
    go("HOME")
    return {"plan": steps, "target": target_tray(state)}


def scripted_planner(*first_answers):
    """A planner that gives some fixed answers first, then plans from the cell state on every call."""
    answers = list(first_answers)

    def planner(order, state, capability, history):
        answer = answers.pop(0) if answers else plan_from_state(state)
        return json.dumps(answer)

    return planner


# Output

def _call(function, args):
    return f"{function}(" + ", ".join(f"{key}={value}" for key, value in args.items()) + ")"


def tray_view(state, title):
    """A small text view of the tray, the return position, the gripper and the arm."""
    lines = [title, f"  {'Slot':<8}{'base':<16}{'top':<16}"]
    for slot, parts in state["slots"].items():
        base = parts[0] if parts else "-"
        top = parts[1] if len(parts) > 1 else "-"
        lines.append(f"  {slot:<8}{base:<16}{top:<16}")
    lines.append(f"  RETURN  {', '.join(state['return']) or '-'}")
    lines.append(f"  Gripper {state['gripper'] or 'empty'}, arm at {state['arm']}")
    return "\n".join(lines)


def _count(number, word):
    return f"{number} {word}" if number == 1 else f"{number} {word}s"


def _planner_line(record):
    try:
        answer = json.loads(record["raw"])
    except (TypeError, ValueError):
        answer = None
    if not isinstance(answer, dict):
        what = "an answer that is not a JSON object"
    elif "plan" in answer and isinstance(answer["plan"], list):
        what = f"a plan of {_count(len(answer['plan']), 'step')}" if answer["plan"] else "an empty plan, order complete"
    elif "ask" in answer:
        what = f"a question: {answer['ask']}"
    elif "refuse" in answer:
        what = f"a refusal: {answer['refuse']}"
    else:
        what = "an answer without plan, ask or refuse"
    return f"Planner call {record['call']}: {what}"


def _sentence(text):
    return text[:1].upper() + text[1:]


def describe(record):
    """Turn one run log record into one or two lines for the screen."""
    kind = record["event"]
    if kind == "run_start":
        return (f"Order {record['order_id']}, {record['variant']}, protected {', '.join(record['protected'])}, "
                f"step budget {record['step_budget']}")
    if kind == "planner_response":
        return _planner_line(record)
    if kind == "check_result":
        if record["verdict"] == "run":
            return f"  Checker: RUN. {record['reason']}."
        where = f" at step {record['step']}" if record["step"] else ""
        return f"  Checker: REJECT{where}, code {record['code']}. {record['reason']}."
    if kind == "step_result":
        return f"    step {record['step']:>2}  {_call(record['function'], record['args']):<50} {record['status']}"
    if kind == "feedback":
        if record["kind"] == "injected failure":
            return "    ! Injected: " + injected_text(record)
        return f"    ! Failure sent back to the planner: {record['message']}"
    if kind == "intervention":
        return f"  Operator asked ({record['kind']}): {record['question']}\n  Operator answer: {record['answer']}"
    if kind == "run_end":
        return (f"Result: {record['outcome'].upper()}. {_sentence(record['reason'])}. "
                f"{_count(record['steps_run'], 'step')}, {_count(record['planner_calls'], 'planner call')}, "
                f"{_count(record['interventions'], 'operator question')}.")
    if kind == "provider_limit":
        return f"Provider limit: {record['reason']}"
    return f"{kind}: {record}"


def injected_text(record):
    """One line for an injected failure, for each kind of the cell (FR11)."""
    details = record.get("details") or {}
    if record.get("failure") == "pick_failure":
        times = details.get("times", 1)
        which = "the next pick fails" if times == 1 else f"the next {times} picks fail"
        return f"{which}: the gripper closes but gets no hold on the part"
    if record.get("failure") == "drop_part":
        part = details.get("part", "the held part")
        where = details.get("destination", "its bin")
        return f"{part} slips out of the gripper after the lift and falls back into {where}"
    return (f"{details.get('part')} moved from {details.get('source')} to {details.get('destination')} "
            "after planning")


def render(records):
    """The lines for one run. A planner call and a passed check share one line, so the closed loop stays short."""
    lines = []
    index = 0
    while index < len(records):
        record = records[index]
        following = records[index + 1] if index + 1 < len(records) else None
        if (record["event"] == "planner_response" and following and following["event"] == "check_result"
                and following["verdict"] == "run"):
            empty = "empty plan" in _planner_line(record)
            lines.append(_planner_line(record) + ("" if empty else ", checker: RUN"))
            index += 2
            continue
        lines.append(describe(record))
        index += 1
    return lines


def interesting_record(records):
    """A record worth showing: a failed step, else a rejection, else the first check."""
    for test in (lambda r: r["event"] == "step_result" and r["status"] != "success",
                 lambda r: r["event"] == "check_result" and r["verdict"] == "reject",
                 lambda r: r["event"] == "check_result"):
        found = next((record for record in records if test(record)), None)
        if found:
            return found
    return records[-1]


# Scenarios

def _run(log_dir, name, variant, planner, state, out, **options):
    capability = demo_capability()
    start = copy.deepcopy(state)
    cell = SimulatedCell(capability, state)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log = RunLog(f"demo-{name}-{variant.replace(' ', '-')}-{stamp}", folder=log_dir)
    summary = run_order(ORDER, variant, planner=planner, cell=cell, operator=ScriptedOperator(), log=log,
                        protected=PROTECTED, info={"planner": "scripted, no LLM", "initial_state": start}, **options)
    for line in render(log.records):
        out(line)
    return summary, log


def scenario_1(log_dir, out):
    out("Scenario 1: the kit change of Chapter 13, open loop")
    out(textwrap.fill(f"Order: {ORDER['text']}", WIDTH, subsequent_indent="       "))
    capability = demo_capability()
    state = chapter_13_state(capability)
    out(tray_view(state, "Tray before:"))
    out("")
    expected = plan_from_state(state)["plan"]
    summary, log = _run(log_dir, "1", "open loop", scripted_planner(), state, out, expected_plan=expected)
    out("")
    out(tray_view(summary["final_state"], "Tray after:"))
    return [(summary, log)]


def scenario_2(log_dir, out):
    out("Scenario 2: rejected plans, repaired, closed loop")
    out("A bolt lies on top of the short spacer in slot 2 (Chapter 13, last variation).")
    capability = demo_capability()
    state = chapter_13_state(capability, part_on_top="BOLT")
    out(tray_view(state, "Tray before:"))
    out("")
    # Both wrong plans still name the right target tray, so the checker rejects their steps (DD25).
    touches_slot_1 = {"plan": [_step("move_to", position="SLOT_1"),
                               _step("pick", part="SPACER_BLUE", source="SLOT_1")], "target": target_tray(state)}
    ignores_the_bolt = {"plan": [_step("move_to", position="SLOT_2"),
                                 _step("pick", part="SPACER_SHORT", source="SLOT_2")], "target": target_tray(state)}
    planner = scripted_planner(touches_slot_1, ignores_the_bolt)
    summary, log = _run(log_dir, "2", "closed loop", planner, state, out)
    out("")
    out(tray_view(summary["final_state"], "Tray after:"))
    return [(summary, log)]


def scenario_3(log_dir, out, pause):
    out("Scenario 3: a part is moved after planning")
    out("Before step 6 someone moves the long spacer from BIN_3 to BIN_1.")
    capability = demo_capability()
    move = {6: ("move_part", {"part": "SPACER_LONG", "source": "BIN_3", "destination": "BIN_1"})}
    expected = plan_from_state(chapter_13_state(capability))["plan"]
    results = []
    for variant in ("open loop", "closed loop"):
        out("")
        out(f"--- {variant} ---")
        summary, log = _run(log_dir, "3", variant, scripted_planner(), chapter_13_state(capability), out,
                            expected_plan=expected, failures=move)
        out(tray_view(summary["final_state"], "Tray after:"))
        results.append((summary, log))
        if variant == "open loop":
            pause()
    return results


def _step_of(plan, function, part=None, after=None):
    """The step number (from 1) of the first step with this function, and part if given, after step `after`."""
    for number, step in enumerate(plan, start=1):
        if number > (after or 0) and step["function"] == function and step["args"].get("part", part) == part:
            return number
    raise ValueError(f"no {function} step in the plan")


def _both_loops(log_dir, name, failures, out, pause):
    capability = demo_capability()
    expected = plan_from_state(chapter_13_state(capability))["plan"]
    results = []
    for variant in ("open loop", "closed loop"):
        out("")
        out(f"--- {variant} ---")
        summary, log = _run(log_dir, name, variant, scripted_planner(), chapter_13_state(capability), out,
                            expected_plan=expected, failures=failures)
        out(tray_view(summary["final_state"], "Tray after:"))
        results.append((summary, log))
        if variant == "open loop":
            pause()
    return results


def scenario_4(log_dir, out, pause):
    out("Scenario 4: the gripper gets no hold on the long spacer")
    expected = plan_from_state(chapter_13_state(demo_capability()))["plan"]
    step = _step_of(expected, "pick", "SPACER_LONG")
    out(f"The checker allows the plan, but the pick of step {step} fails, as with a part of an awkward shape.")
    out("The open loop stops safely (DD16). The closed loop sends the failure to the planner, which tries again.")
    return _both_loops(log_dir, "4", {step: ("pick_failure", {})}, out, pause)


def scenario_5(log_dir, out, pause):
    out("Scenario 5: the long spacer slips out of the gripper after the lift")
    expected = plan_from_state(chapter_13_state(demo_capability()))["plan"]
    step = _step_of(expected, "move_to", after=_step_of(expected, "pick", "SPACER_LONG"))
    out(f"Before step {step}, the move to the tray, the spacer falls back into BIN_3, as a heavy part might.")
    out("The open loop places with an empty gripper, which fails, and stops. The closed loop sees the empty")
    out("gripper in the new state and fetches the spacer again.")
    drop = {step: ("drop_part", {"part": "SPACER_LONG", "destination": "BIN_3"})}
    return _both_loops(log_dir, "5", drop, out, pause)


# Live mode with the real model

class LiveLog(RunLog):
    """A run log that also prints every event the moment it happens, so the screen is never blank."""

    def __init__(self, run_id, folder, out):
        super().__init__(run_id, folder=folder)
        self._out = out

    def event(self, kind, /, **fields):
        record = super().event(kind, **fields)
        if kind == "planner_response":
            self._out(_planner_line(record))
            self._out(raw_view(record["raw"], full=record["call"] == 1))
        else:
            self._out(describe(record))
        return record


def raw_view(raw, full):
    """The raw answer of the model: in full for the first call, on one short line after that."""
    try:
        text = json.dumps(json.loads(raw), indent=2) if full else json.dumps(json.loads(raw))
    except (TypeError, ValueError):
        text = str(raw)
    if not full and len(text) > WIDTH + 40:
        text = text[: WIDTH + 37] + "..."
    return textwrap.indent(f"Raw answer: {text}" if not full else f"Raw answer:\n{text}", "  ")


def paced(planner, delay, out, sleep):
    """Wait between model calls, and wait once or twice when Groq asks for a short pause.

    Demo only (proposal): Study 2 repeats the whole run after a provider limit instead (DD21).
    """
    calls = {"n": 0}

    def plan(*args):
        if calls["n"] and delay:
            sleep(delay)
        calls["n"] += 1
        for attempt in range(3):
            try:
                return planner(*args)
            except planner_module.ProviderLimit as error:
                if attempt < 2 and error.retry_after is not None and error.retry_after <= 30:
                    out(f"  Groq asked to wait {error.retry_after:.0f} seconds (per-minute limit). Waiting.")
                    sleep(error.retry_after + 1)
                    continue
                raise

    return plan


def live_demo(args, out, read, sleep):
    settings = planner_module.settings_for(args.local, args.model)
    model = settings["model"]
    variant = "open loop" if args.variant == "open" else "closed loop"
    out(f"Live mode: the order of Chapter 13 with {model} on {planner_module.provider_name(settings)}, {variant}.")
    out("Planner: real language model. Cell, checker, loop and run log: real code.")
    out("This runs on this computer and needs no API key." if args.local else "This uses the Groq free-tier limit.")
    out(textwrap.fill(f"Order: {ORDER['text']}", WIDTH, subsequent_indent="       "))
    capability = demo_capability()
    state = chapter_13_state(capability)

    def fall_back(reason):
        out("")
        out(f"The live model could not be used: {reason}")
        if not args.no_pause:
            answer = read("Run the scripted version of the same order instead? [Y/n] ").strip().lower()
            if answer.startswith("n"):
                return []
        out("Scripted version of the same order, closed loop. " + PLANNER_NOTE)
        expected = plan_from_state(chapter_13_state(capability))["plan"]
        summary, log = _run(args.log_dir, "live-fallback", "closed loop", scripted_planner(),
                            chapter_13_state(capability), out, expected_plan=expected)
        out(tray_view(summary["final_state"], "Tray after:"))
        return [(summary, log)]

    try:
        planner_module.check_access(settings)
    except planner_module.ModelAccessError as error:
        return fall_back(str(error))
    out(tray_view(state, "Tray before:"))
    out("")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log = LiveLog(f"demo-live-{variant.replace(' ', '-')}-{stamp}", args.log_dir, out)
    operator = ScriptedOperator() if args.no_pause else TerminalOperator(read=read, write=out)
    info = {"planner": "llm", "initial_state": copy.deepcopy(state),
            "model": model, "provider": settings["provider"], "prompt_version": planner_module.PROMPT_VERSION,
            "settings": {key: value for key, value in settings.items() if key != "base_url"}}
    delay = args.delay if args.delay is not None else (0 if args.local else 2.5)
    try:
        summary = run_order(ORDER, variant, planner=paced(planner_module.llm_planner(settings), delay, out, sleep),
                            cell=SimulatedCell(capability, state), operator=operator, log=log, protected=PROTECTED,
                            expected_plan=plan_from_state(state)["plan"], info=info)
    except planner_module.ModelError as error:
        return fall_back(f"{type(error).__name__}: {error}")
    out("")
    out(tray_view(summary["final_state"], "Tray after:"))
    return [(summary, log)]


def main(argv=None, out=print, read=input, sleep=time.sleep, show=webbrowser.open):
    parser = argparse.ArgumentParser(description="Gate A demo: the cell, checker and loop with a scripted planner")
    parser.add_argument("--no-pause", action="store_true", help="run without the press Enter pauses")
    parser.add_argument("--scenario", type=int, choices=(1, 2, 3, 4, 5), help="run only this scenario")
    parser.add_argument("--log-dir", default=str(ROOT / "demo_logs"), help="folder for the run logs")
    parser.add_argument("--live", action="store_true", help="run the order once with the real model on Groq")
    parser.add_argument("--variant", choices=("closed", "open"), default="closed", help="loop for --live")
    parser.add_argument("--model", help="model ID for --live, by default the one in planner.DEFAULT_SETTINGS "
                        "(or LOCAL_SETTINGS with --local)")
    parser.add_argument("--local", action="store_true",
                        help="with --live, use a local model through Ollama instead of Groq (no key needed)")
    parser.add_argument("--delay", type=float, help="seconds between model calls with --live (2.5 on Groq, 0 local)")
    parser.add_argument("--view", action="store_true", help="open the 3D and 2D replay of the last run")
    args = parser.parse_args(argv)

    def pause():
        if not args.no_pause:
            read("\n[press Enter to continue]")

    def banner(text):
        out("")
        out("=" * WIDTH)
        out(text)
        out("=" * WIDTH)

    banner("SSM3 kitting cell, Gate A demo")
    if args.live:
        results = live_demo(args, out, read, sleep)
        if not results:
            return results
    else:
        out(PLANNER_NOTE)
        out("No language model and no API calls are used in this demo.")
        scenarios = {1: lambda: scenario_1(args.log_dir, out),
                     2: lambda: scenario_2(args.log_dir, out),
                     3: lambda: scenario_3(args.log_dir, out, pause),
                     4: lambda: scenario_4(args.log_dir, out, pause),
                     5: lambda: scenario_5(args.log_dir, out, pause)}
        chosen = [args.scenario] if args.scenario else [1, 2, 3, 4, 5]
        results = []
        for number in chosen:
            pause()
            out("")
            out("=" * WIDTH)
            results += scenarios[number]()
    last_log = results[-1][1]
    out("")
    out("=" * WIDTH)
    out(f"Run logs (one JSON record per event) are in: {Path(args.log_dir).resolve()}")
    out(f"Last log: {last_log.path}")
    pages = [viewer.write_html(log.path) for _, log in results]
    out(f"Replay of the last run in 3D and 2D (open it in a browser): {pages[-1]}")
    out("One record from it:")
    out(json.dumps(interesting_record(last_log.records), indent=2))
    if args.view:
        show(pages[-1].resolve().as_uri())
    return results


if __name__ == "__main__":
    main()
