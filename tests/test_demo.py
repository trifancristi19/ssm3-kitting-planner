"""Smoke tests for the Gate A demo (scripts/demo.py), run without its pauses and without a model."""

import json

from target_helper import DEMO_PLAN, DEMO_TARGET

from ssm3 import demo, planner
from ssm3.logger import read_log


def never_read(prompt=""):
    raise AssertionError("the demo must not pause with --no-pause")


def test_all_scenarios_run_without_pauses(tmp_path):
    lines = []
    results = demo.main(["--no-pause", "--log-dir", str(tmp_path)], out=lines.append, read=never_read)
    screen = "\n".join(lines)
    assert demo.PLANNER_NOTE in screen
    outcomes = [summary["outcome"] for summary, _ in results]
    assert outcomes == ["done", "done", "stopped", "done", "stopped", "done", "stopped", "done"]
    for summary, _ in [results[0], results[1], results[3], results[5], results[7]]:
        assert summary["final_state"]["slots"]["SLOT_2"] == ["BRICK_2X4_RED"]
        assert summary["final_state"]["slots"]["SLOT_1"] == ["BRICK_2X4_BLUE"]
    assert "code PROTECTED_SLOT" in screen and "code PART_COVERED" in screen
    assert "not recovered" in screen
    assert len(list(tmp_path.glob("*.jsonl"))) == 8
    for _, log in results:
        assert read_log(log.path) == log.records


def test_scenario_1_gives_the_chapter_6_plan_with_bricks(tmp_path):
    lines = []
    [(summary, log)] = demo.main(["--no-pause", "--scenario", "1", "--log-dir", str(tmp_path)], out=lines.append,
                                 read=never_read)
    run = [{"function": r["function"], "args": r["args"]} for r in log.of_kind("step_result")]
    assert run == DEMO_PLAN
    assert summary["final_state"]["return"] == ["BRICK_2X2_RED"]


def test_scenario_4_a_failed_pick_stops_the_open_loop_and_is_tried_again_in_the_closed_loop(tmp_path):
    lines = []
    (open_run, open_log), (closed_run, closed_log) = demo.main(
        ["--no-pause", "--scenario", "4", "--log-dir", str(tmp_path)], out=lines.append, read=never_read)
    assert (open_run["outcome"], closed_run["outcome"]) == ("stopped", "done")
    failed = [r for r in closed_log.of_kind("step_result") if r["status"] == "failed"]
    assert [(r["step"], r["function"]) for r in failed] == [(6, "pick")]
    assert "gripper closed but is still empty" in failed[0]["message"]
    after = closed_log.of_kind("step_result")[6]
    assert (after["function"], after["args"]["part"], after["status"]) == ("pick", "BRICK_2X4_RED", "success")
    assert "the next pick fails" in "\n".join(lines)


def test_scenario_5_a_part_that_slips_out_is_fetched_again_in_the_closed_loop(tmp_path):
    lines = []
    (open_run, open_log), (closed_run, closed_log) = demo.main(
        ["--no-pause", "--scenario", "5", "--log-dir", str(tmp_path)], out=lines.append, read=never_read)
    assert open_log.of_kind("step_result")[-1]["status"] == "blocked"
    assert open_run["final_state"]["bins"]["BIN_2"] == ["BRICK_2X4_RED"] * 2
    assert closed_run["outcome"] == "done" and closed_run["final_state"]["slots"]["SLOT_2"] == ["BRICK_2X4_RED"]
    [injected] = closed_log.of_kind("feedback")
    assert (injected["failure"], injected["step"]) == ("drop_part", 7)
    assert "BRICK_2X4_RED slips out of the gripper" in "\n".join(lines)


def test_pauses_wait_for_enter(tmp_path):
    prompts = []
    demo.main(["--scenario", "1", "--log-dir", str(tmp_path)], out=lambda line: None, read=prompts.append)
    assert prompts == ["\n[press Enter to continue]"]


# Live mode, with call_model replaced, so no test reaches Groq

SENTINEL = "gsk_test_sentinel_key_0123456789"


def live(tmp_path, *extra):
    lines = []
    results = demo.main(["--live", "--no-pause", "--log-dir", str(tmp_path), *extra], out=lines.append,
                        read=never_read, sleep=lambda seconds: None)
    return results, "\n".join(lines)


def with_key(monkeypatch, tmp_path):
    monkeypatch.setenv("GROQ_API_KEY", SENTINEL)
    monkeypatch.setattr(planner, "ENV_FILE", tmp_path / "no.env")


