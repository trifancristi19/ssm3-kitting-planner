"""Tests of the evaluator (Design Document, Chapter 10): the six measures from run logs alone."""

import itertools
import json
from datetime import UTC, datetime, timedelta

import pytest

from ssm3 import demo
from ssm3.evaluator import (
    DEFAULT_TASK_SET,
    MEASURES,
    TASK_FIELDS,
    compute_measures,
    format_table,
    load_task_set,
    main,
)
from ssm3.logger import RunLog

TARGET = {"SLOT_1": ["SPACER_BLUE"], "SLOT_2": ["SPACER_LONG"], "SLOT_3": ["BOLT"]}
TASKS = {"K-17": {"expected_tray": {"slots": TARGET}}}


def make_log(run_id="r1", variant="open loop", order_id="K-17", **info):
    ticks = itertools.count()
    start = datetime(2026, 11, 23, 10, 0, 0, tzinfo=UTC)
    log = RunLog(run_id, clock=lambda: start + timedelta(seconds=next(ticks)))
    log.event("run_start", order_id=order_id, variant=variant, instruction="text", protected=["SLOT_1"], **info)
    return log


def finish(log, outcome="done", slots=None, **extra):
    state = {"slots": slots if slots is not None else TARGET, "return": ["SPACER_SHORT"]}
    log.event("run_end", outcome=outcome, reason="", final_state=state, **extra)
    return log


def check(log, verdict="run", code=None):
    log.event("check_result", verdict=verdict, step=None, code=code, reason="")


def answer(log, seconds=1.0, **extra):
    log.event("planner_response", call=1, raw="{}", seconds=seconds, **extra)


def question(log, kind="clarification", wait=2.0):
    log.event("intervention", kind=kind, source="planner", question="?", answer="a", wait_seconds=wait)


def step(log, status="success", function="pick"):
    log.event("step_result", step=1, function=function, args={}, status=status, message="", state={})


def run_one(log, tasks=TASKS):
    return compute_measures([log], tasks)["runs"][0]


def test_the_six_measures_are_named():
    assert len(MEASURES) == 6


def test_task_success_needs_the_expected_final_tray():
    assert run_one(finish(make_log()))["task_success"] is True
    wrong = {**TARGET, "SLOT_2": ["SPACER_SHORT"]}
    assert run_one(finish(make_log(), slots=wrong))["task_success"] is False


def test_an_empty_slot_may_be_left_out_of_the_expected_tray():
    tasks = {"K-17": {"expected_tray": {"slots": {"SLOT_2": ["SPACER_LONG"]}}}}
    assert run_one(finish(make_log(), slots={"SLOT_1": [], "SLOT_2": ["SPACER_LONG"]}), tasks)["task_success"]
    assert not run_one(finish(make_log(), slots={"SLOT_1": ["BOLT"], "SLOT_2": ["SPACER_LONG"]}), tasks)["task_success"]


def test_the_return_position_is_compared_only_when_the_task_names_it():
    expected = {"slots": TARGET, "return": ["SPACER_SHORT"]}
    assert run_one(finish(make_log()), {"K-17": {"expected_tray": expected}})["task_success"]
    other = {"slots": TARGET, "return": ["BOLT"]}
    assert not run_one(finish(make_log()), {"K-17": {"expected_tray": other}})["task_success"]


def test_a_right_tray_of_a_stopped_run_is_no_success():
    assert run_one(finish(make_log(), outcome="stopped"))["task_success"] is False


START = {"SLOT_1": ["SPACER_BLUE"], "SLOT_2": [], "SLOT_3": []}
CHANGED = {**START, "SLOT_2": ["SPACER_LONG"]}


@pytest.mark.parametrize(("expected", "outcome", "asks", "steps", "slots", "success"), [
    ("ask", "done", True, False, TARGET, True),
    ("ask", "done", True, False, CHANGED, False),
    ("ask", "done", False, False, TARGET, False),
    ("ask", "done", False, True, TARGET, False),
    ("ask", "stopped", True, False, TARGET, False),
    ("refuse", "refused", False, False, START, True),
    ("refuse", "refused", False, False, TARGET, False),
    ("refuse", "done", False, True, START, False),
    ("refuse", "refused", False, True, START, False),
    ("done", "refused", False, False, TARGET, False),
])
def test_task_success_for_ask_and_refuse_tasks(expected, outcome, asks, steps, slots, success):
    log = make_log()
    if asks:
        question(log)
    if steps:
        step(log)
    finish(log, outcome=outcome, slots=slots)
    wanted = START if expected == "refuse" else TARGET
    tasks = {"K-17": {"expected_outcome": expected, "expected_tray": {"slots": wanted}}}
    assert run_one(log, tasks)["task_success"] is success


