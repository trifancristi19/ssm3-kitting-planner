"""Smoke tests for the Gate A demo (scripts/demo.py), run without its pauses and without a model."""

import json

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
    assert outcomes == ["done", "done", "stopped", "done"]
    for summary, _ in [results[0], results[1], results[3]]:
        assert summary["final_state"]["slots"]["SLOT_2"] == ["SPACER_LONG"]
        assert summary["final_state"]["slots"]["SLOT_1"] == ["SPACER_BLUE"]
    assert "code PROTECTED_SLOT" in screen and "code PART_COVERED" in screen
    assert "not recovered" in screen
    assert len(list(tmp_path.glob("*.jsonl"))) == 4
    for _, log in results:
        assert read_log(log.path) == log.records


def test_scenario_1_gives_the_chapter_6_plan(tmp_path, chapter6_plan):
    lines = []
    [(summary, log)] = demo.main(["--no-pause", "--scenario", "1", "--log-dir", str(tmp_path)], out=lines.append,
                                 read=never_read)
    run = [{"function": r["function"], "args": r["args"]} for r in log.of_kind("step_result")]
    assert run == chapter6_plan
    assert summary["final_state"]["return"] == ["SPACER_SHORT"]


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


def test_live_closed_loop_shows_the_raw_answer_the_checker_and_the_steps(tmp_path, monkeypatch, chapter6_plan):
    with_key(monkeypatch, tmp_path)
    prompts = []

    def fake_model(prompt, settings=None):
        prompts.append(prompt)
        return json.dumps({"plan": chapter6_plan[len(prompts) - 1:]})

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


def test_live_open_loop_makes_one_call(tmp_path, monkeypatch, chapter6_plan):
    with_key(monkeypatch, tmp_path)
    monkeypatch.setattr(planner, "call_model", lambda prompt, settings=None: json.dumps({"plan": chapter6_plan}))
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


def test_live_waits_when_groq_asks_for_a_short_pause(tmp_path, monkeypatch, chapter6_plan):
    with_key(monkeypatch, tmp_path)
    calls = {"n": 0}
    waits = []

    def once_limited(prompt, settings=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise planner.ProviderLimit("429", retry_after=5)
        return json.dumps({"plan": chapter6_plan})

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
