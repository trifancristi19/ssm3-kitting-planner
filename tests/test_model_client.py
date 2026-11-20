"""Tests for the Groq model client (Design Document, Chapter 7, DD14 and NFR4).

No test reaches Groq: every HTTP call is replaced by a fake opener, and the network is
blocked in every test (conftest.py). The key in these tests is a made-up sentinel.
"""

import io
import json
import urllib.error

import pytest

from ssm3 import orchestrator, planner
from ssm3.logger import RunLog
from ssm3.planner import (
    DEFAULT_SETTINGS,
    ModelAccessError,
    ModelTimeout,
    ProviderLimit,
    api_key,
    call_model,
    llm_planner,
)

SENTINEL = "gsk_test_sentinel_key_0123456789"


@pytest.fixture
def key(monkeypatch, tmp_path):
    """A made-up key in the environment, and no .env file, whatever the machine has set."""
    monkeypatch.setenv("GROQ_API_KEY", SENTINEL)
    monkeypatch.setattr(planner, "ENV_FILE", tmp_path / ".env")
    return SENTINEL


@pytest.fixture
def no_key(monkeypatch, tmp_path):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(planner, "ENV_FILE", tmp_path / ".env")
    return tmp_path / ".env"


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def answering(content, seen=None):
    """An opener that records the request and answers like the chat completions endpoint."""

    def opener(request, timeout):
        if seen is not None:
            seen.append((request, timeout))
        body = {"choices": [{"message": {"role": "assistant", "content": content}}],
                "usage": {"completion_tokens": 42}}
        return FakeResponse(json.dumps(body).encode("utf-8"))

    return opener


def failing(code, body="error", headers=None):
    def opener(request, timeout):
        raise urllib.error.HTTPError(request.full_url, code, "error", headers or {}, io.BytesIO(body.encode()))

    return opener


# The request

def test_the_request_follows_the_settings(key):
    seen = []
    assert call_model("the prompt", opener=answering('{"plan": []}', seen)) == '{"plan": []}'
    [(request, timeout)] = seen
    assert request.full_url == "https://api.groq.com/openai/v1/chat/completions"
    assert request.get_header("Authorization") == f"Bearer {SENTINEL}"
    payload = json.loads(request.data)
    assert payload == {"model": "openai/gpt-oss-120b", "messages": [{"role": "user", "content": "the prompt"}],
                       "temperature": 0, "response_format": {"type": "json_object"}}
    assert timeout == 60


def test_the_default_settings_follow_the_design_document():
    # DD17 (proposed main model, the exact ID of the model tests), Chapter 7 and NFR1 (temperature 0, JSON), DD14.
    assert DEFAULT_SETTINGS["model"] == "openai/gpt-oss-120b"
    assert DEFAULT_SETTINGS["temperature"] == 0
    assert DEFAULT_SETTINGS["json_mode"] is True
    assert DEFAULT_SETTINGS["timeout_seconds"] == 60


def test_settings_can_change_the_model_and_switch_json_off(key):
    seen = []
    call_model("p", {"model": "another-model", "json_mode": False}, opener=answering("{}", seen))
    payload = json.loads(seen[0][0].data)
    assert payload["model"] == "another-model"
    assert "response_format" not in payload


# The key

def test_a_missing_key_is_a_clear_error(no_key):
    with pytest.raises(ModelAccessError, match="GROQ_API_KEY is not set"):
        call_model("p", opener=answering("{}"))


def test_the_key_can_come_from_a_local_env_file(no_key, monkeypatch):
    no_key.write_text(f'# local only\nOTHER=1\nGROQ_API_KEY="{SENTINEL}"\n', encoding="utf-8")
    assert api_key() == SENTINEL
    # Put in the environment, so the run logger removes it from every record.
    import os

    assert os.environ["GROQ_API_KEY"] == SENTINEL
    monkeypatch.delenv("GROQ_API_KEY")


def test_the_key_never_reaches_the_log(key, tmp_path):
    log = RunLog("secret-test", folder=tmp_path)
    log.event("planner_response", call=1, raw=f"echo {SENTINEL}", seconds=0.1)
    assert SENTINEL not in (tmp_path / "secret-test.jsonl").read_text(encoding="utf-8")
    assert SENTINEL not in json.dumps(log.records)


# Errors (DD14)

@pytest.mark.parametrize("code", [429, 498, 500, 502, 503, 504])
def test_rate_limits_and_server_errors_are_provider_limits(key, code):
    with pytest.raises(ProviderLimit):
        call_model("p", opener=failing(code))


def test_a_provider_limit_keeps_the_wait_the_provider_asked_for(key):
    with pytest.raises(ProviderLimit) as caught:
        call_model("p", opener=failing(429, "Rate limit reached", {"retry-after": "7"}))
    assert caught.value.retry_after == 7.0