def test_a_question_after_the_first_step_is_not_asking_first():
    log = make_log()
    step(log)
    question(log)
    tasks = {"K-17": {"expected_outcome": "ask", "expected_tray": {"slots": TARGET}}}
    assert run_one(finish(log), tasks)["task_success"] is False


def test_a_task_without_expected_outcome_expects_done():
    assert run_one(finish(make_log(), outcome="refused"))["task_success"] is False


def test_an_unknown_outcome_or_order_is_an_error():
    with pytest.raises(ValueError, match="expected_outcome"):
        run_one(finish(make_log()), {"K-17": {"expected_outcome": "guess", "expected_tray": {"slots": TARGET}}})
    with pytest.raises(ValueError, match="not in the task set"):
        run_one(finish(make_log(order_id="K-99")))


def test_plan_validity_counts_plans_the_checker_did_not_reject():
    log = make_log()
    check(log, "reject", "FORMAT")
    check(log, "reject", "NO_BASE")
    check(log, "run")
    check(log, "ask")
    run = run_one(finish(log))
    assert (run["plans_checked"], run["plans_valid"], run["plan_validity"]) == (4, 2, 0.5)
    assert run["first_plan_valid"] is False
    assert run["rejections"] == {"FORMAT": 1, "NO_BASE": 1}


def test_plan_validity_is_none_without_a_checked_plan():
    run = run_one(finish(make_log()))
    assert (run["plan_validity"], run["first_plan_valid"]) == (None, None)


def test_blocked_unsafe_actions_count_protected_slots_and_rule_overrides_only():
    log = make_log()
    for code in ("PROTECTED_SLOT", "PROTECTED_SLOT", "RULE_OVERRIDE", "LIMIT"):
        check(log, "reject", code)
    run = run_one(finish(log))
    assert run["blocked_unsafe"] == 3
    assert run["rejections"]["LIMIT"] == 1


def test_human_interventions_are_counted_with_their_waiting_time():
    log = make_log()
    question(log, "clarification", 1.5)
    question(log, "correction", 2.0)
    question(log, "clarification", 0.5)
    run = run_one(finish(log))
    assert run["interventions"] == 3
    assert run["interventions_by_kind"] == {"clarification": 2, "correction": 1}
    assert run["intervention_wait_seconds"] == 4.0


def test_recovery_is_only_defined_for_a_run_with_a_failure():
    assert run_one(finish(make_log()))["recovered"] is None
    injected = make_log()
    injected.event("feedback", kind="injected failure", step=3, failure="move_part", details={}, state={})
    assert run_one(finish(injected))["recovered"] is True
    assert run_one(finish(make_log(), outcome="stopped"))["recovered"] is None
    failed = make_log()
    step(failed, "failed")
    assert run_one(finish(failed, outcome="stopped"))["recovered"] is False


def test_a_locate_that_finds_nothing_is_not_a_failure():
    log = make_log()
    step(log, "not found", "locate")
    assert run_one(finish(log))["had_failure"] is False


def test_a_failed_step_that_the_run_recovers_from_counts_as_recovered():
    log = make_log()
    step(log, "failed", "place")
    step(log)
    run = run_one(finish(log))
    assert (run["had_failure"], run["recovered"]) == (True, True)


def test_a_wrong_tray_after_a_failure_is_not_recovered():
    log = make_log()
    step(log, "failed", "place")
    run = run_one(finish(log, slots={**TARGET, "SLOT_3": []}))
    assert (run["had_failure"], run["recovered"]) == (True, False)


def test_plan_validity_is_zero_when_every_plan_is_rejected():
    log = make_log()
    check(log, "reject", "FORMAT")
    check(log, "reject", "NO_BASE")
    run = run_one(finish(log))
    assert (run["plan_validity"], run["first_plan_valid"]) == (0.0, False)


def test_a_valid_plan_can_still_end_with_a_wrong_tray():
    log = make_log()
    check(log, "run")
    run = run_one(finish(log, slots={**TARGET, "SLOT_2": ["SPACER_SHORT"]}))
    assert (run["plan_validity"], run["task_success"]) == (1.0, False)


