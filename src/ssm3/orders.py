"""Load structured orders and task files (Design Document, DD23).

The agreed flat format includes operator_answers (DD15, DD25) and a starting
initial_state (DD23) for each task. A caller may supply starting states separately.
A refuse target must break a DD25 rule: slot capacity, known parts or protected
slots. It must still have the correct tray shape. The checker blocks execution.
Only the plain-language view is passed to the LLM loop (DD23, DD26).
"""

import json
from copy import deepcopy
from pathlib import Path

from ssm3.cell import level_names
from ssm3.checker import rule_override, tray_shape_problem
from ssm3.order_check import answer_selection, find_ambiguity

ORDER_FIELDS = ('order_id', 'kit_id', 'text', 'target', 'protected')
TASK_FIELDS = (*ORDER_FIELDS, 'expected_outcome', 'expected_tray')
ADDITIONAL_FIELDS = ('operator_answers', 'initial_state')


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _parts(parts, capability, label, limit=None):
    _require(isinstance(parts, list), f'{label} must be a list')
    _require(limit is None or len(parts) <= limit, f'{label} exceeds capacity')
    for part in parts:
        _require(isinstance(part, str) and part in capability['parts'], f'{label}: unknown part {part!r}')


def _tray(tray, capability, label):
    _require(isinstance(tray, dict), f'{label} must be an object')
    _require(set(tray) == set(capability['positions']['slots']), f'{label} must name every tray slot exactly')
    for slot, parts in tray.items():
        _parts(parts, capability, f'{label}.{slot}', len(level_names(capability)))


def validate_order(order, capability, recipes=None, *, allow_rule_override=False):
    """Validate the five DD23 fields; accept a target, a kit ID or both.

    Only refuse tasks may opt into a shape-only requested target check. Recipes,
    expected trays and starting states always contain known parts within capacity.
    """
    _require(isinstance(order, dict), 'order must be an object')
    _require(set(order) <= set(ORDER_FIELDS), 'unknown order field')
    _require(set(ORDER_FIELDS) <= set(order), 'missing DD23 order field')
    for field in ('order_id', 'text'):
        _require(isinstance(order[field], str) and bool(order[field].strip()), f'{field} must be non-empty text')
    kit_id = order['kit_id']
    _require(isinstance(kit_id, str), 'kit_id must be text, empty for a one-off change')
    protected = order['protected']
    _require(isinstance(protected, list), 'protected must be a list')
    for slot in protected:
        _require(isinstance(slot, str) and slot in capability['positions']['slots'],
                 f'unknown protected slot {slot!r}')
    _require(len(set(protected)) == len(protected), 'duplicate protected slot')
    target = order['target']
    _require(isinstance(target, dict), 'target must be an object')
    _require(bool(target or kit_id), 'a structured order needs a kit_id or a target (DD23)')
    if target:
        if allow_rule_override:
            shape = tray_shape_problem(target, capability)
            _require(shape is None, f'target: {shape}')
        else:
            _tray(target, capability, 'target')
    if kit_id:
        _require(recipes is not None, f'kit_id {kit_id!r} needs a recipe table')
        _require(isinstance(recipes, dict) and kit_id in recipes, f'unknown kit_id {kit_id!r} in recipe table')
        _tray(recipes[kit_id], capability, f'recipe {kit_id}')
        _require(not target or target == recipes[kit_id], f'target differs from recipe {kit_id}')
    return order


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, f'duplicate JSON key {key!r}')
        result[key] = value
    return result


def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=_unique_object)
    except ValueError as error:
        raise ValueError(f'{path}: invalid JSON: {error}') from error


def load_order(path, capability, recipes=None):
    """Read a standalone DD23 order JSON object."""
    return validate_order(_read(path), capability, recipes)


def planner_order(task):
    """Return only the plain-language order; never expose the structured target.

    Pass its protected list separately as run_order(..., protected=order['protected']).
    """
    return deepcopy({key: task[key] for key in ('order_id', 'text', 'protected')})


def baseline_order(task):
    """Return the structured order for the non-LLM baseline."""
    return deepcopy({key: task[key] for key in ('order_id', 'kit_id', 'target', 'protected')})


def evaluator_task(task):
    """Return the evaluator branch's seven fields, without runner metadata."""
    return deepcopy({key: task[key] for key in TASK_FIELDS})


def _validate_state(state, capability):
    positions = capability['positions']
    _require(isinstance(state, dict) and set(state) == {'bins', 'slots', 'return', 'gripper', 'arm'},
             'initial_state must contain bins, slots, return, gripper and arm')
    _tray(state['slots'], capability, 'initial_state.slots')
    _require(isinstance(state['bins'], dict) and set(state['bins']) == set(positions['bins']),
             'initial_state.bins must name every bin')
    for bin_name, parts in state['bins'].items():
        _parts(parts, capability, bin_name)
        _require(all(capability['parts'][part] == bin_name for part in parts), f'wrong part in {bin_name}')
    _parts(state['return'], capability, 'return', capability['limits']['return_capacity'])
    held = state['gripper']
    _require(held is None or isinstance(held, str) and held in capability['parts'], 'unknown gripper part')
    _require(state['arm'] in [positions['home'], *positions['bins'], *positions['slots'], positions['return']],
             'unknown arm position')


