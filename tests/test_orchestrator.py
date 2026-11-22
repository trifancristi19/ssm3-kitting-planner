"""Tests for the orchestrator loop and its run limits (Design Document, Chapter 9, Table 10, DD13 to DD16, DD21).

The planner in these tests is a fake with fixed answers, so no test calls a language model.
"""

import json

import pytest
from target_helper import CHAPTER_13_TARGET, add_target

from ssm3.cell import SimulatedCell
from ssm3.console import NO_FURTHER_INFORMATION, ScriptedOperator
from ssm3.logger import RunLog
from ssm3.orchestrator import (
    PROVIDER_REPEATS,
    REJECTS_BEFORE_ASKING,
    ProviderLimit,
    run_order,
    run_with_provider_repeats,
    step_budget,
)
from ssm3.planner import ModelTimeout


def test_step_budget_is_twice_the_expected_plan(capability, chapter6_plan):
    assert step_budget(capability, chapter6_plan) == 18


def test_step_budget_without_an_expected_plan_is_max_steps(capability):
    assert step_budget(capability) == 40
    assert step_budget(capability, []) == 40


def flaky(failures):
    """A run that hits a provider limit a number of times before it works."""
    calls = {"n": 0}

    def run():
        calls["n"] += 1
        if calls["n"] <= failures:
            raise ProviderLimit("429 rate limit")
        return "run log"

    return run, calls


def test_a_run_without_provider_limits_runs_once():
    run, calls = flaky(0)
    assert run_with_provider_repeats(run) == {"status": "done", "result": "run log", "attempts": 1}
    assert calls["n"] == 1


def test_a_run_is_repeated_at_most_three_times():
    assert PROVIDER_REPEATS == 3
    run, calls = flaky(3)
    assert run_with_provider_repeats(run)["status"] == "done"
    assert calls["n"] == 4


def test_a_run_that_still_hits_the_limit_is_marked_not_run():
    run, calls = flaky(10)
    assert run_with_provider_repeats(run) == {"status": "not run", "result": None, "attempts": 4}
    assert calls["n"] == 4


def test_other_errors_are_not_repeated():
    def broken():
        raise ValueError("planner bug")

    with pytest.raises(ValueError):
        run_with_provider_repeats(broken)


# The loop

ORDER = {"order_id": "K-17", "text": "Replace the short spacer in slot 2 with a long spacer. "
                                     "Put the short spacer in the return position. Leave slots 1 and 3 unchanged."}
PROTECTED = ("SLOT_1", "SLOT_3")

# Places the long spacer on the base of slot 2 while the short spacer is still there: SLOT_OCCUPIED at step 4.
BAD_PLAN = [
    {"function": "move_to", "args": {"position": "BIN_3"}},
    {"function": "pick", "args": {"part": "SPACER_LONG", "source": "BIN_3"}},
    {"function": "move_to", "args": {"position": "SLOT_2"}},
    {"function": "place", "args": {"part": "SPACER_LONG", "slot": "SLOT_2", "level": "base"}},
]