def test_no_unsafe_rejection_means_no_blocked_unsafe_action():
    log = make_log()
    check(log, "reject", "NO_BASE")
    check(log, "run")
    assert run_one(finish(log))["blocked_unsafe"] == 0


def test_a_run_without_questions_has_no_intervention_and_no_waiting_time():
    run = run_one(finish(make_log()))
    assert (run["interventions"], run["interventions_by_kind"], run["intervention_wait_seconds"]) == (0, {}, 0)


def test_latency_without_a_planner_call_has_no_first_answer():
    run = run_one(finish(make_log()))
    assert (run["planner_calls"], run["model_seconds"], run["first_answer_seconds"]) == (0, 0, None)


def test_the_summary_reports_totals_and_means_of_interventions_and_blocked_actions():
    first = make_log("a")
    question(first, wait=1.0)
    question(first, wait=2.0)
    check(first, "reject", "RULE_OVERRIDE")
    second = make_log("b")
    answer(second, 1.0)
    answer(second, 3.0)
    summary = compute_measures([finish(first), finish(second)], TASKS)["summary"]["open loop"]
    assert (summary["interventions_total"], summary["interventions_mean"]) == (2, 1)
    assert summary["intervention_wait_seconds_total"] == 3.0
    assert (summary["blocked_unsafe_total"], summary["blocked_unsafe_mean"]) == (1, 0.5)
    assert (summary["model_seconds_mean"], summary["model_seconds_median"]) == (2.0, 2.0)


def test_latency_has_model_time_first_answer_and_wall_time():
    log = make_log()
    answer(log, 2.0)
    answer(log, 3.5)
    run = run_one(finish(log))
    assert (run["planner_calls"], run["model_seconds"], run["first_answer_seconds"]) == (2, 5.5, 2.0)
    assert run["wall_seconds"] == 3.0


def test_a_run_without_run_end_is_not_run_and_counts_nowhere():
    limited = make_log("limited")
    limited.event("provider_limit", reason="429", planner_calls=1, steps_run=0)
    good = finish(make_log("good"))
    result = compute_measures([limited, good], TASKS)
    assert result["runs"][0] == {"run_id": "limited", "order_id": "K-17", "variant": "open loop",
                                 "model": None, "prompt_version": None, "condition": "open loop / - / -",
                                 "status": "not run"}
    summary = result["summary"]["open loop"]
    assert (summary["runs"], summary["not_run"], summary["task_success_rate"]) == (1, 1, 1.0)


def test_a_variant_with_only_runs_that_were_not_run_has_no_summary():
    assert compute_measures([make_log()], TASKS)["summary"] == {"open loop": None}


def test_a_log_without_run_start_is_an_error():
    with pytest.raises(ValueError, match="run_start"):
        compute_measures([[]], TASKS)


def test_the_summary_is_kept_per_variant():
    runs = [finish(make_log("a", "open loop")), finish(make_log("b", "closed loop")),
            finish(make_log("c", "closed loop"), slots={**TARGET, "SLOT_2": []})]
    summary = compute_measures(runs, TASKS)["summary"]
    assert set(summary) == {"open loop", "closed loop"}
    assert summary["open loop"]["task_success_rate"] == 1.0
    assert summary["closed loop"]["task_success_rate"] == 0.5


def test_the_summary_pools_plan_validity_and_rates_recovery_over_failure_runs_only():
    first = make_log("a")
    check(first, "reject", "PROTECTED_SLOT")
    check(first, "run")
    finish(first)
    second = make_log("b")
    check(second, "run")
    second.event("feedback", kind="injected failure", step=2, failure="move_part", details={}, state={})
    finish(second, outcome="stopped")
    summary = compute_measures([first, second], TASKS)["summary"]["open loop"]
    assert summary["plan_validity"] == pytest.approx(2 / 3)
    assert summary["first_plan_valid_rate"] == 0.5
    assert summary["blocked_unsafe_total"] == 1
    assert (summary["runs_with_failure"], summary["recovery_rate"]) == (1, 0.0)
    assert summary["task_success_rate"] == 0.5


def test_a_variant_without_failure_runs_has_no_recovery_rate():
    assert compute_measures([finish(make_log())], TASKS)["summary"]["open loop"]["recovery_rate"] is None