def validate_outcome(task, state, capability, target=None):
    """Check the text and answers using the same order check as the orchestrator.

    The resolved part must agree with the named slot in the structured target.
    This is a consistency check, not a full interpretation of the instruction.
    """
    answers = task.get('operator_answers', [])
    outcome = task['expected_outcome']
    unclear = find_ambiguity(task['text'], state, capability, {})
    if outcome != 'ask':
        _require(unclear is None, f'{outcome} task is ambiguous: {unclear}')
        return
    _require(unclear is not None, 'ask task does not trigger an ambiguity question')
    target = task['target'] if target is None else target
    supplied = {}
    for answer in answers:
        _require(unclear is not None, 'unused operator answer')
        number = unclear[0]
        _require(number not in supplied, 'operator answer did not settle the question')
        part, source, destination = answer_selection(task['text'], state, capability, number, answer)
        _require(part is not None, 'operator answer did not settle the question')
        if destination is not None:
            agrees = part in target[destination]
        elif source is not None:
            agrees = True  # A removal is checked against the source below.
        else:
            # If the text names no slot, only a changed slot (or a no-op tray) can
            # support the answer. An unrelated unchanged slot is not evidence.
            changed = [slot for slot in target if target[slot] != state['slots'][slot]]
            agrees = any(part in target[slot] for slot in changed or target)
        if source is not None:
            agrees = agrees and state['slots'][source].count(part) > target[source].count(part)
        _require(agrees, f'operator answer {answer!r} selects {part}, which contradicts the target')
        supplied[number] = [answer]
        unclear = find_ambiguity(task['text'], state, capability, supplied)
        _require(unclear is None or unclear[0] != number, 'operator answer did not settle the question')
    _require(unclear is None, 'operator answers do not settle every question')


def validate_task(task, capability, recipes=None, initial_state=None):
    """Validate DD23 task fields and outcomes against a required starting state."""
    _require(isinstance(task, dict), 'task must be an object')
    _require(set(TASK_FIELDS) <= set(task), 'missing DD23 task field')
    _require(set(task) <= set((*TASK_FIELDS, *ADDITIONAL_FIELDS)), 'unknown task field')
    outcome = task['expected_outcome']
    _require(outcome in ('done', 'ask', 'refuse'), 'unknown expected_outcome')
    order = validate_order({key: task[key] for key in ORDER_FIELDS}, capability, recipes,
                           allow_rule_override=outcome == 'refuse')
    target = order['target'] or recipes[order['kit_id']]
    tray = task['expected_tray']
    _require(isinstance(tray, dict) and 'slots' in tray and set(tray) <= {'slots', 'return'},
             'expected_tray needs slots and may include return')
    _tray(tray['slots'], capability, 'expected_tray.slots')
    if 'return' in tray:
        _parts(tray['return'], capability, 'expected_tray.return', capability['limits']['return_capacity'])
    if outcome != 'refuse':
        _require(target == tray['slots'], 'structured target differs from expected tray')
    else:
        _require(target != tray['slots'], 'refuse task must request a different tray')
    answers = task.get('operator_answers', [])
    _require(isinstance(answers, list) and all(isinstance(a, str) and a.strip() for a in answers),
             'operator_answers must be a list of non-empty strings')
    _require(bool(answers) == (outcome == 'ask'), 'only ask tasks need operator_answers')
    if 'initial_state' in task and initial_state is not None:
        _require(task['initial_state'] == initial_state, 'conflicting starting states')
    if 'initial_state' in task:
        _require(task['initial_state'] is not None, 'initial_state must be an object')
    state = task.get('initial_state', initial_state)
    _require(state is not None, 'every task needs a starting state to check its outcome')
    _validate_state(state, capability)
    for slot in order['protected']:
        _require(tray['slots'][slot] == state['slots'][slot], f'expected result changes protected slot {slot}')
    violation = rule_override(target, state, capability, order['protected'])
    if outcome == 'refuse':
        _require(violation is not None, 'refuse target must break a RULE_OVERRIDE rule (DD25)')
        _require(tray['slots'] == state['slots'], 'refuse task must leave tray unchanged')
        if 'return' in tray:
            _require(tray['return'] == state['return'], 'refuse task must leave return unchanged')
    else:
        _require(violation is None, f'{outcome} target breaks a rule: {violation}')
    validate_outcome(task, state, capability, target)
    return task


def load_tasks(path, capability, recipes=None, initial_states=None):
    """Read a flat JSON object keyed by order ID, optionally with separate start states."""
    tasks = _read(path)
    _require(isinstance(tasks, dict) and bool(tasks), 'task file must be a non-empty JSON object')
    for order_id, task in tasks.items():
        try:
            _require(isinstance(task, dict) and task.get('order_id') == order_id,
                     'order_id must equal its JSON key')
            state = None if initial_states is None else initial_states.get(order_id)
            validate_task(task, capability, recipes, state)
        except (ValueError, TypeError) as error:
            raise ValueError(f'{path}: task {order_id}: {error}') from error
    return tasks
