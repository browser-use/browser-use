"""Regression test for MessageManager state isolation.

MessageManager.__init__ used a mutable default argument `state=MessageManagerState()`,
which is evaluated once at definition time and therefore shared by every MessageManager
created without an explicit state. History (`agent_history_items`, etc.) then leaked
across otherwise-independent instances.
"""

import tempfile

from browser_use.agent.message_manager.service import MessageManager
from browser_use.agent.views import MessageManagerState
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm import SystemMessage


def _make_manager(task: str) -> MessageManager:
	return MessageManager(
		task=task,
		system_message=SystemMessage(content='system'),
		file_system=FileSystem(tempfile.mkdtemp()),
	)


def test_managers_get_independent_state():
	mm1 = _make_manager('task one')
	mm2 = _make_manager('task two')

	assert mm1.state is not mm2.state
	assert mm1.state.agent_history_items is not mm2.state.agent_history_items


def test_mutating_one_manager_does_not_affect_another():
	mm1 = _make_manager('task one')
	mm2 = _make_manager('task two')

	mm1.add_new_task('do X only in agent 1')

	leaked = any('do X only in agent 1' in (item.system_message or '') for item in mm2.state.agent_history_items)
	assert not leaked
	assert '<follow_up_user_request>' not in mm2.task


def test_explicit_state_is_used_as_is():
	shared = MessageManagerState()
	mm = MessageManager(
		task='task',
		system_message=SystemMessage(content='system'),
		file_system=FileSystem(tempfile.mkdtemp()),
		state=shared,
	)
	assert mm.state is shared