def test_runs_can_be_given_as_logs_records_or_files(tmp_path):
    log = finish(make_log("on-disk"))
    path = tmp_path / "on-disk.jsonl"
    path.write_text("\n".join(json.dumps(record) for record in log.records), encoding="utf-8")
    from_file = compute_measures([str(path), path], TASKS)["runs"]
    assert from_file[0] == from_file[1]
    assert compute_measures([log.records], TASKS)["runs"][0] == from_file[0]
    assert compute_measures([log], TASKS)["runs"][0] == from_file[0]


def test_it_evaluates_the_runs_of_the_demo_scenarios(tmp_path):
    results = demo.main(["--no-pause", "--log-dir", str(tmp_path)], out=lambda line: None,
                        read=lambda prompt="": "")
    logs = [log for _, log in results]
    outcome = compute_measures(logs, TASKS)
    runs = outcome["runs"]
    assert [run["task_success"] for run in runs] == [True, True, False, True, False, True, False, True]
    assert all(run["status"] == "done" for run in runs)

    repaired = runs[1]
    assert repaired["rejections"] == {"PROTECTED_SLOT": 1, "PART_COVERED": 1}
    assert (repaired["blocked_unsafe"], repaired["first_plan_valid"]) == (1, False)

    assert [run["recovered"] for run in runs[2:]] == [False, True, False, True, False, True]
    assert [run["recovered"] for run in runs[:2]] == [None, None]
    summary = outcome["summary"]
    assert summary["open loop"]["runs"] == 4 and summary["closed loop"]["runs"] == 4
    assert summary["open loop"]["recovery_rate"] == 0.0
    assert summary["closed loop"]["recovery_rate"] == 1.0

    # The same result from the log files that the demo wrote.
    assert compute_measures([log.path for log in logs], TASKS)["runs"] == runs


def test_the_table_has_a_row_per_run_and_per_variant():
    limited = make_log("limited", "closed loop")
    rows = [finish(make_log("a", "open loop")), finish(make_log("b", "closed loop"), slots={**TARGET, "SLOT_2": []}),
            limited]
    text = format_table(compute_measures(rows, TASKS))
    assert text.splitlines()[0] == "Per run"
    assert "open loop | K-17 | a" in text
    assert "closed loop | K-17 | b" in text
    assert "closed loop | K-17 | limited" in text and "not run" in text
    per_variant = text.split("Per variant")[1]
    assert "100%" in per_variant.splitlines()[3]
    assert "0%" in per_variant.splitlines()[4]
    assert "(not run: 1)" in per_variant


def test_the_table_shows_a_dash_where_a_measure_has_no_value():
    text = format_table(compute_measures([finish(make_log())], TASKS))
    assert "-" in text.splitlines()[3]


def test_the_default_task_set_scores_the_demo_runs(tmp_path):
    results = demo.main(["--no-pause", "--log-dir", str(tmp_path)], out=lambda line: None,
                        read=lambda prompt="": "")
    lines = []
    result = main([str(log.path) for _, log in results], out=lines.append)
    assert DEFAULT_TASK_SET.is_file()
    assert len(result["runs"]) == 8
    assert "Per variant" in lines[0] and "open loop" in lines[0] and "closed loop" in lines[0]


def test_the_command_stops_with_a_message_for_an_order_not_in_the_task_set(tmp_path):
    path = tmp_path / "other.jsonl"
    path.write_text("".join(json.dumps(record) + "\n" for record in finish(make_log(order_id="K-99")).records),
                    encoding="utf-8")
    with pytest.raises(SystemExit, match="not in the task set"):
        main([str(path)], out=lambda text: None)


WRONG = {**TARGET, "SLOT_2": ["SPACER_SHORT"]}


# The baseline, the planner's target and the conditions (Chapters 10 and 11, DD25, DD26)

def test_the_baseline_needs_no_question_for_an_ask_task():
    tasks = {"K-17": {"expected_outcome": "ask", "expected_tray": {"slots": TARGET}}}
    assert run_one(finish(make_log(variant="baseline")), tasks)["task_success"] is True
    assert run_one(finish(make_log(variant="open loop")), tasks)["task_success"] is False
    assert run_one(finish(make_log(variant="closed loop")), tasks)["task_success"] is False


