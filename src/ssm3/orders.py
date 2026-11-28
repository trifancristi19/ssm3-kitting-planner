"""Load DD23 orders and proposed Study 2 task files without running the cell.

Structured orders carry a target; plain-language orders do not. Expected
results are kept separate from the order passed to the planner.
"""

import json
from pathlib import Path

from ssm3.cell import level_names


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _parts(parts, capability, label, limit=None):
    _require(isinstance(parts, list), f"{label} must be a list")
    _require(limit is None or len(parts) <= limit, f"{label} exceeds capacity")
    for part in parts:
        _require(isinstance(part, str) and part in capability['parts'], f"{label}: unknown part {part!r}")


def _tray(tray, capability, label):
    _require(isinstance(tray, dict), f"{label} must be an object")
    _require(set(tray) == set(capability['positions']['slots']), f"{label} must name every tray slot exactly")
    for slot, parts in tray.items():
        _parts(parts, capability, f"{label}.{slot}", len(level_names(capability)))


def validate_order(order, capability):
    """Validate a plain-language or structured DD23 order; return the order."""
    _require(isinstance(order, dict), 'order must be an object')
    for field in ('order_id', 'text'):
        _require(isinstance(order.get(field), str) and bool(order[field].strip()), f"{field} must be non-empty text")
    _require(set(order) <= {'order_id', 'text', 'target', 'protected'}, 'unknown order field')
    protected = order.get('protected', [])
    _require(isinstance(protected, list), 'protected must be a list')
    for slot in protected:
        _require(slot in capability['positions']['slots'], f"unknown protected slot {slot!r}")
    _require(len(set(protected)) == len(protected), 'duplicate protected slot')
    if 'target' in order:
        _tray(order['target'], capability, 'target')
    return order


def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except json.JSONDecodeError as error:
        raise ValueError(f"{path}: invalid JSON: {error}") from error


def load_order(path, capability):
    """Read one standalone DD23 order JSON object."""
    return validate_order(_read(path), capability)


def validate_task(task, capability):
    """Validate a task, including its starting state and evaluation metadata."""
    _require(isinstance(task, dict), 'task must be an object')
    _require(set(task) == {'order', 'initial_state', 'expected'}, 'task needs order, initial_state and expected')
    order = validate_order(task['order'], capability)
    state = task['initial_state']
    positions = capability['positions']
    _require(isinstance(state, dict) and set(state) == {'bins', 'slots', 'return', 'gripper', 'arm'},
             'initial_state must contain bins, slots, return, gripper and arm')
    _tray(state['slots'], capability, 'initial_state.slots')
    _require(isinstance(state['bins'], dict) and set(state['bins']) == set(positions['bins']),
             'initial_state.bins must name every bin')
    for bin_name, parts in state['bins'].items():
        _parts(parts, capability, bin_name)
        _require(all(capability['parts'][part] == bin_name for part in parts), f"wrong part in {bin_name}")
    _parts(state['return'], capability, 'return', capability['limits']['return_capacity'])
    _require(state['gripper'] is None or state['gripper'] in capability['parts'], 'unknown gripper part')
    _require(state['arm'] in [positions['home'], *positions['bins'], *positions['slots'], positions['return']],
             'unknown arm position')
    expected = task['expected']
    _require(isinstance(expected, dict) and set(expected) == {'kind', 'target', 'operator_answers'},
             'expected needs kind, target and operator_answers')
    _require(expected['kind'] in ('plan', 'ask', 'refuse'), 'unknown expected kind')
    _tray(expected['target'], capability, 'expected.target')
    answers = expected['operator_answers']
    _require(isinstance(answers, list) and all(isinstance(a, str) for a in answers),
             'operator_answers must be a list of strings')
    if 'target' in order:
        _require(order['target'] == expected['target'], 'structured target differs from expected target')
    for slot in order.get('protected', []):
        _require(expected['target'][slot] == state['slots'][slot], f"expected result changes protected slot {slot}")
    if expected['kind'] == 'refuse':
        _require(expected['target'] == state['slots'], 'refuse task must leave tray unchanged')
    return task


def load_tasks(path, capability):
    """Read a task array; reject duplicate IDs and malformed tasks."""
    tasks = _read(path)
    _require(isinstance(tasks, list) and bool(tasks), 'task file must be a non-empty JSON array')
    seen = set()
    for index, task in enumerate(tasks):
        try:
            validate_task(task, capability)
            order_id = task['order']['order_id']
            _require(order_id not in seen, f"duplicate order_id {order_id!r}")
            seen.add(order_id)
        except (ValueError, TypeError) as error:
            raise ValueError(f"{path}: task {index + 1}: {error}") from error
    return tasks
