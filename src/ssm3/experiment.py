"""Experiment runner: the same task with the baseline, the open loop and the closed loop (Design Document, Ch. 8, 11).

The evaluator can only compare approaches when their logs exist for the same task. This runner makes them.
It takes the task of the task set (K-17 by default, with the start tray of Chapter 13), and for every approach
and every case it runs the task several times through the same cell, checker, loop and run log:

- baseline: no language model. plan_from_layout writes the plan from the structured order (target and protected
  slots of the task, DD23) and the plan passes the same checker (DD4). It runs like the open loop (Chapter 11).
- open loop and closed loop: the real model on Groq (or on Ollama with --local), as in demo.py --live (DD17).

The cases are a clean run and a run with a pick failure at the first pick, so the recovery measure has something
to measure (FR11). The repetitions default to 5 per approach and case (Chapter 8). A run that hits a provider
limit is repeated at most three times and is then listed as not run (DD21). Runs that cannot reach the model
(no key) are skipped with the reason, and the baseline still runs.

The logs are written as demo-exp-*.jsonl in the log folder, so scripts\\evaluate.py reads them with the rest.
The runner ends by printing the three tables of the evaluator for the runs it made, one set per case, because a
run with an injected failure would otherwise lower the task success of the approaches that cannot recover.
Pilot runs are exploratory (DD22), so report them under their condition. Uses the Groq free-tier limit, needs
GROQ_API_KEY for the language model, and is never run by the tests:

    .venv\\Scripts\\python scripts\\experiment.py
    .venv\\Scripts\\python scripts\\experiment.py --no-llm --reps 1
"""

import argparse
import copy
import json
import time
from datetime import datetime
from pathlib import Path

from ssm3 import planner as planner_module
from ssm3.baseline import plan_from_layout
from ssm3.cell import SimulatedCell
from ssm3.console import ScriptedOperator
from ssm3.demo import ROOT, chapter_13_state, demo_capability, paced, plan_from_state
from ssm3.evaluator import DEFAULT_TASK_SET, compute_measures, format_table, load_task_set
from ssm3.logger import RunLog
from ssm3.orchestrator import run_order, run_with_provider_repeats

APPROACHES = ("baseline", "open loop", "closed loop")
CASES = {"clean": (), "pick failure": ("pick_failure",)}
REPETITIONS = 5
DELAY = 2.5


def baseline_planner(task):
    """The non-LLM planner: the layout comparison of baseline.py on the structured order of the task."""

    def plan(order_text, state, capability, history):
        return json.dumps(plan_from_layout(task, state, capability))

    return plan


def _slug(text):
    return text.replace(" ", "-")


def run_once(task, approach, case, rep, *, log_dir, planner, info, attempts, made):
    """One run of the task from the start tray of Chapter 13. Its log goes into `made` before it runs."""
    capability = demo_capability()
    state = chapter_13_state(capability)
    start = copy.deepcopy(state)
    attempts[0] += 1
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"demo-exp-{_slug(approach)}-{_slug(case)}-r{rep}-a{attempts[0]}-{stamp}"
    log = RunLog(name, folder=log_dir)
    made.append(log)
    return run_order({"order_id": task["order_id"], "text": task["text"]}, approach, planner=planner,
                     cell=SimulatedCell(capability, state), operator=ScriptedOperator(), log=log,
                     protected=task["protected"], expected_plan=plan_from_state(start)["plan"],
                     faults=CASES[case], info={**info, "initial_state": start})


def _info(approach, settings):
    if approach == "baseline":
        return {"planner": "baseline"}
    return {"planner": "llm", "model": settings["model"], "provider": settings["provider"],
            "prompt_version": planner_module.PROMPT_VERSION,
            "settings": {key: value for key, value in settings.items() if key != "base_url"}}


def run_experiment(task, *, log_dir, reps, out, sleep, llm=True, local=False, model=None, delay=DELAY):
    """Run every approach and case `reps` times. Returns the logs of all attempts per case, in the order they ran."""
    settings = planner_module.settings_for(local, model)
    approaches = list(APPROACHES)
    if llm:
        try:
            planner_module.check_access(settings)
        except planner_module.ModelAccessError as error:
            out(f"The language model cannot be used, so only the baseline runs: {error}")
            llm = False
    if not llm:
        approaches = ["baseline"]
    logs = {case: [] for case in CASES}
    for approach in approaches:
        for case in CASES:
            for rep in range(1, reps + 1):
                attempts = [0]
                made = []

                def attempt(approach=approach, case=case, rep=rep, attempts=attempts, made=made):
                    base = (baseline_planner(task) if approach == "baseline"
                            else paced(planner_module.llm_planner(settings), delay, out, sleep))
                    return run_once(task, approach, case, rep, log_dir=log_dir, planner=base,
                                    info=_info(approach, settings), attempts=attempts, made=made)

                label = f"{approach} / {case} / run {rep}"
                try:
                    result = run_with_provider_repeats(attempt)
                except planner_module.ModelError as error:
                    out(f"{label}: not run ({type(error).__name__}: {error})")
                    continue
                finally:
                    logs[case] += made
                if result["status"] == "done":
                    summary = result["result"]
                    out(f"{label}: {summary['outcome']}, {summary['steps_run']} steps")
                else:
                    out(f"{label}: not run, provider limit after {result['attempts']} attempts")
    return logs


def main(argv=None, out=print, sleep=time.sleep):
    parser = argparse.ArgumentParser(description="Run one task with the baseline, open loop and closed loop, "
                                                 "then print the evaluator tables")
    parser.add_argument("--tasks", default=str(DEFAULT_TASK_SET), help="JSON task set")
    parser.add_argument("--task", default="K-17", help="order ID of the task, which needs the start tray of "
                                                      "Chapter 13 (only K-17 has one)")
    parser.add_argument("--reps", type=int, default=REPETITIONS, help="runs per approach and case (5, Chapter 8)")
    parser.add_argument("--no-llm", action="store_true", help="run the baseline only, no model call")
    parser.add_argument("--local", action="store_true", help="use a local model through Ollama instead of Groq")
    parser.add_argument("--model", help="model ID, by default the one in planner.DEFAULT_SETTINGS")
    parser.add_argument("--delay", type=float, help="seconds between model calls (2.5 on Groq, 0 local)")
    parser.add_argument("--log-dir", default=str(ROOT / "demo_logs"), help="folder for the run logs")
    parser.add_argument("--json", metavar="FILE", help="also write the evaluator result to this JSON file")
    args = parser.parse_args(argv)
    if args.reps < 1:
        raise SystemExit("--reps must be at least 1")
    try:
        task_set = load_task_set(args.tasks)
    except (OSError, ValueError) as error:
        raise SystemExit(f"Cannot read the task set: {error}") from error
    if args.task != "K-17" or args.task not in task_set:
        raise SystemExit("Only the task K-17 of the task set can be run: it is the one with a start tray.")
    task = task_set[args.task]
    delay = args.delay if args.delay is not None else (0 if args.local else DELAY)
    out(f"Task {task['order_id']}: {task['text']}")
    logs = run_experiment(task, log_dir=args.log_dir, reps=args.reps, out=out, sleep=sleep, llm=not args.no_llm,
                          local=args.local, model=args.model, delay=delay)
    results = {case: compute_measures(case_logs, task_set) for case, case_logs in logs.items() if case_logs}
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    for case, result in results.items():
        out("")
        out(f"=== Case: {case} ===")
        out(format_table(result))
    out("")
    out(f"Run logs: {Path(args.log_dir).resolve()}. scripts\\evaluate.py reads them with the other demo logs.")
    return results