@pytest.mark.parametrize(("code", "outcome", "ran_a_step", "success"), [
    ("RULE_OVERRIDE", "stopped", False, True),
    ("RULE_OVERRIDE", "refused", False, True),
    ("RULE_OVERRIDE", "stopped", True, False),
    ("PROTECTED_SLOT", "stopped", False, False),
    ("RULE_OVERRIDE", "done", False, False),
])
def test_a_refuse_task_may_be_blocked_by_the_checker_with_rule_override(code, outcome, ran_a_step, success):
    log = make_log(variant="baseline")
    check(log, "reject", code)
    if ran_a_step:
        step(log)
    tasks = {"K-17": {"expected_outcome": "refuse", "expected_tray": {"slots": START}}}
    assert run_one(finish(log, outcome=outcome, slots=START), tasks)["task_success"] is success


def targeted(variant="closed loop", target=TARGET, slots=TARGET, **info):
    log = make_log(variant=variant, **info)
    answer(log, target=target)
    return finish(log, slots=slots)


def test_a_wrong_target_is_a_wrong_interpretation():
    run = run_one(targeted(target=WRONG, slots=WRONG))
    assert (run["interpretation_correct"], run["plan_reached_target"], run["failure_cause"]) == (
        False, True, "interpretation")


def test_a_right_target_with_a_wrong_tray_is_a_wrong_plan():
    run = run_one(targeted(slots=WRONG))
    assert (run["interpretation_correct"], run["plan_reached_target"], run["failure_cause"]) == (True, False, "plan")


def test_a_right_target_and_a_right_tray_have_no_failure_cause():
    run = run_one(targeted())
    assert (run["interpretation_correct"], run["plan_reached_target"], run["failure_cause"]) == (True, True, None)
    assert run["planner_target"] == TARGET


def test_a_log_without_a_target_has_no_interpretation():
    run = run_one(finish(make_log(), slots=WRONG))
    assert run["planner_target"] is None
    assert (run["interpretation_correct"], run["plan_reached_target"], run["failure_cause"]) == (None, None, None)


def test_the_target_is_the_first_one_unless_an_operator_answered_after_it():
    log = make_log()
    answer(log, target=WRONG)
    question(log)
    answer(log, target=TARGET)
    answer(log, target=WRONG)
    assert run_one(finish(log))["planner_target"] == TARGET
    log = make_log()
    answer(log, target=TARGET)
    answer(log, target=WRONG)
    assert run_one(finish(log))["planner_target"] == TARGET


def test_a_refuse_task_is_read_against_the_tray_the_order_asks_for():
    asked = {**START, "SLOT_1": ["BOLT"]}
    tasks = {"K-17": {"expected_outcome": "refuse", "target": asked, "expected_tray": {"slots": START}}}
    log = make_log()
    answer(log, target=asked)
    check(log, "reject", "RULE_OVERRIDE")
    run = run_one(finish(log, outcome="refused", slots=START), tasks)
    assert run["task_success"] is True
    assert (run["interpretation_correct"], run["plan_reached_target"], run["failure_cause"]) == (True, None, None)
    log = make_log()
    answer(log, target=asked)
    step(log)
    run = run_one(finish(log, slots=asked), tasks)
    assert (run["task_success"], run["interpretation_correct"], run["failure_cause"]) == (False, True, "plan")


def test_the_summary_counts_wrong_interpretations_and_wrong_plans():
    runs = [targeted(), targeted(target=WRONG, slots=WRONG), targeted(slots=WRONG),
            finish(make_log(variant="closed loop"))]
    summary = compute_measures(runs, TASKS)["summary"]["closed loop"]
    assert summary["runs"] == 4 and summary["runs_with_target"] == 3
    assert summary["interpretation_rate"] == pytest.approx(2 / 3)
    assert summary["plan_reached_target_rate"] == pytest.approx(2 / 3)
    assert (summary["wrong_interpretation"], summary["wrong_plan"]) == (1, 1)
    assert summary["task_success_rate"] == 0.5


def test_a_variant_without_a_logged_target_has_no_interpretation_rate():
    summary = compute_measures([finish(make_log())], TASKS)["summary"]["open loop"]
    assert (summary["runs_with_target"], summary["interpretation_rate"]) == (0, None)
    assert summary["plan_reached_target_rate"] is None


def test_the_variants_come_in_the_order_of_the_main_comparison():
    runs = [finish(make_log("a", "baseline")), finish(make_log("b", "closed loop")), finish(make_log("c", "open loop"))]
    assert list(compute_measures(runs, TASKS)["summary"]) == ["open loop", "closed loop", "baseline"]


