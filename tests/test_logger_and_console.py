"""Tests for the run logger (Chapter 10) and the operator console (Chapter 9)."""

from datetime import UTC, datetime

import pytest

from ssm3.console import NO_FURTHER_INFORMATION, ScriptedOperator, TerminalOperator
from ssm3.logger import EVENT_KINDS, REMOVED, RunLog, read_log


def fixed_clock():
    return datetime(2026, 11, 12, 20, 0, tzinfo=UTC)


# Run logger

def test_every_record_has_run_id_number_time_and_kind():
    log = RunLog("K-17-closed-1", clock=fixed_clock)
    record = log.event("run_start", order_id="K-17", variant="closed loop")
    assert record == {"run_id": "K-17-closed-1", "seq": 1, "time": "2026-11-12T20:00:00+00:00",
                      "event": "run_start", "order_id": "K-17", "variant": "closed loop"}
    assert log.event("run_end", outcome="done")["seq"] == 2


def test_the_log_is_one_json_record_per_line_in_one_file_per_run(tmp_path):
    log = RunLog("K-17-open-1", folder=tmp_path, clock=fixed_clock)
    log.event("run_start", order_id="K-17")
    log.event("step_result", step=1, state={"slots": {"SLOT_2": ["SPACER_SHORT"]}})
    assert log.path == tmp_path / "K-17-open-1.jsonl"
    assert read_log(log.path) == log.records
    assert len(log.path.read_text(encoding="utf-8").splitlines()) == 2


def test_unknown_event_kinds_are_refused():
    assert "intervention" in EVENT_KINDS
    with pytest.raises(ValueError):
        RunLog("r").event("chat")


def test_a_field_that_is_not_json_fails_early():
    log = RunLog("r")
    with pytest.raises(TypeError):
        log.event("feedback", thing=object())
    assert log.records == []


def test_api_keys_never_reach_the_log(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_secret_value_123")
    log = RunLog("r", folder=tmp_path)
    log.event("planner_response", raw="Error: invalid key gsk_secret_value_123",
              headers=["Bearer gsk_secret_value_123"])
    text = log.path.read_text(encoding="utf-8")
    assert "gsk_secret_value_123" not in text
    assert log.records[0]["raw"] == f"Error: invalid key {REMOVED}"


def test_of_kind_returns_the_records_of_one_kind():
    log = RunLog("r")
    log.event("intervention", kind="clarification")
    log.event("step_result", step=1)
    log.event("intervention", kind="correction")
    assert [record["kind"] for record in log.of_kind("intervention")] == ["clarification", "correction"]


# Operator console

def test_the_scripted_operator_answers_in_order_then_gives_the_fixed_reply():
    operator = ScriptedOperator(["The long one.", "Slot 2."])
    assert operator.ask("Which spacer?") == "The long one."
    assert operator.ask("Which slot?") == "Slot 2."
    assert operator.ask("Anything else?") == NO_FURTHER_INFORMATION == "no further information"
    assert operator.questions == ["Which spacer?", "Which slot?", "Anything else?"]


def test_the_scripted_operator_keeps_what_it_was_told():
    operator = ScriptedOperator()
    operator.tell("Order K-17 stopped")
    assert operator.messages == ["Order K-17 stopped"]


def test_the_terminal_operator_reads_and_writes_through_the_given_functions():
    shown = []
    operator = TerminalOperator(read=lambda prompt: shown.append(prompt) or "  slot 2 \n", write=shown.append)
    assert operator.ask("Which slot?") == "slot 2"
    operator.tell("Run stopped")
    assert shown == ["Question from the planner: Which slot?\n> ", "Operator notice: Run stopped"]
