"""Tests for the chat session (chat.py), with fake planners, so no test calls a model."""

import json

from ssm3 import chat, planner


def answers(*raw):
    """A fake planner that gives these raw answers in order."""
    remaining = list(raw)

    def fake(order, state, capability, history):
        return remaining.pop(0)

    return fake


def plan(*steps):
    return json.dumps({"plan": [{"function": f, "args": a} for f, a in steps]})


BOLT_TO_SLOT_4 = plan(("move_to", {"position": "BIN_1"}), ("pick", {"part": "BOLT", "source": "BIN_1"}),
                      ("move_to", {"position": "SLOT_4"}),
                      ("place", {"part": "BOLT", "slot": "SLOT_4", "level": "base"}))


def kinds(session):
    return [event["event"] for event in session.events_since()]


def test_a_typed_order_runs_through_the_checker_and_the_cell(tmp_path):
    session = chat.ChatSession(planner=answers(BOLT_TO_SLOT_4), log_dir=tmp_path)
    summary = session.run("Put the bolt from BIN_1 in slot 4")
    assert summary["outcome"] == "done"
    assert session.state()["slots"]["SLOT_4"] == ["BOLT"]
    events = session.events_since()
    assert events[0] == {"event": "user", "order_id": "C-1", "text": "Put the bolt from BIN_1 in slot 4",
                         "variant": "open loop", "protected": [], "faults": [], "n": 0}
    assert [e["n"] for e in events] == list(range(len(events)))
    assert "check_result" in kinds(session) and kinds(session)[-1] == "run_end"
    assert (tmp_path / f"{events[1]['run_id']}.jsonl").exists()


def test_the_cell_keeps_its_state_for_the_next_order(tmp_path):
    # Parts go back through the return position, since the cell cannot place into a bin (BAD_POSITION).
    back = plan(("pick", {"part": "BOLT", "source": "SLOT_4"}), ("move_to", {"position": "RETURN"}),
                ("place", {"part": "BOLT", "slot": "RETURN"}))
    session = chat.ChatSession(planner=answers(BOLT_TO_SLOT_4, back), log_dir=tmp_path)
    session.run("Put the bolt from BIN_1 in slot 4")
    second = session.run("Now put it in the return position")
    assert second["outcome"] == "done"
    assert session.state()["slots"]["SLOT_4"] == [] and session.state()["return"] == ["BOLT"]
    start = [e for e in session.events_since() if e["event"] == "run_start"][1]
    assert start["order_id"] == "C-2" and start["initial_state"]["slots"]["SLOT_4"] == ["BOLT"]


def test_a_rejected_plan_moves_nothing(tmp_path):
    into_slot_1 = plan(("move_to", {"position": "BIN_1"}), ("pick", {"part": "BOLT", "source": "BIN_1"}),
                       ("move_to", {"position": "SLOT_1"}),
                       ("place", {"part": "BOLT", "slot": "SLOT_1", "level": "base"}))
    session = chat.ChatSession(planner=answers(into_slot_1, '{"refuse": "Slot 1 is full"}'), log_dir=tmp_path)
    before = session.state()
    summary = session.run("Put the bolt in slot 1")
    assert summary["outcome"] == "refused"
    rejects = [e for e in session.events_since() if e["event"] == "check_result" and e["verdict"] == "reject"]
    assert rejects and rejects[0]["code"] == "SLOT_OCCUPIED"
    assert session.state() == before


def test_a_question_waits_for_the_answer_typed_in_the_chat(tmp_path):
    session = chat.ChatSession(planner=answers('{"ask": "Which bolt?"}', BOLT_TO_SLOT_4), log_dir=tmp_path)
    assert session.submit("Move a bolt to slot 4")
    for _ in range(200):
        if "operator_question" in kinds(session):
            break
        session.wait(0.01)
    session.answer("The one in BIN_1")
    session.wait(5)
    assert not session.busy
    events = session.events_since()
    question = next(e for e in events if e["event"] == "operator_question")
    assert question["question"] == "Which bolt?"
    intervention = next(e for e in events if e["event"] == "intervention")
    assert intervention["answer"] == "The one in BIN_1"
    assert kinds(session)[-1] == "idle"
    assert session.state()["slots"]["SLOT_4"] == ["BOLT"]


def test_an_unanswered_question_gets_the_fixed_reply(tmp_path):
    session = chat.ChatSession(planner=answers('{"ask": "Which bolt?"}', '{"refuse": "Not clear"}'),
                               log_dir=tmp_path, answer_seconds=0.01)
    summary = session.run("Move a bolt")
    intervention = next(e for e in session.events_since() if e["event"] == "intervention")
    assert intervention["answer"] == chat.NO_FURTHER_INFORMATION
    assert summary["outcome"] == "refused"


def test_only_one_order_at_a_time_and_no_empty_orders(tmp_path):
    session = chat.ChatSession(planner=answers('{"ask": "Which bolt?"}', '{"refuse": "no"}'), log_dir=tmp_path,
                               answer_seconds=0.5)
    assert not session.submit("   ")
    assert not session.submit("x", variant="sideways")
    assert session.submit("Move a bolt")
    assert not session.submit("Another order")
    assert not session.reset()
    session.wait(5)
    assert session.reset()


def test_without_a_key_the_chat_says_so_and_calls_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(planner, "ENV_FILE", tmp_path / "no.env")

    def must_not_be_called(*args, **kwargs):
        raise AssertionError("no model call without a key")

    monkeypatch.setattr(planner, "call_model", must_not_be_called)
    session = chat.ChatSession(log_dir=tmp_path)
    assert session.run("Put the bolt in slot 4") is None
    error = session.events_since()[-1]
    assert error["event"] == "error" and "GROQ_API_KEY is not set" in error["reason"]