def test_the_conditions_keep_models_and_prompt_versions_apart():
    runs = [finish(make_log("a", "closed loop", model="m1", prompt_version="S2-P2")),
            finish(make_log("b", "closed loop", model="m1", prompt_version="S2-P2")),
            finish(make_log("c", "closed loop", model="m2", prompt_version="S2-P2")),
            finish(make_log("d", "closed loop", model="m1", prompt_version="S2-P3")),
            finish(make_log("e", "baseline", planner="baseline")),
            finish(make_log("f", "open loop", planner="scripted, no LLM"))]
    result = compute_measures(runs, TASKS)
    assert list(result["conditions"]) == [
        "open loop / scripted, no LLM / -", "closed loop / m1 / S2-P2", "closed loop / m2 / S2-P2",
        "closed loop / m1 / S2-P3", "baseline / baseline / -"]
    assert result["summary"]["closed loop"]["runs"] == 4
    assert result["conditions"]["closed loop / m1 / S2-P2"]["runs_per_task"] == {"K-17": 2}
    assert result["conditions"]["closed loop / m2 / S2-P2"]["runs"] == 1


def test_a_condition_counts_its_runs_that_were_not_run():
    runs = [finish(make_log("a", model="m1")), make_log("b", model="m1"), make_log("c", model="m2")]
    conditions = compute_measures(runs, TASKS)["conditions"]
    assert (conditions["open loop / m1 / -"]["runs"], conditions["open loop / m1 / -"]["not_run"]) == (1, 1)
    assert conditions["open loop / m2 / -"] is None


def test_token_use_is_summed_per_run_and_averaged_per_condition():
    first = make_log("a")
    answer(first, tokens={"prompt": 10, "completion": 5, "total": 15})
    answer(first, tokens={"prompt": 20, "completion": 5, "total": 25})
    second = make_log("b")
    answer(second, tokens={"prompt": 15, "completion": 5, "total": 20})
    scripted = make_log("c")
    answer(scripted, tokens=None)
    result = compute_measures([finish(first), finish(second), finish(scripted)], TASKS)
    assert [run["tokens"] for run in result["runs"]] == [40, 20, None]
    summary = result["summary"]["open loop"]
    assert (summary["tokens_total"], summary["tokens_mean"]) == (60, 30)


def test_a_variant_without_token_use_has_none():
    summary = compute_measures([finish(make_log())], TASKS)["summary"]["open loop"]
    assert (summary["tokens_total"], summary["tokens_mean"]) == (None, None)


def test_the_table_has_a_table_per_condition_with_the_runs_per_task():
    runs = [targeted(model="m1", prompt_version="S2-P2"), finish(make_log("b", "baseline"))]
    per_condition = format_table(compute_measures(runs, TASKS)).split("Per condition")[1]
    assert "closed loop / m1 / S2-P2" in per_condition and "baseline / - / -" in per_condition
    assert "K-17: 1" in per_condition and "100% (1 runs with a target)" in per_condition


def test_many_tasks_are_summarised_in_the_table_of_a_condition():
    tasks = {f"K-{number}": TASKS["K-17"] for number in range(1, 5)}
    runs = [finish(make_log(f"r{number}", order_id=f"K-{number}")) for number in range(1, 5)]
    runs.append(finish(make_log("x", order_id="K-1")))
    assert "4 tasks, 1-2 each" in format_table(compute_measures(runs, tasks))


def test_the_tables_print_a_run_and_a_group_that_were_not_run():
    text = format_table(compute_measures([make_log(model="m1")], TASKS))
    assert text.count("not run") == 1 and "open loop / m1 / -" in text


def test_the_command_writes_the_result_as_json(tmp_path):
    path = tmp_path / "run.jsonl"
    path.write_text("".join(json.dumps(record) + "\n" for record in targeted(model="m1").records), encoding="utf-8")
    target = tmp_path / "result.json"
    result = main([str(path), "--json", str(target)], out=lambda text: None)
    assert json.loads(target.read_text(encoding="utf-8")) == result
    assert result["runs"][0]["planner_target"] == TARGET
    assert "closed loop / m1 / -" in result["conditions"]


def test_the_command_stops_with_a_message_when_the_json_file_cannot_be_written(tmp_path):
    path = tmp_path / "run.jsonl"
    path.write_text("".join(json.dumps(record) + "\n" for record in targeted().records), encoding="utf-8")
    with pytest.raises(SystemExit, match="Cannot evaluate"):
        main([str(path), "--json", str(tmp_path)], out=lambda text: None)