@pytest.mark.parametrize("code", [400, 401, 403, 404])
def test_a_refused_key_or_bad_request_is_an_access_error(key, code):
    with pytest.raises(ModelAccessError):
        call_model("p", opener=failing(code))


def test_error_messages_never_hold_the_key(key):
    with pytest.raises(ModelAccessError) as caught:
        call_model("p", opener=failing(401, f"Invalid API Key {SENTINEL}"))
    assert SENTINEL not in str(caught.value)


def test_a_slow_answer_is_a_model_timeout_not_a_provider_limit(key):
    def slow(request, timeout):
        raise TimeoutError("timed out")

    with pytest.raises(ModelTimeout):
        call_model("p", opener=slow)


def test_a_lost_connection_is_a_provider_limit(key):
    def offline(request, timeout):
        raise urllib.error.URLError("getaddrinfo failed")

    with pytest.raises(ProviderLimit):
        call_model("p", opener=offline)


def test_an_answer_without_a_message_is_a_provider_limit(key):
    def empty(request, timeout):
        return FakeResponse(b'{"choices": []}')

    with pytest.raises(ProviderLimit):
        call_model("p", opener=empty)


def test_a_groq_rate_limit_is_repeated_by_the_orchestrator(key, cell, monkeypatch, chapter6_plan):
    # The class call_model raises must be the one run_with_provider_repeats catches.
    assert orchestrator.ProviderLimit is planner.ProviderLimit
    calls = {"n": 0}

    def flaky(prompt, settings=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return call_model(prompt, settings, opener=failing(429))
        return json.dumps({"plan": chapter6_plan})

    monkeypatch.setattr(planner, "call_model", flaky)

    def run():
        from ssm3.cell import SimulatedCell
        from ssm3.console import ScriptedOperator

        fresh = SimulatedCell(cell.capability, cell.state())
        return orchestrator.run_order({"order_id": "K-17", "text": "swap"}, "open loop", planner=llm_planner(),
                                      cell=fresh, operator=ScriptedOperator(), log=RunLog("repeat"))

    result = orchestrator.run_with_provider_repeats(run)
    assert (result["status"], result["attempts"]) == ("done", 2)
    assert result["result"]["outcome"] == "done"


# A local model through Ollama (demo and chat mode only, proposal)

def test_the_local_settings_reach_ollama_on_this_computer_without_a_key(no_key):
    seen = []
    settings = planner.settings_for(local=True)
    assert call_model("the prompt", settings, opener=answering('{"plan": []}', seen)) == '{"plan": []}'
    [(request, timeout)] = seen
    assert request.full_url == "http://localhost:11434/v1/chat/completions"
    assert request.get_header("Authorization") is None
    payload = json.loads(request.data)
    assert payload["model"] == "qwen3:8b" and payload["temperature"] == 0
    assert payload["response_format"] == {"type": "json_object"}
    assert timeout == planner.LOCAL_SETTINGS["timeout_seconds"]


def test_the_local_settings_never_send_a_groq_key(key):
    seen = []
    call_model("p", planner.settings_for(local=True), opener=answering("{}", seen))
    [(request, _)] = seen
    assert request.get_header("Authorization") is None
    assert SENTINEL not in json.dumps(dict(request.header_items())) + request.data.decode()


def test_settings_for_picks_the_provider_and_the_model():
    assert planner.settings_for() == DEFAULT_SETTINGS
    assert planner.settings_for(local=True)["model"] == "qwen3:8b"
    local = planner.settings_for(local=True, model="gpt-oss:20b")
    assert (local["provider"], local["model"], local["needs_key"]) == ("ollama", "gpt-oss:20b", False)
    assert local["temperature"] == 0 and local["json_mode"] is True
    assert planner.provider_name(local) == "Ollama on this computer"
    assert planner.provider_name() == "Groq"


def test_check_access_needs_a_key_only_for_groq(no_key):
    planner.check_access(planner.settings_for(local=True))
    with pytest.raises(ModelAccessError, match="GROQ_API_KEY is not set"):
        planner.check_access()


def test_ollama_not_running_says_how_to_start_it(no_key):
    def offline(request, timeout):
        raise urllib.error.URLError(ConnectionRefusedError("refused"))

    with pytest.raises(ProviderLimit, match="ollama pull qwen3:8b"):
        call_model("p", planner.settings_for(local=True), opener=offline)


def test_a_model_that_is_not_pulled_says_how_to_pull_it(no_key):
    with pytest.raises(ModelAccessError, match="ollama pull gpt-oss:20b"):
        call_model("p", planner.settings_for(local=True, model="gpt-oss:20b"),
                   opener=failing(404, '{"error": "model not found"}'))
