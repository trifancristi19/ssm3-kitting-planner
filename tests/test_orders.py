"""Tests for the DD23 loader, agreed task format and outcome checks."""

import copy
import json
from pathlib import Path

import pytest

from ssm3.baseline import plan_from_layout
from ssm3.capability import load_capability
from ssm3.cell import SimulatedCell
from ssm3.checker import check, rule_override
from ssm3.console import ScriptedOperator
from ssm3.logger import RunLog
from ssm3.orchestrator import run_order
from ssm3.orders import (
    baseline_order,
    evaluator_task,
    load_order,
    load_tasks,
    planner_order,
    validate_order,
    validate_outcome,
    validate_task,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def data():
    cap = load_capability(ROOT / 'config/capability_kitting.json')
    return cap, load_tasks(ROOT / 'config/example_tasks.json', cap)


def test_examples(data):
    cap, tasks = data
    assert {t['expected_outcome'] for t in tasks.values()} == {'done', 'ask', 'refuse'}
    for task in tasks.values():
        assert task['target']
        validate_outcome(task, task['initial_state'], cap)
        if task['expected_outcome'] == 'refuse':
            assert task['target'] != task['expected_tray']['slots'] == task['initial_state']['slots']
        else:
            assert plan_from_layout(baseline_order(task), task['initial_state'], cap)['plan']


def test_views(data):
    _, tasks = data
    for task in tasks.values():
        plain = planner_order(task)
        assert set(plain) == {'order_id', 'text', 'protected'}
        assert set(baseline_order(task)) == {'order_id', 'kit_id', 'target', 'protected'}
        assert set(evaluator_task(task)) == {
            'order_id', 'kit_id', 'text', 'target', 'protected', 'expected_outcome', 'expected_tray',
        }
        plain['protected'].append('SLOT_4')
        assert 'SLOT_4' not in task['protected']


def test_standalone_order(data, tmp_path):
    cap, tasks = data
    order = {**baseline_order(tasks['EX-PLAN-01']), 'text': tasks['EX-PLAN-01']['text']}
    path = tmp_path / 'order.json'
    path.write_text(json.dumps(order), encoding='utf-8')
    assert load_order(path, cap) == order


@pytest.mark.parametrize('change, message', [
    ('missing_recipe', 'needs a recipe table'),
    ('unknown_kit', 'unknown kit_id'),
    ('mismatch', 'differs from recipe'),
    ('neither', 'needs a kit_id or a target'),
])
def test_invalid_recipe_order(data, change, message):
    cap, tasks = data
    order = {**baseline_order(tasks['EX-PLAN-01']), 'text': tasks['EX-PLAN-01']['text']}
    recipes = {'KIT_A': copy.deepcopy(order['target'])}
    order['kit_id'] = 'KIT_A'
    if change == 'missing_recipe':
        recipes = None
    elif change == 'unknown_kit':
        order['kit_id'] = 'UNKNOWN'
    elif change == 'mismatch':
        order['target']['SLOT_1'] = []
    else:
        order.update(kit_id='', target={})
    with pytest.raises(ValueError, match=message):
        validate_order(order, cap, recipes)


@pytest.mark.parametrize('with_target', [True, False])
def test_recipe_order(data, with_target):
    cap, tasks = data
    task = copy.deepcopy(tasks['EX-PLAN-01'])
    recipes = {'KIT_A': copy.deepcopy(task['target'])}
    task['kit_id'] = 'KIT_A'
    if not with_target:
        task['target'] = {}
    assert validate_task(task, cap, recipes) == task


@pytest.mark.parametrize('change', ['missing_slot', 'unknown_part', 'too_many', 'protected', 'leak',
                                   'wrong_bin', 'bad_arm', 'bad_gripper', 'return_full'])
def test_invalid_task(data, change):
    cap, tasks = data
    task = copy.deepcopy(tasks['EX-PLAN-01'])
    if change == 'missing_slot':
        del task['target']['SLOT_4']
    elif change == 'unknown_part':
        task['target']['SLOT_1'] = ['UNKNOWN']
    elif change == 'too_many':
        task['target']['SLOT_1'] *= 3
    elif change == 'protected':
        task['protected'] = ['SLOT_1']
    elif change == 'leak':
        task['expected'] = task['expected_tray']
    elif change == 'wrong_bin':
        task['initial_state']['bins']['BIN_1'] = ['BRICK_2X4_RED']
    elif change == 'bad_arm':
        task['initial_state']['arm'] = 'UNKNOWN'
    elif change == 'bad_gripper':
        task['initial_state']['gripper'] = 'UNKNOWN'
    else:
        task['initial_state']['return'] = ['BRICK_2X2_RED'] * (cap['limits']['return_capacity'] + 1)
    with pytest.raises(ValueError):
        validate_task(task, cap)


@pytest.mark.parametrize('change', ['no_answer', 'wrong_answer', 'ambiguous_done', 'ambiguous_refuse',
                                   'clear_ask', 'extra_answer', 'wrong_expected_tray', 'same_refuse_target'])
def test_invalid_outcome(data, change):
    cap, tasks = data
    task = copy.deepcopy(tasks['ASK-01'])
    if change == 'no_answer':
        task['operator_answers'] = []
    elif change == 'wrong_answer':
        task['operator_answers'] = ['red']
    elif change == 'ambiguous_done':
        task['expected_outcome'] = 'done'
        task['operator_answers'] = []
    elif change == 'ambiguous_refuse':
        task = copy.deepcopy(tasks['REFUSE-01'])
        task['text'] = 'Put the red brick in slot 1.'
    elif change == 'clear_ask':
        task['text'] = 'Put BRICK_2X2_RED in SLOT_1.'
    elif change == 'extra_answer':
        task['operator_answers'].append('2x2')
    elif change == 'wrong_expected_tray':
        task = copy.deepcopy(tasks['REFUSE-01'])
        task['expected_tray']['slots']['SLOT_2'] = ['BRICK_2X2_RED']
    else:
        task = copy.deepcopy(tasks['REFUSE-01'])
        task['target'] = copy.deepcopy(task['expected_tray']['slots'])
    with pytest.raises(ValueError):
        validate_task(task, cap)


def test_separate_start_state(data, tmp_path):
    cap, tasks = data
    task = copy.deepcopy(tasks['ASK-01'])
    state = task.pop('initial_state')
    path = tmp_path / 'tasks.json'
    path.write_text(json.dumps({'ASK-01': task}), encoding='utf-8')
    with pytest.raises(ValueError, match='starting state'):
        load_tasks(path, cap)
    assert load_tasks(path, cap, initial_states={'ASK-01': state}) == {'ASK-01': task}


def test_duplicate_and_invalid_json(data, tmp_path):
    cap, tasks = data
    path = tmp_path / 'tasks.json'
    task = json.dumps(tasks['EX-PLAN-01'])
    path.write_text('{"EX-PLAN-01": ' + task + ', "EX-PLAN-01": ' + task + '}', encoding='utf-8')
    with pytest.raises(ValueError, match='duplicate'):
        load_tasks(path, cap)
    path.write_text('{', encoding='utf-8')
    with pytest.raises(ValueError, match='invalid JSON'):
        load_tasks(path, cap)
    path.write_text(json.dumps({'WRONG': tasks['EX-PLAN-01']}), encoding='utf-8')
    with pytest.raises(ValueError, match='JSON key'):
        load_tasks(path, cap)


@pytest.mark.parametrize('task_id', ['EX-PLAN-01', 'ASK-01', 'ASK-02', 'REFUSE-01', 'REFUSE-02', 'REFUSE-03'])
def test_example_in_orchestrator(data, task_id):
    cap, tasks = data
    task = tasks[task_id]
    state = task['initial_state']
    order = planner_order(task)
    baseline = baseline_order(task)
    outcome = task['expected_outcome']
    if task_id in ('REFUSE-01', 'REFUSE-03'):
        with pytest.raises(ValueError):
            plan_from_layout(baseline, state, cap)
        plan = []  # An invalid target is rejected before any step is checked.
    else:
        plan = plan_from_layout(baseline, state, cap)['plan']
    operator = ScriptedOperator(task['operator_answers'])
    log = RunLog(task_id)
    if outcome == 'refuse':
        # Even a planner that initially tries the prohibited target cannot move the cell.
        verdict = check(plan, state, cap, protected=order['protected'], target=baseline['target'])
        assert verdict['code'] == 'RULE_OVERRIDE'
        replies = iter([{'plan': plan, 'target': baseline['target']}, {'refuse': verdict['reason']}])
    else:
        replies = iter([{'plan': plan, 'target': baseline['target']}])

    def fake_planner(text, current_state, capability, history):
        assert text == task['text']
        assert current_state == state
        assert capability == cap
        if outcome == 'ask':
            assert history[0]['answer'] == task['operator_answers'][0]
        return json.dumps(next(replies))

    result = run_order(order, 'open loop', planner=fake_planner, cell=SimulatedCell(cap, state),
                       operator=operator, log=log, protected=order['protected'])
    assert result['outcome'] == ('refused' if outcome == 'refuse' else 'done')
    assert result['final_state']['slots'] == task['expected_tray']['slots']
    assert result['interventions'] == int(outcome == 'ask')
    if outcome == 'refuse':
        assert result['steps_run'] == 0
        assert result['final_state'] == state
        assert any(record.get('code') == 'RULE_OVERRIDE' for record in log.of_kind('check_result'))


@pytest.mark.parametrize('task_id', ['EX-PLAN-01', 'ASK-01', 'REFUSE-01'])
def test_start_state_required(data, tmp_path, task_id):
    cap, tasks = data
    task = copy.deepcopy(tasks[task_id])
    state = task.pop('initial_state')
    path = tmp_path / 'tasks.json'
    path.write_text(json.dumps({task_id: task}), encoding='utf-8')
    with pytest.raises(ValueError, match='starting state'):
        load_tasks(path, cap)
    assert load_tasks(path, cap, initial_states={task_id: state}) == {task_id: task}


@pytest.mark.parametrize('answer', ['2x4', 'BRICK_2X4_RED', 'the bigger one'])
def test_answer_contradicts_target(data, answer):
    cap, tasks = data
    task = copy.deepcopy(tasks['ASK-01'])
    task['operator_answers'] = [answer]
    with pytest.raises(ValueError, match='contradicts the target'):
        validate_task(task, cap)


def test_answer_must_match_destination_not_another_slot(data):
    cap, tasks = data
    task = copy.deepcopy(tasks['ASK-01'])
    task['target']['SLOT_1'] = ['BRICK_2X4_RED']
    task['target']['SLOT_2'] = ['BRICK_2X2_RED']
    task['expected_tray']['slots'] = copy.deepcopy(task['target'])
    with pytest.raises(ValueError, match='contradicts the target'):
        validate_task(task, cap)


@pytest.mark.parametrize('task_id, reason', [
    ('REFUSE-01', '3 parts in SLOT_1'),
    ('REFUSE-02', 'which the order protects'),
    ('REFUSE-03', 'PART_X99'),
])
def test_refuse_rule_matches_checker(data, task_id, reason):
    cap, tasks = data
    task = tasks[task_id]
    violation = rule_override(task['target'], task['initial_state'], cap, task['protected'])
    result = check([], task['initial_state'], cap, protected=task['protected'], target=task['target'])
    assert result['code'] == 'RULE_OVERRIDE'
    assert violation == result['reason']
    assert reason in violation


def test_refuse_without_a_rule_violation(data):
    cap, tasks = data
    task = copy.deepcopy(tasks['REFUSE-02'])
    task['protected'] = []
    with pytest.raises(ValueError, match='RULE_OVERRIDE'):
        validate_task(task, cap)


def test_refuse_with_only_kit_id(data):
    cap, tasks = data
    task = copy.deepcopy(tasks['REFUSE-02'])
    recipes = {'KIT_A': copy.deepcopy(task['target'])}
    task.update(kit_id='KIT_A', target={})
    assert validate_task(task, cap, recipes) == task
    task['protected'] = []
    with pytest.raises(ValueError, match='RULE_OVERRIDE'):
        validate_task(task, cap, recipes)


@pytest.mark.parametrize('change', ['missing_slot', 'extra_slot', 'not_a_list', 'not_a_string'])
def test_refuse_still_requires_tray_shape(data, change):
    cap, tasks = data
    task = copy.deepcopy(tasks['REFUSE-01'])
    if change == 'missing_slot':
        del task['target']['SLOT_4']
    elif change == 'extra_slot':
        task['target']['SLOT_5'] = []
    elif change == 'not_a_list':
        task['target']['SLOT_4'] = 'BRICK_2X2_RED'
    else:
        task['target']['SLOT_4'] = [42]
    with pytest.raises(ValueError, match='target'):
        validate_task(task, cap)


def test_two_answers_match_their_own_slots(data):
    cap, tasks = data
    task = copy.deepcopy(tasks['ASK-01'])
    task['text'] = 'Put the red brick in slot 1 and the blue brick in slot 2.'
    task['target']['SLOT_2'] = ['BRICK_2X4_BLUE']
    task['expected_tray']['slots'] = copy.deepcopy(task['target'])
    task['operator_answers'] = ['2x2', '2x4']
    assert validate_task(task, cap) == task
    task['operator_answers'].reverse()
    with pytest.raises(ValueError, match='contradicts the target'):
        validate_task(task, cap)


def test_ask_recipe_only_checks_resolved_target(data):
    cap, tasks = data
    task = copy.deepcopy(tasks['ASK-01'])
    recipes = {'KIT_A': copy.deepcopy(task['target'])}
    task.update(kit_id='KIT_A', target={})
    assert validate_task(task, cap, recipes) == task
    task['operator_answers'] = ['2x4']
    with pytest.raises(ValueError, match='contradicts the target'):
        validate_task(task, cap, recipes)


def test_ambiguous_done_file_with_start_state_is_rejected(data, tmp_path):
    cap, tasks = data
    task = copy.deepcopy(tasks['EX-PLAN-01'])
    task['text'] = 'Put the red brick in slot 1.'
    path = tmp_path / 'tasks.json'
    path.write_text(json.dumps({task['order_id']: task}), encoding='utf-8')
    with pytest.raises(ValueError, match='done task is ambiguous'):
        load_tasks(path, cap)