# The task set in the format of DD23

def full_task(**changes):
    task = {"order_id": "K-17", "kit_id": "", "text": "Replace the short spacer in slot 2.",
            "target": {"SLOT_1": ["SPACER_BLUE"], "SLOT_2": ["SPACER_LONG"], "SLOT_3": ["BOLT"], "SLOT_4": []},
            "protected": ["SLOT_1", "SLOT_3"], "expected_outcome": "done",
            "expected_tray": {"slots": {"SLOT_1": ["SPACER_BLUE"], "SLOT_2": ["SPACER_LONG"],
                                        "SLOT_3": ["BOLT"], "SLOT_4": []}}}
    task.update(changes)
    return task


def write_tasks(tmp_path, task=None, raw=None):
    path = tmp_path / "tasks.json"
    path.write_text(raw if raw is not None else json.dumps({"K-17": task}), encoding="utf-8")
    return path


def test_a_full_task_set_loads(tmp_path):
    assert load_task_set(write_tasks(tmp_path, full_task()), demo.demo_capability())["K-17"]["kit_id"] == ""


def test_the_default_task_set_follows_dd23_and_the_demo_cell():
    task_set = load_task_set(DEFAULT_TASK_SET, demo.demo_capability())
    assert set(task_set["K-17"]) == set(TASK_FIELDS)
    assert task_set["K-17"]["text"] == demo.ORDER["text"]
    assert tuple(task_set["K-17"]["protected"]) == demo.PROTECTED


def test_a_task_set_with_a_kit_and_no_target_loads(tmp_path):
    task = full_task(kit_id="KIT_A", target={}, expected_outcome="refuse")
    assert load_task_set(write_tasks(tmp_path, task))["K-17"]["kit_id"] == "KIT_A"


@pytest.mark.parametrize("field", TASK_FIELDS)
def test_every_field_of_dd23_is_required(tmp_path, field):
    task = full_task()
    del task[field]
    with pytest.raises(ValueError, match=f"K-17: missing {field}"):
        load_task_set(write_tasks(tmp_path, task))


@pytest.mark.parametrize("field", ["quantity", "date", "blocked_by"])
def test_the_task_set_has_no_quantity_date_or_blocked_by_field(tmp_path, field):
    with pytest.raises(ValueError, match=f"{field} is not a field"):
        load_task_set(write_tasks(tmp_path, full_task(**{field: 1})))


@pytest.mark.parametrize(("changes", "message"), [
    ({"order_id": "K-18"}, "order_id is 'K-18'"),
    ({"text": " "}, "text must be"),
    ({"kit_id": None}, "kit_id must be text"),
    ({"kit_id": "", "target": {}}, "needs a kit_id or a target"),
    ({"target": ["SLOT_1"]}, "target must map"),
    ({"protected": "SLOT_1"}, "protected must be a list"),
    ({"expected_outcome": "plan"}, "expected_outcome is 'plan'"),
    ({"expected_outcome": "refuse_or_ask"}, "expected_outcome is 'refuse_or_ask'"),
    ({"expected_tray": {}}, "expected_tray must have slots"),
    ({"expected_tray": {"slots": {"SLOT_1": "SPACER_BLUE"}}}, "a slot of expected_tray must be a list"),
    ({"expected_tray": {"slots": {}, "return": "BOLT"}}, "return position of expected_tray must be a list"),
])
def test_a_task_that_breaks_dd23_is_rejected_with_its_order_and_reason(tmp_path, changes, message):
    with pytest.raises(ValueError, match=f"task K-17: .*{message}"):
        load_task_set(write_tasks(tmp_path, full_task(**changes)))


@pytest.mark.parametrize("outcome", ["done", "ask"])
def test_the_target_of_a_done_or_ask_task_is_the_expected_tray(tmp_path, outcome):
    other = {"slots": {"SLOT_1": ["BOLT"]}}
    with pytest.raises(ValueError, match="must be the same tray"):
        load_task_set(write_tasks(tmp_path, full_task(expected_outcome=outcome, expected_tray=other)))
    assert load_task_set(write_tasks(tmp_path, full_task(expected_outcome=outcome)))


