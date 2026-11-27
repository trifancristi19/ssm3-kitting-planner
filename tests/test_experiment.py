"""Tests for the experiment runner: one task through the baseline, the open loop and the closed loop."""

import json

import pytest

from ssm3 import experiment, planner
from ssm3.demo import chapter_13_state, demo_capability, plan_from_state
from ssm3.evaluator import load_task_set
from ssm3.logger import read_log
from ssm3.orchestrator import ProviderLimit
from ssm3.planner import ModelAccessError

SENTINEL = "gsk_test_sentinel_key_0123456789"


@pytest.fixture
def task():
    return load_task_set(experiment.DEFAULT_TASK_SET)["K-17"]


@pytest.fixture
def with_key(monkeypatch, tmp_path):
    monkeypatch.setenv("GROQ_API_KEY", SENTINEL)
    monkeypatch.setattr(planner, "ENV_FILE", tmp_path / "no.env")


def state_planner(settings=None, function_detail="full"):
    """A stand-in for the model that writes the remaining plan from the state, so no test reaches Groq."""
    return lambda order, state, capability, history: json.dumps(plan_from_state(state))


def run_main(tmp_path, *extra):
    lines = []
    results = experiment.main(["--log-dir", str(tmp_path), *extra], out=lines.append, sleep=lambda seconds: None)
    return results, "\n".join(lines)


def test_the_baseline_plan_is_the_plan_of_the_task(task):
    state = chapter_13_state(demo_capability())
    answer = experiment.baseline_planner(task)(task["text"], state, demo_capability(), [])
    assert json.loads(answer) == {"plan": plan_from_state(state)["plan"]}


def test_baseline_only_runs_every_case_and_scores_it(tmp_path):
    results, screen = run_main(tmp_path, "--no-llm", "--reps", "2")
    clean = results["clean"]["summary"]["baseline"]
    failing = results["pick failure"]["summary"]["baseline"]
    assert clean["runs"] == 2 and clean["task_success_rate"] == 1.0
    assert failing["runs"] == 2 and failing["task_success_rate"] == 0.0 and failing["recovery_rate"] == 0.0
    assert "=== Case: clean ===" in screen and "baseline / baseline / -" in screen
    assert len(list(tmp_path.glob("demo-exp-baseline-*.jsonl"))) == 4


def test_the_baseline_makes_no_model_call(tmp_path, monkeypatch):
    def must_not_be_called(*args, **kwargs):
        raise AssertionError("the baseline makes no model call")

    monkeypatch.setattr(planner, "call_model", must_not_be_called)
    monkeypatch.setattr(planner, "check_access", must_not_be_called)
    run_main(tmp_path, "--no-llm", "--reps", "1")
    start = read_log(next(tmp_path.glob("demo-exp-baseline-clean-*.jsonl")))[0]
    assert start["planner"] == "baseline" and "model" not in start


def test_all_three_approaches_give_comparable_rows_for_the_same_task(tmp_path, monkeypatch, with_key):
    monkeypatch.setattr(planner, "llm_planner", state_planner)
    results, screen = run_main(tmp_path, "--reps", "2", "--delay", "0")
    for case in ("clean", "pick failure"):
        summary = results[case]["summary"]
        assert list(summary) == ["open loop", "closed loop", "baseline"]
        assert all(group["runs"] == 2 and group["runs_per_task"] == {"K-17": 2} for group in summary.values())
    clean = results["clean"]["summary"]
    assert all(group["task_success_rate"] == 1.0 for group in clean.values())
    failing = results["pick failure"]["summary"]
    assert (failing["open loop"]["recovery_rate"], failing["baseline"]["recovery_rate"]) == (0.0, 0.0)
    assert failing["closed loop"]["recovery_rate"] == 1.0
    assert "closed loop / openai/gpt-oss-120b / S2-P2" in screen


def test_llm_logs_hold_the_model_and_the_prompt_version(tmp_path, monkeypatch, with_key):
    monkeypatch.setattr(planner, "llm_planner", state_planner)
    run_main(tmp_path, "--reps", "1", "--delay", "0")
    start = read_log(next(tmp_path.glob("demo-exp-closed-loop-clean-*.jsonl")))[0]
    assert (start["model"], start["prompt_version"], start["planner"]) == ("openai/gpt-oss-120b", "S2-P2", "llm")
    assert start["order_id"] == "K-17" and start["initial_state"]["slots"]["SLOT_2"] == ["SPACER_SHORT"]
    assert SENTINEL not in start["settings"].values()


def test_without_a_key_only_the_baseline_runs(tmp_path, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(planner, "ENV_FILE", tmp_path / "no.env")
    results, screen = run_main(tmp_path, "--reps", "1")
    assert "only the baseline runs" in screen
    assert all(list(result["summary"]) == ["baseline"] for result in results.values())


def test_a_provider_limit_is_repeated_and_then_listed_as_not_run(tmp_path, monkeypatch, with_key):
    def limited(settings=None, function_detail="full"):
        def plan(order, state, capability, history):
            raise ProviderLimit("429 rate limit")

        return plan

    monkeypatch.setattr(planner, "llm_planner", limited)
    monkeypatch.setattr(planner, "check_access", lambda settings=None: None)
    results, screen = run_main(tmp_path, "--reps", "1", "--delay", "0")
    open_loop = results["clean"]["summary"]["open loop"]
    assert open_loop is None
    assert "not run, provider limit after 4 attempts" in screen
    assert len(list(tmp_path.glob("demo-exp-open-loop-clean-*.jsonl"))) == 4
    not_run = [run for run in results["clean"]["runs"] if run["variant"] == "open loop"]
    assert len(not_run) == 4 and all(run["status"] == "not run" for run in not_run)
    assert results["clean"]["summary"]["baseline"]["task_success_rate"] == 1.0


def test_a_model_error_marks_the_run_not_run_and_goes_on(tmp_path, monkeypatch, with_key):
    def broken(settings=None, function_detail="full"):
        def plan(order, state, capability, history):
            raise ModelAccessError("the key was refused")

        return plan

    monkeypatch.setattr(planner, "llm_planner", broken)
    monkeypatch.setattr(planner, "check_access", lambda settings=None: None)
    results, screen = run_main(tmp_path, "--reps", "1", "--delay", "0")
    assert "open loop / clean / run 1: not run (ModelAccessError" in screen
    assert results["clean"]["summary"]["baseline"]["runs"] == 1


def test_the_result_can_be_written_as_json(tmp_path):
    target = tmp_path / "result.json"
    run_main(tmp_path, "--no-llm", "--reps", "1", "--json", str(target))
    data = json.loads(target.read_text(encoding="utf-8"))
    assert set(data) == {"clean", "pick failure"}
    assert data["clean"]["summary"]["baseline"]["task_success_rate"] == 1.0


def test_only_the_task_with_a_start_tray_can_be_run(tmp_path):
    with pytest.raises(SystemExit):
        run_main(tmp_path, "--task", "K-99", "--no-llm")
    with pytest.raises(SystemExit):
        run_main(tmp_path, "--reps", "0", "--no-llm")
