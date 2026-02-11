"""Tests for the todo_write action — task management tool."""

import json

from browser_use.agent.views import ActionResult
from browser_use.tools.service import Tools
from browser_use.tools.todo.views import TodoItem, TodoStats, TodoWriteAction


# ─── Helpers ───────────────────────────────────────────────────────────────────


def _make_tools() -> Tools:
	"""Create a fresh Tools instance with todo_write registered."""
	return Tools()


async def _execute_todo_write(tools: Tools, todos_data: list[dict], replan: bool = False, replan_reason: str | None = None) -> ActionResult:
	"""Execute todo_write through the registry."""
	params_dict = {'todos': todos_data, 'replan': replan}
	if replan_reason is not None:
		params_dict['replan_reason'] = replan_reason

	result = await tools.registry.execute_action(
		action_name='todo_write',
		params=params_dict,
	)
	assert isinstance(result, ActionResult)
	return result


# ─── Basic write ───────────────────────────────────────────────────────────────


async def test_todo_write_basic():
	"""Writing a simple todo list should succeed and update get_todos()."""
	tools = _make_tools()

	result = await _execute_todo_write(tools, [
		{'content': 'Set up project', 'status': 'in_progress', 'activeForm': 'Setting up project'},
		{'content': 'Write tests', 'status': 'pending', 'activeForm': 'Writing tests'},
	])

	assert result.error is None
	assert 'Total: 2' in result.extracted_content
	assert 'In Progress: 1' in result.extracted_content
	assert 'Pending: 1' in result.extracted_content

	todos = tools.get_todos()
	assert len(todos) == 2
	assert todos[0].content == 'Set up project'
	assert todos[0].status == 'in_progress'
	assert todos[0].active_form == 'Setting up project'
	assert todos[1].status == 'pending'


async def test_todo_write_replaces_list():
	"""Each call fully replaces the todo list."""
	tools = _make_tools()

	await _execute_todo_write(tools, [
		{'content': 'Task A', 'status': 'pending', 'activeForm': 'Doing A'},
		{'content': 'Task B', 'status': 'pending', 'activeForm': 'Doing B'},
	])
	assert len(tools.get_todos()) == 2

	await _execute_todo_write(tools, [
		{'content': 'Task C', 'status': 'completed', 'activeForm': 'Doing C'},
	])
	assert len(tools.get_todos()) == 1
	assert tools.get_todos()[0].content == 'Task C'


# ─── Replan ────────────────────────────────────────────────────────────────────


async def test_todo_write_replan():
	"""replan=True should note the old plan was discarded."""
	tools = _make_tools()

	# First write
	await _execute_todo_write(tools, [
		{'content': 'Old task', 'status': 'pending', 'activeForm': 'Doing old task'},
	])

	# Replan
	result = await _execute_todo_write(
		tools,
		[{'content': 'New approach', 'status': 'pending', 'activeForm': 'Trying new approach'}],
		replan=True,
		replan_reason='Old approach was infeasible',
	)

	assert result.error is None
	assert 'Plan rewritten' in result.extracted_content
	assert 'Old approach was infeasible' in result.extracted_content
	assert len(tools.get_todos()) == 1


async def test_todo_write_replan_on_empty_is_normal():
	"""replan=True on an empty list should just be a normal write."""
	tools = _make_tools()

	result = await _execute_todo_write(
		tools,
		[{'content': 'First task', 'status': 'pending', 'activeForm': 'Doing first task'}],
		replan=True,
		replan_reason='Nothing to replan',
	)

	assert result.error is None
	# No "Plan rewritten" since there were no old todos
	assert 'Todos updated' in result.extracted_content


# ─── Empty list ────────────────────────────────────────────────────────────────


async def test_todo_write_empty_list():
	"""Writing an empty list should clear all todos."""
	tools = _make_tools()

	await _execute_todo_write(tools, [
		{'content': 'Task', 'status': 'pending', 'activeForm': 'Doing task'},
	])
	assert len(tools.get_todos()) == 1

	result = await _execute_todo_write(tools, [])
	assert result.error is None
	assert 'Total: 0' in result.extracted_content
	assert len(tools.get_todos()) == 0


# ─── Stats ─────────────────────────────────────────────────────────────────────


async def test_todo_stats():
	"""Stats should accurately reflect the state of the todo list."""
	tools = _make_tools()

	await _execute_todo_write(tools, [
		{'content': 'A', 'status': 'completed', 'activeForm': 'Doing A'},
		{'content': 'B', 'status': 'completed', 'activeForm': 'Doing B'},
		{'content': 'C', 'status': 'in_progress', 'activeForm': 'Doing C'},
		{'content': 'D', 'status': 'pending', 'activeForm': 'Doing D'},
		{'content': 'E', 'status': 'pending', 'activeForm': 'Doing E'},
	])

	stats = tools._get_todo_stats()
	assert stats.total == 5
	assert stats.completed == 2
	assert stats.in_progress == 1
	assert stats.pending == 2


# ─── get_todos returns copies ──────────────────────────────────────────────────


async def test_get_todos_returns_copy():
	"""get_todos() should return a copy, not the internal list."""
	tools = _make_tools()

	await _execute_todo_write(tools, [
		{'content': 'Task', 'status': 'pending', 'activeForm': 'Doing task'},
	])

	external = tools.get_todos()
	external.clear()  # mutate the returned list

	assert len(tools.get_todos()) == 1  # internal list unchanged


# ─── Registration / exclusion ──────────────────────────────────────────────────


def test_todo_write_registered_by_default():
	"""todo_write should be registered by default."""
	tools = Tools()
	assert 'todo_write' in tools.registry.registry.actions


def test_todo_write_can_be_excluded():
	"""todo_write can be excluded via exclude_actions."""
	tools = Tools(exclude_actions=['todo_write'])
	assert 'todo_write' not in tools.registry.registry.actions


def test_todo_write_exclude_after_init():
	"""todo_write can be excluded after init."""
	tools = Tools()
	tools.exclude_action('todo_write')
	assert 'todo_write' not in tools.registry.registry.actions