class FakePlanner:
    """Returns fixed answers in order. An answer can also be a function of the history."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.histories = []

    def __call__(self, order, state, capability, history):
        self.histories.append(history)
        answer = self.answers.pop(0)
        answer = answer(history) if callable(answer) else answer
        # Since DD25 a plan also gives the tray it intends. Unless a test sets one, it is the tray the plan builds.
        return add_target(answer, state, capability)


def plan(steps):
    return json.dumps({"plan": steps})


def remaining(steps):
    """A closed-loop answer: the steps that have not succeeded yet."""

    def answer(history):
        done = sum(1 for event in history if event["type"] == "step" and event["status"] == "success")
        return plan(steps[done:])

    return answer


def run(cell, variant, planner, operator=None, **options):
    log = RunLog("test-run")
    operator = operator or ScriptedOperator()
    options.setdefault("protected", PROTECTED)
    summary = run_order(ORDER, variant, planner=planner, cell=cell, operator=operator, log=log, **options)
    return summary, log, operator


def test_open_loop_runs_the_chapter_6_plan(cell, chapter6_plan):
    summary, log, operator = run(cell, "open loop", FakePlanner(plan(chapter6_plan)), expected_plan=chapter6_plan)
    assert summary["outcome"] == "done"
    assert (summary["steps_run"], summary["planner_calls"], summary["interventions"]) == (9, 1, 0)
    final = summary["final_state"]
    assert final["slots"]["SLOT_2"] == ["SPACER_LONG"]
    assert final["return"] == ["SPACER_SHORT"]
    assert final["slots"]["SLOT_1"] == ["SPACER_BLUE"] and final["slots"]["SLOT_3"] == ["BOLT"]
    kinds = [record["event"] for record in log.records]
    assert kinds == ["run_start", "planner_response", "check_result"] + ["step_result"] * 9 + ["run_end"]
    assert operator.messages == []


def test_closed_loop_calls_the_planner_after_every_step(cell, chapter6_plan):
    # Nine steps, then one more call that answers with an empty plan to end the run.
    planner = FakePlanner(*[remaining(chapter6_plan)] * 10)
    summary, log, _ = run(cell, "closed loop", planner, expected_plan=chapter6_plan)
    assert summary["outcome"] == "done"
    assert (summary["steps_run"], summary["planner_calls"]) == (9, 10)
    assert [len(history) for history in planner.histories] == list(range(10))
    assert summary["final_state"]["slots"]["SLOT_2"] == ["SPACER_LONG"]


def test_closed_loop_rejects_a_planner_that_sends_only_the_next_step(cell, chapter6_plan):
    # Since DD26 the planner sends the full remaining plan (team answer of 22 November 2026). A plan of only
    # the next step does not end at the target, so it gets TARGET_MISMATCH and nothing moves.
    def next_step(history):
        done = sum(1 for event in history if event["type"] == "step" and event["status"] == "success")
        return json.dumps({"plan": chapter6_plan[done:done + 1], "target": CHAPTER_13_TARGET})

    planner = FakePlanner(*[next_step] * 4)
    summary, log, _ = run(cell, "closed loop", planner, expected_plan=chapter6_plan)
    assert summary["outcome"] == "stopped" and summary["steps_run"] == 0
    assert {record["code"] for record in log.of_kind("check_result")} == {"TARGET_MISMATCH"}


def test_closed_loop_does_not_end_after_a_successful_step(cell, chapter6_plan):
    planner = FakePlanner(plan(chapter6_plan[:1]), plan([]))
    summary, _, _ = run(cell, "closed loop", planner)
    assert (summary["steps_run"], summary["planner_calls"]) == (1, 2)
    assert summary["reason"] == "the planner returned an empty plan, so the order is complete"


def test_closed_loop_recovers_from_a_failed_pick(cell, chapter6_plan):
    planner = FakePlanner(*[remaining(chapter6_plan)] * 11)
    failures = {2: ("pick_failure", {})}
    summary, log, _ = run(cell, "closed loop", planner, expected_plan=chapter6_plan, failures=failures)
    assert summary["outcome"] == "done"
    assert summary["steps_run"] == 10
    assert [record["status"] for record in log.of_kind("step_result")][:3] == ["success", "failed", "success"]
    assert [record["kind"] for record in log.of_kind("feedback")] == ["injected failure", "failure sent to the planner"]


def test_open_loop_stops_safely_at_a_failed_step(cell, chapter6_plan):
    failures = {2: ("pick_failure", {})}
    summary, log, operator = run(cell, "open loop", FakePlanner(plan(chapter6_plan)), failures=failures)
    assert summary["outcome"] == "stopped"
    assert "not recovered" in summary["reason"]
    assert summary["steps_run"] == 2
    assert summary["final_state"]["slots"]["SLOT_2"] == ["SPACER_SHORT"]
    assert operator.messages and "stopped" in operator.messages[0]


def test_an_injected_failure_logs_the_state_after_it(cell, chapter6_plan):
    failures = {7: ("drop_part", {})}
    summary, log, _ = run(cell, "open loop", FakePlanner(plan(chapter6_plan)), failures=failures)
    [injected] = log.of_kind("feedback")
    assert (injected["failure"], injected["step"]) == ("drop_part", 7)
    assert injected["state"]["gripper"] is None and injected["state"]["bins"]["BIN_3"] == ["SPACER_LONG"]


def test_open_loop_stops_when_the_part_slipped_out_before_the_place(cell, chapter6_plan):
    failures = {7: ("drop_part", {})}
    summary, log, _ = run(cell, "open loop", FakePlanner(plan(chapter6_plan)), failures=failures)
    assert summary["outcome"] == "stopped" and summary["steps_run"] == 8
    last = log.of_kind("step_result")[-1]
    assert (last["function"], last["status"]) == ("place", "blocked")
    assert "gripper is empty" in last["message"]


def test_a_failure_the_cell_cannot_apply_stops_the_run_before_its_step(cell, chapter6_plan):
    # Review of pull request 10: the error used to end the log without a run_end.
    failures = {1: ("drop_part", {})}  # the gripper is still empty before step 1
    summary, log, _ = run(cell, "open loop", FakePlanner(plan(chapter6_plan)), failures=failures)
    assert summary["outcome"] == "stopped" and summary["steps_run"] == 0
    assert "drop_part failure before step 1 could not be applied" in summary["reason"]
    assert log.of_kind("step_result") == [] and log.records[-1]["event"] == "run_end"


def test_a_slip_of_a_part_without_a_bin_stops_the_run(capability, cell):
    # Review of pull request 10: a held part that the capability file does not list has no bin to fall into.
    # The part is known, so the plan may place it, but the capability file gives it no bin (DD26: the plan ends
    # with an empty gripper, so it places the part).
    capability["parts"]["MYSTERY_PART"] = None
    state = cell.state()
    state["gripper"] = "MYSTERY_PART"
    odd = SimulatedCell(capability, state)
    planner = FakePlanner(plan([{"function": "move_to", "args": {"position": "SLOT_4"}},
                                {"function": "place", "args": {"part": "MYSTERY_PART", "slot": "SLOT_4",
                                                               "level": "base"}}]))
    summary, log, _ = run(odd, "open loop", planner, faults=("drop_part",))
    assert summary["outcome"] == "stopped" and summary["steps_run"] == 0
    assert "could not be applied" in summary["reason"]
    assert summary["final_state"]["gripper"] == "MYSTERY_PART"
    assert log.records[-1]["event"] == "run_end"


def test_a_model_timeout_ends_the_run_as_stopped(cell, chapter6_plan):
    # Review of pull request 10: DD14 stops a run safely after a model call of 60 seconds.
    def too_slow(history):
        raise ModelTimeout("no answer within 60 seconds")

    planner = FakePlanner(remaining(chapter6_plan), too_slow)
    summary, log, operator = run(cell, "closed loop", planner, expected_plan=chapter6_plan)
    assert summary["outcome"] == "stopped"
    assert summary["reason"] == "model call 2 timed out: no answer within 60 seconds (DD14)"
    assert (summary["steps_run"], summary["planner_calls"]) == (1, 2)
    assert log.records[-1]["event"] == "run_end" and log.of_kind("provider_limit") == []
    assert operator.messages and "stopped" in operator.messages[0]


def test_a_grip_that_keeps_failing_ends_at_the_step_budget(cell, chapter6_plan):
    planner = FakePlanner(*[remaining(chapter6_plan)] * 40)
    failures = {6: ("pick_failure", {"times": 100})}
    summary, log, _ = run(cell, "closed loop", planner, expected_plan=chapter6_plan, failures=failures)
    assert summary["outcome"] == "stopped"
    # The budget of twice the expected plan limits both the steps and the planner calls (DD14).
    assert summary["reason"] == "18 planner calls without finishing the order"
    assert [r["status"] for r in log.of_kind("step_result")][5:] == ["failed"] * 13


def test_a_question_goes_to_the_operator_and_the_answer_back_to_the_planner(cell, chapter6_plan):
    planner = FakePlanner(json.dumps({"ask": "Which spacer goes in slot 2?"}), plan(chapter6_plan))
    operator = ScriptedOperator(["The long spacer."])
    summary, log, _ = run(cell, "open loop", planner, operator=operator)
    assert summary["outcome"] == "done"
    assert summary["interventions"] == 1
    [intervention] = log.of_kind("intervention")
    assert (intervention["kind"], intervention["source"]) == ("clarification", "planner")
    assert intervention["answer"] == "The long spacer."
    assert "wait_seconds" in intervention
    assert planner.histories[1] == [{"type": "answer", "question": "Which spacer goes in slot 2?",
                                     "answer": "The long spacer."}]


def test_a_refusal_stops_the_run_and_tells_the_operator(cell):
    summary, log, operator = run(cell, "closed loop", FakePlanner(json.dumps({"refuse": "No such part."})))
    assert (summary["outcome"], summary["reason"], summary["steps_run"]) == ("refused", "No such part.", 0)
    assert operator.messages


def test_a_rejected_plan_goes_back_to_the_planner_with_its_reason(cell, chapter6_plan):
    planner = FakePlanner(plan(BAD_PLAN), plan(chapter6_plan))
    summary, log, _ = run(cell, "open loop", planner)
    assert summary["outcome"] == "done"
    [reject] = planner.histories[1]
    assert (reject["type"], reject["step"], reject["code"]) == ("reject", 4, "SLOT_OCCUPIED")


def test_an_answer_that_is_not_json_is_a_format_rejection(cell, chapter6_plan):
    planner = FakePlanner("Sure! First I move the arm.", plan(chapter6_plan))
    summary, log, _ = run(cell, "open loop", planner)
    assert summary["outcome"] == "done"
    assert log.of_kind("check_result")[0]["code"] == "FORMAT"


def test_a_protected_slot_is_never_touched(cell, chapter6_plan):
    touch_slot_1 = [{"function": "move_to", "args": {"position": "SLOT_1"}},
                    {"function": "pick", "args": {"part": "SPACER_BLUE", "source": "SLOT_1"}}]
    # The planner says it keeps slot 1 as it is, but its plan picks from it: PROTECTED_SLOT.
    keeps_slot_1 = json.dumps({"plan": touch_slot_1, "target": cell.state()["slots"]})
    planner = FakePlanner(keeps_slot_1, plan(chapter6_plan))
    summary, log, _ = run(cell, "open loop", planner)
    assert log.of_kind("check_result")[0]["code"] == "PROTECTED_SLOT"
    assert summary["final_state"]["slots"]["SLOT_1"] == ["SPACER_BLUE"]


def test_after_three_rejections_the_operator_is_asked_once(cell, chapter6_plan):
    assert REJECTS_BEFORE_ASKING == 3
    planner = FakePlanner(plan(BAD_PLAN), plan(BAD_PLAN), plan(BAD_PLAN), plan(chapter6_plan))
    operator = ScriptedOperator(["Take the short spacer out first."])
    summary, log, _ = run(cell, "open loop", planner, operator=operator)
    assert summary["outcome"] == "done"
    [intervention] = log.of_kind("intervention")
    assert intervention["kind"] == "correction"
    assert planner.histories[3][-1]["answer"] == "Take the short spacer out first."


def test_a_rejection_after_the_operator_was_asked_stops_the_run(cell):
    planner = FakePlanner(*[plan(BAD_PLAN)] * 4)
    summary, log, operator = run(cell, "closed loop", planner)
    assert summary["outcome"] == "stopped"
    assert (summary["planner_calls"], summary["interventions"], summary["steps_run"]) == (4, 1, 0)
    assert summary["final_state"] == cell.state()
    assert operator.messages


def test_the_step_budget_stops_a_long_run(cell, chapter6_plan):
    summary, log, _ = run(cell, "open loop", FakePlanner(plan(chapter6_plan)), expected_plan=chapter6_plan[:2])
    assert summary["outcome"] == "stopped"
    assert summary["steps_run"] == 4
    assert "budget" in summary["reason"]


def test_a_planner_that_keeps_asking_is_stopped_too(cell, chapter6_plan):
    planner = FakePlanner(*[json.dumps({"ask": "Are you sure?"})] * 20)
    summary, log, operator = run(cell, "closed loop", planner, expected_plan=chapter6_plan[:3])
    assert summary["outcome"] == "stopped"
    assert summary["planner_calls"] == 6
    assert operator.questions == ["Are you sure?"] * 6
    assert all(record["answer"] == NO_FURTHER_INFORMATION for record in log.of_kind("intervention"))


def test_an_empty_plan_means_nothing_is_left_to_do(cell):
    summary, _, _ = run(cell, "open loop", FakePlanner(plan([])))
    assert (summary["outcome"], summary["steps_run"]) == ("done", 0)


def test_locate_not_found_is_not_a_failed_step(cell):
    look = [{"function": "locate", "args": {"part": "BOLT"}},
            {"function": "locate", "args": {"part": "SPACER_SHORT"}}]
    state = cell.state()
    state["slots"]["SLOT_3"] = []
    summary, log, _ = run(SimulatedCell(cell.capability, state), "open loop", FakePlanner(plan(look)))
    assert summary["outcome"] == "done"
    assert [record["status"] for record in log.of_kind("step_result")] == ["not found", "success"]


def test_run_start_records_the_model_settings_and_prompt_version(cell, chapter6_plan):
    info = {"model": "openai/gpt-oss-120b", "settings": {"temperature": 0}, "prompt_version": "S2-P1"}
    _, log, _ = run(cell, "open loop", FakePlanner(plan(chapter6_plan)), info=info)
    start = log.of_kind("run_start")[0]
    assert start["model"] == "openai/gpt-oss-120b"
    assert start["prompt_version"] == "S2-P1"
    assert start["protected"] == list(PROTECTED)


def test_an_unknown_variant_is_an_error(cell):
    with pytest.raises(ValueError):
        run(cell, "half loop", FakePlanner())


def test_a_provider_limit_repeats_the_whole_run_from_a_fresh_cell(cell, chapter6_plan):
    calls = {"n": 0}

    def planner(order, state, capability, history):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ProviderLimit("429 rate limit")
        return add_target(plan(chapter6_plan), state, capability)

    logs = []

    def one_run():
        fresh = SimulatedCell(cell.capability, cell.state())
        logs.append(RunLog(f"K-17-attempt-{len(logs) + 1}"))
        return run_order(ORDER, "open loop", planner=planner, cell=fresh, operator=ScriptedOperator(),
                         log=logs[-1], protected=PROTECTED)

    result = run_with_provider_repeats(one_run)
    assert (result["status"], result["attempts"]) == ("done", 2)
    assert result["result"]["outcome"] == "done"
    # Review of pull request 7: the attempt that hit the limit leaves a provider_limit event (DD14).
    assert [record["event"] for record in logs[0].records] == ["run_start", "provider_limit"]
    assert logs[0].records[-1]["reason"] == "429 rate limit"
    assert logs[1].of_kind("provider_limit") == []