def test_a_provider_limit_ends_the_order_with_a_message(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_sentinel_key_0123456789")
    monkeypatch.setattr(planner, "ENV_FILE", tmp_path / "no.env")

    def limited(prompt, settings=None):
        raise planner.ProviderLimit("groq returned 429")

    monkeypatch.setattr(planner, "call_model", limited)
    session = chat.ChatSession(log_dir=tmp_path, sleep=lambda seconds: None)
    assert session.run("Put the bolt in slot 4") is None
    events = session.events_since()
    assert events[-1]["event"] == "error" and "ProviderLimit" in events[-1]["reason"]
    assert "gsk_test_sentinel_key_0123456789" not in json.dumps(events)


INTO_RETURN_FROM_SLOT_1 = plan(("move_to", {"position": "SLOT_1"}),
                               ("pick", {"part": "SPACER_BLUE", "source": "SLOT_1"}),
                               ("move_to", {"position": "RETURN"}),
                               ("place", {"part": "SPACER_BLUE", "slot": "RETURN"}))


def test_the_checker_protects_the_ticked_slots_whatever_the_order_says(tmp_path):
    # Mihail's review: without this, only the model kept slots 1 and 3 unchanged in the chat.
    session = chat.ChatSession(planner=answers(INTO_RETURN_FROM_SLOT_1, '{"refuse": "Slot 1 must stay unchanged"}'),
                               log_dir=tmp_path)
    before = session.state()
    summary = session.run("Put the blue spacer from slot 1 in the return position", protected=["SLOT_3", "SLOT_1"])
    assert summary["outcome"] == "refused"
    events = session.events_since()
    assert events[0]["protected"] == ["SLOT_1", "SLOT_3"]
    assert next(e for e in events if e["event"] == "run_start")["protected"] == ["SLOT_1", "SLOT_3"]
    reject = next(e for e in events if e["event"] == "check_result")
    assert (reject["verdict"], reject["code"]) == ("reject", "PROTECTED_SLOT")
    assert session.state() == before


def test_without_ticked_slots_the_same_plan_runs(tmp_path):
    session = chat.ChatSession(planner=answers(INTO_RETURN_FROM_SLOT_1), log_dir=tmp_path)
    assert session.run("Put the blue spacer from slot 1 in the return position")["outcome"] == "done"
    assert session.state()["return"] == ["SPACER_BLUE"]


def test_unknown_protected_slots_are_refused(tmp_path):
    session = chat.ChatSession(planner=answers(BOLT_TO_SLOT_4), log_dir=tmp_path)
    assert not session.submit("Move the bolt", protected=["SLOT_9"])
    assert not session.submit("Move the bolt", protected="SLOT_1")
    assert not session.submit("Move the bolt", protected=["BIN_1"])
    assert session.events_since() == []


def test_a_local_model_runs_without_a_key(tmp_path, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(planner, "ENV_FILE", tmp_path / "no.env")
    seen = []

    def fake_model(prompt, settings=None):
        seen.append(settings)
        return json.dumps({"plan": []})

    monkeypatch.setattr(planner, "call_model", fake_model)
    session = chat.ChatSession(settings=planner.settings_for(local=True), log_dir=tmp_path, delay=0)
    summary = session.run("Nothing to do")
    assert summary is not None and seen[0]["provider"] == "ollama"
    start = next(event for event in session.events_since() if event["event"] == "run_start")
    assert (start["provider"], start["model"]) == ("ollama", "qwen3:8b")


# Gripper faults armed for the next order (proposal)

def test_armed_faults_go_off_once_and_the_closed_loop_recovers(tmp_path):
    from ssm3.demo import scripted_planner

    session = chat.ChatSession(planner=scripted_planner(), log_dir=tmp_path)
    summary = session.run("Replace the short spacer in slot 2 with a long spacer", "closed",
                          faults=["drop_part", "pick_failure"])
    assert summary["outcome"] == "done"
    events = session.events_since()
    assert events[0]["faults"] == ["pick_failure", "drop_part"]
    injected = [e for e in events if e["event"] == "feedback" and e["kind"] == "injected failure"]
    assert [e["failure"] for e in injected] == ["pick_failure", "drop_part"]
    # The slip went off before a move with a part in the gripper, and the part fell into its own bin.
    assert injected[1]["details"] == {"part": "SPACER_SHORT", "destination": "BIN_2"}
    statuses = [e["status"] for e in events if e["event"] == "step_result"]
    assert statuses.count("failed") == 1
    assert session.state()["slots"]["SLOT_2"] == ["SPACER_LONG"]
    # The next order runs without faults.
    session.run("Put the bolt from BIN_1 in slot 4", "open")
    assert not any(e["event"] == "feedback" for e in session.events_since(len(events)))


def test_open_loop_stops_at_an_armed_pick_failure(tmp_path):
    session = chat.ChatSession(planner=answers(BOLT_TO_SLOT_4), log_dir=tmp_path)
    summary = session.run("Put the bolt from BIN_1 in slot 4", "open", faults=["pick_failure"])
    assert summary["outcome"] == "stopped" and summary["steps_run"] == 2
    assert session.state()["bins"]["BIN_1"] == ["BOLT"]


def test_unknown_faults_are_refused(tmp_path):
    session = chat.ChatSession(planner=answers(BOLT_TO_SLOT_4), log_dir=tmp_path)
    assert session.submit("Put the bolt in slot 4", faults=["explode"]) is False
    assert session.submit("Put the bolt in slot 4", faults="pick_failure") is False
    assert session.events_since() == []
