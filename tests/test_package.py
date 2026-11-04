"""Smoke tests for the ssm3 package and the example capability file."""

import importlib
from pathlib import Path

import pytest

from ssm3.capability import load_capability

ROOT = Path(__file__).resolve().parent.parent
MODULES = ["baseline", "capability", "cell", "checker", "console", "evaluator",
           "functions", "logger", "orchestrator", "planner"]


@pytest.mark.parametrize("name", MODULES)
def test_module_imports_and_has_a_docstring(name):
    module = importlib.import_module(f"ssm3.{name}")
    assert "Design Document" in module.__doc__


def test_example_capability_file_loads():
    capability = load_capability(ROOT / "config" / "capability_example.json")
    assert set(capability) == {"positions", "parts", "limits"}
    bins = capability["positions"]["bins"]
    assert all(source in bins for source in capability["parts"].values())
