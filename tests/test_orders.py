"""Tests for the DD23 loader and the example task file."""

import copy
import json
from pathlib import Path

import pytest

from ssm3.baseline import plan_from_layout
from ssm3.capability import load_capability
from ssm3.order_check import find_ambiguity
from ssm3.orders import load_order, load_tasks, validate_task

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def data():
    cap = load_capability(ROOT / 'config/capability_kitting.json')
    return cap, load_tasks(ROOT / 'tasks/example_tasks.json', cap)


def test_examples(data):
    cap, tasks = data
    assert {t['expected']['kind'] for t in tasks} == {'plan', 'ask', 'refuse'}
    for task in tasks:
        order = task['order']
        if task['expected']['kind'] == 'ask':
            assert 'target' not in order
            unclear = find_ambiguity(order['text'], task['initial_state'], cap, {})
            assert unclear is not None
            assert find_ambiguity(order['text'], task['initial_state'], cap,
                                  {unclear[0]: task['expected']['operator_answers']}) is None
        elif task['expected']['kind'] == 'refuse':
            assert 'target' not in order
            assert find_ambiguity(order['text'], task['initial_state'], cap, {}) is None
        else:
            assert plan_from_layout(order, task['initial_state'], cap)['plan']


def test_standalone_order(data, tmp_path):
    cap, tasks = data
    path = tmp_path / 'order.json'
    path.write_text(json.dumps(tasks[0]['order']))
    assert load_order(path, cap) == tasks[0]['order']


@pytest.mark.parametrize('change', ['missing_slot', 'unknown_part', 'too_many', 'protected', 'leak'])
def test_invalid_task(data, change):
    cap, tasks = data
    task = copy.deepcopy(tasks[0])
    order = task['order']
    if change == 'missing_slot':
        del order['target']['SLOT_4']
    elif change == 'unknown_part':
        order['target']['SLOT_1'] = ['UNKNOWN']
    elif change == 'too_many':
        order['target']['SLOT_1'] *= 3
    elif change == 'protected':
        order['protected'] = ['SLOT_1']
    else:
        order['expected'] = task['expected']
    with pytest.raises(ValueError):
        validate_task(task, cap)


def test_duplicate_and_invalid_json(data, tmp_path):
    cap, tasks = data
    path = tmp_path / 'tasks.json'
    path.write_text(json.dumps([tasks[0], tasks[0]]))
    with pytest.raises(ValueError, match='duplicate'):
        load_tasks(path, cap)
    path.write_text('{')
    with pytest.raises(ValueError, match='invalid JSON'):
        load_tasks(path, cap)
