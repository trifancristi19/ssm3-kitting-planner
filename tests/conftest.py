"""Shared test setup.

Tests never use the network, so they can never call an LLM or spend API limits.
Any attempt to open a connection fails the test.
"""

import socket

import pytest


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise RuntimeError("Tests must not use the network (no LLM calls in tests or CI)")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
