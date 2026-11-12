"""Tests for the run limits of the orchestrator (Design Document, Chapter 9, DD14 and DD21)."""

import pytest

from ssm3.orchestrator import PROVIDER_REPEATS, ProviderLimit, run_order, run_with_provider_repeats, step_budget


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


def test_run_order_is_still_a_stub():
    with pytest.raises(NotImplementedError):
        run_order({}, "closed loop")
