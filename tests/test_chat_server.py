"""Tests for the chat server routes (chat_server.handle), without opening a socket or calling a model."""

import json

from ssm3 import chat, chat_server

PLAN = json.dumps({"plan": [{"function": "move_to", "args": {"position": "BIN_1"}},
                            {"function": "pick", "args": {"part": "BOLT", "source": "BIN_1"}},
                            {"function": "move_to", "args": {"position": "SLOT_4"}},
                            {"function": "place", "args": {"part": "BOLT", "slot": "SLOT_4", "level": "base"}}]})


def session(tmp_path, *raw):
    remaining = list(raw)
    return chat.ChatSession(planner=lambda *args: remaining.pop(0), log_dir=tmp_path, answer_seconds=1)


def call(s, method, path, data=None, content_type="application/json", host="127.0.0.1:8765"):
    body = json.dumps(data).encode() if data is not None else b""
    status, kind, content = chat_server.handle(s, method, path, body, content_type, host)
    return status, json.loads(content) if kind.startswith("application/json") else content.decode()


def test_the_page_is_served(tmp_path):
    status, text = call(session(tmp_path), "GET", "/")
    assert status == 200 and "<title>SSM3 cell chat</title>" in text
    # The drawing and the styles of the replay page are put in, so the two pages draw the cell the same way.
    assert "__CELL_VIEW__" not in text and "__CELL_STYLE__" not in text
    assert "function drawStatic()" in text and "function drawArm(" in text and "--reject:" in text


def test_an_order_runs_and_its_events_can_be_read(tmp_path):
    s = session(tmp_path, PLAN)
    assert call(s, "POST", "/api/order", {"text": "Put the bolt from BIN_1 in slot 4", "variant": "open"}) == \
        (200, {"ok": True, "error": None})
    s.wait(5)
    status, data = call(s, "GET", "/api/events?since=0")
    assert status == 200 and data["busy"] is False
    assert data["events"][0]["event"] == "user" and data["events"][-1]["event"] == "idle"
    assert data["state"]["slots"]["SLOT_4"] == ["BOLT"]
    later = call(s, "GET", f"/api/events?since={len(data['events']) - 1}")[1]["events"]
    assert [e["event"] for e in later] == ["idle"]


def test_a_question_is_answered_through_the_route(tmp_path):
    s = session(tmp_path, '{"ask": "Which bolt?"}', PLAN)
    call(s, "POST", "/api/order", {"text": "Move a bolt to slot 4"})
    for _ in range(200):
        if any(e["event"] == "operator_question" for e in s.events_since()):
            break
        s.wait(0.01)
    assert call(s, "POST", "/api/answer", {"text": "The one in BIN_1"})[0] == 200
    s.wait(5)
    assert next(e for e in s.events_since() if e["event"] == "intervention")["answer"] == "The one in BIN_1"


def test_other_sites_and_other_formats_are_refused(tmp_path):
    s = session(tmp_path, PLAN)
    assert call(s, "POST", "/api/order", {"text": "x"}, content_type="text/plain")[0] == 415
    assert call(s, "POST", "/api/order", {"text": "x"}, host="evil.example:8765")[0] == 403
    assert call(s, "GET", "/api/events", host="evil.example")[0] == 403
    assert chat_server.handle(s, "POST", "/api/order", b"{not json", "application/json")[0] == 400
    assert chat_server.handle(s, "POST", "/api/order", b"x" * 20_000, "application/json")[0] == 413
    assert call(s, "POST", "/api/answer", {"text": "  "})[0] == 400
    assert call(s, "GET", "/nothing")[0] == 404
    assert s.events_since() == []


def test_an_empty_order_and_a_second_order_are_refused(tmp_path):
    s = session(tmp_path, '{"ask": "Which bolt?"}', '{"refuse": "no"}')
    assert call(s, "POST", "/api/order", {"text": " "})[0] == 409
    assert call(s, "POST", "/api/order", {"text": "Move a bolt"})[0] == 200
    assert call(s, "POST", "/api/order", {"text": "Another"})[0] == 409
    assert call(s, "POST", "/api/reset", {})[0] == 409
    s.wait(5)
    assert call(s, "POST", "/api/reset", {}) == (200, {"ok": True, "error": None})


def test_main_builds_a_session_with_the_options(monkeypatch):
    seen = {}

    def fake_serve(session, port, out, open_page):
        seen.update(port=port, model=session.model, delay=session.delay, uses_model=session.uses_model,
                    open_page=open_page)

    chat_server.main(["--port", "9001", "--model", "another-model", "--delay", "1", "--no-open"],
                     out=lambda line: None, run=fake_serve)
    assert seen == {"port": 9001, "model": "another-model", "delay": 1.0, "uses_model": True, "open_page": None}
    chat_server.main([], out=lambda line: None, show="opener", run=fake_serve)
    assert seen["port"] == chat_server.PORT and seen["open_page"] == "opener"


def test_an_order_carries_the_ticked_slots_to_the_checker(tmp_path):
    touches_slot_1 = json.dumps({"plan": [{"function": "move_to", "args": {"position": "SLOT_1"}},
                                          {"function": "pick", "args": {"part": "SPACER_BLUE", "source": "SLOT_1"}}]})
    s = session(tmp_path, touches_slot_1, '{"refuse": "Slot 1 stays unchanged"}')
    assert call(s, "GET", "/api/events")[1]["default_protected"] == ["SLOT_1", "SLOT_3"]
    assert call(s, "POST", "/api/order", {"text": "Take the blue spacer", "protected": ["SLOT_1"]})[0] == 200
    s.wait(5)
    reject = next(e for e in s.events_since() if e["event"] == "check_result")
    assert reject["code"] == "PROTECTED_SLOT"


def test_bad_protected_lists_are_refused(tmp_path):
    s = session(tmp_path, PLAN)
    assert call(s, "POST", "/api/order", {"text": "x", "protected": "SLOT_1"})[0] == 400
    assert call(s, "POST", "/api/order", {"text": "x", "protected": ["SLOT_9"]})[0] == 400
    assert s.events_since() == []


def test_main_with_local_uses_ollama_and_no_delay(monkeypatch):
    seen = {}

    def fake_serve(session, port, out, open_page):
        seen.update(provider=session.settings["provider"], model=session.model, delay=session.delay,
                    local=session.local)

    chat_server.main(["--local", "--no-open"], out=lambda line: None, run=fake_serve)
    assert seen == {"provider": "ollama", "model": "qwen3:8b", "delay": 0, "local": True}
    chat_server.main(["--local", "--model", "gpt-oss:20b", "--delay", "1", "--no-open"], out=lambda line: None,
                     run=fake_serve)
    assert (seen["model"], seen["delay"]) == ("gpt-oss:20b", 1.0)


def test_the_events_say_which_provider_plans(tmp_path):
    s = chat.ChatSession(settings={"provider": "ollama", "needs_key": False}, log_dir=tmp_path)
    _, data = call(s, "GET", "/api/events")
    assert (data["provider"], data["local"]) == ("Ollama on this computer", True)
    _, data = call(chat.ChatSession(log_dir=tmp_path), "GET", "/api/events")
    assert (data["provider"], data["local"]) == ("Groq", False)