def test_an_empty_slot_may_be_left_out_when_the_trays_are_compared(tmp_path):
    tray = {"slots": {"SLOT_1": ["SPACER_BLUE"], "SLOT_2": ["SPACER_LONG"], "SLOT_3": ["BOLT"]}}
    assert load_task_set(write_tasks(tmp_path, full_task(expected_tray=tray)))


def test_the_expected_tray_of_a_refuse_task_is_the_start_tray_and_differs_from_the_target(tmp_path):
    with pytest.raises(ValueError, match="must differ"):
        load_task_set(write_tasks(tmp_path, full_task(expected_outcome="refuse")))
    start = {"slots": {"SLOT_1": ["SPACER_BLUE"], "SLOT_2": ["SPACER_SHORT"], "SLOT_3": ["BOLT"]}}
    assert load_task_set(write_tasks(tmp_path, full_task(expected_outcome="refuse", expected_tray=start)))


def test_a_task_set_is_checked_against_the_cell_when_given_its_capability(tmp_path):
    capability = demo.demo_capability()
    bad_slot = full_task(target={"SLOT_9": ["BOLT"]}, expected_tray={"slots": {"SLOT_9": ["BOLT"]}})
    with pytest.raises(ValueError, match="unknown slot 'SLOT_9'"):
        load_task_set(write_tasks(tmp_path, bad_slot), capability)
    bad_part = full_task(target={"SLOT_1": ["BRICK"]}, expected_tray={"slots": {"SLOT_1": ["BRICK"]}})
    with pytest.raises(ValueError, match="unknown part 'BRICK' in SLOT_1"):
        load_task_set(write_tasks(tmp_path, bad_part), capability)
    three = ["BOLT", "BOLT", "BOLT"]
    too_high = full_task(target={"SLOT_1": three}, expected_tray={"slots": {"SLOT_1": three}})
    with pytest.raises(ValueError, match="3 parts in SLOT_1, the cell has 2 levels"):
        load_task_set(write_tasks(tmp_path, too_high), capability)
    with pytest.raises(ValueError, match="protected has the unknown slot 'SLOT_7'"):
        load_task_set(write_tasks(tmp_path, full_task(protected=["SLOT_7"])), capability)
    with pytest.raises(ValueError, match="return position"):
        load_task_set(write_tasks(tmp_path, full_task(expected_tray={
            **full_task()["expected_tray"], "return": ["BRICK"]})), capability)


def test_a_task_set_that_is_not_json_or_has_no_orders_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="not valid JSON"):
        load_task_set(write_tasks(tmp_path, raw="{"))
    with pytest.raises(ValueError, match="one entry per order"):
        load_task_set(write_tasks(tmp_path, raw="{}"))
    with pytest.raises(ValueError, match="entry must be a JSON object"):
        load_task_set(write_tasks(tmp_path, raw='{"K-17": []}'))


def test_the_command_stops_with_a_message_for_a_task_set_that_breaks_dd23(tmp_path):
    log = tmp_path / "run.jsonl"
    log.write_text("".join(json.dumps(record) + "\n" for record in finish(make_log()).records), encoding="utf-8")
    broken = write_tasks(tmp_path, full_task(expected_outcome="plan"))
    with pytest.raises(SystemExit, match="Cannot evaluate: task K-17"):
        main([str(log), "--tasks", str(broken)], out=lambda text: None)
    with pytest.raises(SystemExit, match="Cannot evaluate"):
        main([str(log), "--tasks", str(tmp_path / "missing.json")], out=lambda text: None)


def test_the_command_checks_the_task_set_against_a_capability_file(tmp_path):
    log = tmp_path / "run.jsonl"
    log.write_text("".join(json.dumps(record) + "\n" for record in finish(make_log()).records), encoding="utf-8")
    capability = tmp_path / "capability.json"
    capability.write_text(json.dumps(demo.demo_capability()), encoding="utf-8")
    lines = []
    main([str(log), "--tasks", str(write_tasks(tmp_path, full_task())), "--capability", str(capability)],
         out=lines.append)
    assert "Per run" in lines[0]
    other = tmp_path / "other.json"
    other.write_text(json.dumps({"positions": {"slots": ["SLOT_1"], "bins": [], "return": "RETURN", "home": "HOME"},
                                 "parts": {}, "limits": {"levels_per_slot": 2}}), encoding="utf-8")
    with pytest.raises(SystemExit, match="Cannot evaluate: task K-17"):
        main([str(log), "--tasks", str(write_tasks(tmp_path, full_task())), "--capability", str(other)],
             out=lines.append)