def test_live_closed_loop_shows_the_raw_answer_the_checker_and_the_steps(tmp_path, monkeypatch):
    with_key(monkeypatch, tmp_path)
    prompts = []

    def fake_model(prompt, settings=None):
        prompts.append(prompt)
        return json.dumps({"plan": DEMO_PLAN[len(prompts) - 1:], "target": DEMO_TARGET})

    monkeypatch.setattr(planner, "call_model", fake_model)
    [(summary, log)], screen = live(tmp_path)
    assert summary["outcome"] == "done"
    assert (summary["steps_run"], summary["planner_calls"]) == (9, 10)
    assert "Raw answer:" in screen and "Checker: RUN" in screen and "step  9" in screen
    assert "real language model" in screen
    start = log.of_kind("run_start")[0]
    assert (start["model"], start["prompt_version"]) == ("openai/gpt-oss-120b", planner.PROMPT_VERSION)
    assert SENTINEL not in screen
    assert SENTINEL not in log.path.read_text(encoding="utf-8")


def test_live_open_loop_makes_one_call(tmp_path, monkeypatch):
    with_key(monkeypatch, tmp_path)
    monkeypatch.setattr(planner, "call_model",
                        lambda prompt, settings=None: json.dumps({"plan": DEMO_PLAN, "target": DEMO_TARGET}))
    [(summary, _)], _ = live(tmp_path, "--variant", "open")
    assert (summary["outcome"], summary["planner_calls"]) == ("done", 1)


def test_live_without_a_key_falls_back_to_the_scripted_order(tmp_path, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(planner, "ENV_FILE", tmp_path / "no.env")

    def must_not_be_called(*args, **kwargs):
        raise AssertionError("no model call without a key")

    monkeypatch.setattr(planner, "call_model", must_not_be_called)
    [(summary, _)], screen = live(tmp_path)
    assert "GROQ_API_KEY is not set" in screen
    assert demo.PLANNER_NOTE in screen
    assert summary["outcome"] == "done"


def test_live_provider_limit_shows_a_message_and_falls_back(tmp_path, monkeypatch):
    with_key(monkeypatch, tmp_path)

    def limited(prompt, settings=None):
        raise planner.ProviderLimit("groq returned 429: Rate limit reached")

    monkeypatch.setattr(planner, "call_model", limited)
    [(summary, _)], screen = live(tmp_path)
    assert "The live model could not be used: ProviderLimit" in screen
    assert "Traceback" not in screen
    assert summary["outcome"] == "done"


def test_live_waits_when_groq_asks_for_a_short_pause(tmp_path, monkeypatch):
    with_key(monkeypatch, tmp_path)
    calls = {"n": 0}
    waits = []

    def once_limited(prompt, settings=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise planner.ProviderLimit("429", retry_after=5)
        return json.dumps({"plan": DEMO_PLAN, "target": DEMO_TARGET})

    monkeypatch.setattr(planner, "call_model", once_limited)
    lines = []
    [(summary, _)] = demo.main(["--live", "--variant", "open", "--no-pause", "--log-dir", str(tmp_path)],
                               out=lines.append, read=never_read, sleep=waits.append)
    assert summary["outcome"] == "done"
    assert waits == [6]


def test_the_fallback_can_be_declined(tmp_path, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(planner, "ENV_FILE", tmp_path / "no.env")
    answers = ["n"]
    results = demo.main(["--live", "--log-dir", str(tmp_path)], out=lambda line: None,
                        read=lambda prompt: answers.pop(0), sleep=lambda seconds: None)
    assert results == []


def test_live_local_needs_no_key_and_logs_the_local_model(tmp_path, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(planner, "ENV_FILE", tmp_path / "no.env")
    seen = []

    def fake_model(prompt, settings=None):
        seen.append(settings)
        return json.dumps({"plan": DEMO_PLAN, "target": DEMO_TARGET})

    monkeypatch.setattr(planner, "call_model", fake_model)
    [(summary, log)], screen = live(tmp_path, "--local", "--variant", "open")
    assert summary["outcome"] == "done"
    assert "qwen3:8b on Ollama on this computer" in screen and "needs no API key" in screen
    assert seen[0]["provider"] == "ollama"
    start = log.of_kind("run_start")[0]
    assert (start["model"], start["provider"]) == ("qwen3:8b", "ollama")
