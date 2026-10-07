"""Regression tests for agent checkpoint save/load (crash recovery boundary).

These tests verify that Agent.save_checkpoint() / load_checkpoint() provide a
serializable, atomically-persisted boundary of agent state that survives a
process restart, and that transient per-step state is excluded from the
checkpoint because it cannot be safely round-tripped through JSON.
"""

import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import cast

import pytest

from browser_use import Agent
from browser_use.agent.message_manager.views import HistoryItem
from browser_use.agent.views import AgentHistory, AgentOutput, PlanItem
from browser_use.browser.views import BrowserStateHistory
from browser_use.llm.messages import SystemMessage, UserMessage
from browser_use.tokens.views import UsageSummary
from tests.ci.conftest import create_mock_llm


def _make_agent(task: str = 'Test task') -> Agent:
	"""Create an agent with a mock LLM and no running browser."""
	return Agent(task=task, llm=create_mock_llm(actions=None))


def test_save_checkpoint_creates_atomic_file():
	"""save_checkpoint() should write a JSON file and leave no temp file behind."""
	agent = _make_agent()

	with tempfile.TemporaryDirectory() as tmpdir:
		path = Path(tmpdir) / 'checkpoint.json'
		returned = agent.save_checkpoint(path)

		assert returned == path
		assert path.exists()
		# Atomic write: the .tmp sibling must be gone after the rename.
		leftover = list(path.parent.glob(f'.{path.name}.*.tmp'))
		assert not leftover, f'Leaked temp files: {leftover}'

		# The file must be valid JSON with the expected top-level shape.
		data = json.loads(path.read_text(encoding='utf-8'))
		assert set(data.keys()) == {'state', 'history'}
		assert isinstance(data['state'], dict)
		assert isinstance(data['history'], dict)


def test_checkpoint_round_trips_agent_state():
	"""State mutations before save should be observable after load."""
	agent = _make_agent()
	agent.state.n_steps = 42
	agent.state.consecutive_failures = 3
	agent.state.follow_up_task = True
	agent.state.paused = True

	with tempfile.TemporaryDirectory() as tmpdir:
		path = Path(tmpdir) / 'checkpoint.json'
		agent.save_checkpoint(path)

		# Load into a fresh agent instance.
		restored_agent = _make_agent()
		state, history = restored_agent.load_checkpoint(path)

		assert state is restored_agent.state
		assert history is restored_agent.history
		assert state.n_steps == 42
		assert state.consecutive_failures == 3
		assert state.follow_up_task is True
		assert state.paused is True
		# The in-memory agent must reflect the loaded state.
		assert restored_agent.state.n_steps == 42


@pytest.mark.parametrize('paused,stopped', [(False, False), (True, False), (False, True), (True, True)])
@pytest.mark.parametrize('initial_event_set', [False, True])
def test_checkpoint_restores_pause_event(tmp_path: Path, paused: bool, stopped: bool, initial_event_set: bool):
	"""Restored control flags must override the event, with stop taking priority."""
	agent = _make_agent()
	agent.state.paused = paused
	agent.state.stopped = stopped
	path = agent.save_checkpoint(tmp_path / 'checkpoint.json')
	restored_agent = _make_agent()
	if initial_event_set:
		restored_agent._external_pause_event.set()
	else:
		restored_agent._external_pause_event.clear()

	restored_agent.load_checkpoint(path)

	assert restored_agent._external_pause_event.is_set() is (stopped or not paused)


def test_checkpoint_excludes_transient_step_state():
	"""last_model_output / last_result must not survive the checkpoint round-trip.

	These fields hold dynamically-created ActionModel subclasses that cannot be
	deserialized from JSON, and they are recreated every step anyway (their content
	is already captured in AgentHistory). save_checkpoint() clears them.
	"""
	agent = _make_agent()

	# Populate transient per-step state with a valid AgentOutput + ActionResult.
	output = AgentOutput.model_construct(evaluation_previous_goal='prev', memory='mem', next_goal='next', action=[])
	agent.state.last_model_output = output
	agent.state.last_result = []

	with tempfile.TemporaryDirectory() as tmpdir:
		path = Path(tmpdir) / 'checkpoint.json'
		agent.save_checkpoint(path)

		# The serialized checkpoint must not carry the transient fields.
		data = json.loads(path.read_text(encoding='utf-8'))
		assert data['state']['last_model_output'] is None
		assert data['state']['last_result'] is None

		# Taking a checkpoint must not mutate the live state.
		assert agent.state.last_model_output is output
		assert agent.state.last_result == []

		# Reloading must succeed (no leftover transient data to break validation).
		restored_agent = _make_agent()
		restored_agent.load_checkpoint(path)
		assert restored_agent.state.last_model_output is None
		assert restored_agent.state.last_result is None


def test_checkpoint_persists_file_system_state():
	"""file_system_state should round-trip through the checkpoint."""
	agent = _make_agent()
	# Populate a valid serializable file system state directly (avoids async file I/O).
	file_system_state = agent.file_system.get_state()
	file_system_state.files['notes.md'] = {
		'type': 'MarkdownFile',
		'data': {'name': 'notes', 'content': '# hello\n'},
	}
	file_system_state.extracted_content_count = 1
	agent.state.file_system_state = file_system_state

	with tempfile.TemporaryDirectory() as tmpdir:
		path = Path(tmpdir) / 'checkpoint.json'
		agent.save_checkpoint(path)

		restored_agent = _make_agent()
		restored_agent.load_checkpoint(path)

		assert restored_agent.state.file_system_state is not None
		assert 'notes.md' in restored_agent.state.file_system_state.files
		assert restored_agent.state.file_system_state.extracted_content_count == 1


def test_checkpoint_persists_loop_detector_state():
	"""ActionLoopDetector state should round-trip through the checkpoint."""
	agent = _make_agent()
	agent.state.loop_detector.record_action('click', {'index': 5})
	agent.state.loop_detector.record_page_state('https://example.com', 'dom text', 10)
	assert agent.state.loop_detector.max_repetition_count >= 1
	assert len(agent.state.loop_detector.recent_page_fingerprints) >= 1

	with tempfile.TemporaryDirectory() as tmpdir:
		path = Path(tmpdir) / 'checkpoint.json'
		agent.save_checkpoint(path)

		restored_agent = _make_agent()
		restored_agent.load_checkpoint(path)

		assert restored_agent.state.loop_detector.max_repetition_count == agent.state.loop_detector.max_repetition_count
		assert len(restored_agent.state.loop_detector.recent_page_fingerprints) == len(
			agent.state.loop_detector.recent_page_fingerprints
		)


def test_checkpoint_default_path_uses_agent_id():
	"""save_checkpoint() with no path should derive one from the agent id."""
	agent = _make_agent()

	with tempfile.TemporaryDirectory() as tmpdir:
		original_cwd = Path.cwd()
		try:
			os.chdir(tmpdir)
			returned = agent.save_checkpoint()
			assert returned.name == f'agent_checkpoint_{agent.id}.json'
			assert returned.exists()
		finally:
			os.chdir(original_cwd)


def test_checkpoint_round_trips_message_manager_state():
	"""message_manager_state (including message history) should round-trip."""
	agent = _make_agent()
	# Directly mutate message manager state to avoid EventBus side effects
	# from add_new_task() on a fresh (not-yet-running) agent.
	agent.state.follow_up_task = True
	agent.state.message_manager_state.tool_id = 7
	agent.state.message_manager_state.read_state_description = 'page loaded'
	agent.state.message_manager_state.agent_history_items.append(HistoryItem(step_number=1, system_message='follow up on this'))
	message_history = agent.state.message_manager_state.history
	message_history.system_message = SystemMessage(content='Checkpoint system instructions')
	message_history.state_message = UserMessage(content='Checkpoint page state')
	message_history.context_messages = [UserMessage(content='Checkpoint context')]

	with tempfile.TemporaryDirectory() as tmpdir:
		path = Path(tmpdir) / 'checkpoint.json'
		agent.save_checkpoint(path)

		restored_agent = _make_agent()
		restored_agent.load_checkpoint(path)

		assert restored_agent.state.message_manager_state.tool_id == 7
		assert restored_agent.state.message_manager_state.read_state_description == 'page loaded'
		assert restored_agent.state.message_manager_state.agent_history_items[-1].system_message == 'follow up on this'
		restored_history = restored_agent.state.message_manager_state.history
		assert isinstance(restored_history.system_message, SystemMessage)
		assert restored_history.system_message.content == 'Checkpoint system instructions'
		assert isinstance(restored_history.state_message, UserMessage)
		assert restored_history.state_message.content == 'Checkpoint page state'
		assert len(restored_history.context_messages) == 1
		assert isinstance(restored_history.context_messages[0], UserMessage)
		assert restored_history.context_messages[0].content == 'Checkpoint context'
		# The follow-up task marker should survive.
		assert restored_agent.state.follow_up_task is True


def test_checkpoint_survives_json_round_trip():
	"""The checkpoint file must be valid JSON that can be loaded by json.load."""
	agent = _make_agent()
	agent.state.n_steps = 10
	agent.state.plan = [PlanItem(text='step 1', status='current'), PlanItem(text='step 2', status='pending')]

	with tempfile.TemporaryDirectory() as tmpdir:
		path = Path(tmpdir) / 'checkpoint.json'
		agent.save_checkpoint(path)

		# Must be parseable by plain json.load (no pydantic needed).
		data = json.loads(path.read_text(encoding='utf-8'))
		assert data['state']['n_steps'] == 10
		assert data['state']['plan'][0]['text'] == 'step 1'
		assert data['state']['plan'][0]['status'] == 'current'


@pytest.mark.parametrize('sensitive_data', [{'value': 'super-secret'}, {'example.com': {'value': 'super-secret'}}])
def test_checkpoint_preserves_usage_and_redacts_sensitive_data(sensitive_data):
	"""Checkpoint state and history redact secrets without changing live state or usage."""
	agent = _make_agent()
	agent.sensitive_data = cast(dict[str, str | dict[str, str]], sensitive_data)
	agent.state.plan = [PlanItem(text='Use super-secret', status='current')]
	agent.state.message_manager_state.history.system_message = SystemMessage(content='Password: super-secret')
	agent.state.message_manager_state.history.context_messages = [UserMessage(content='Use super-secret here')]
	agent.history.usage = UsageSummary(
		total_prompt_tokens=1,
		total_prompt_cost=0.1,
		total_prompt_cached_tokens=2,
		total_prompt_cached_cost=0.2,
		total_completion_tokens=3,
		total_completion_cost=0.3,
		total_tokens=6,
		total_cost=0.6,
		entry_count=1,
		by_model={},
	)
	input_action = agent.ActionModel.model_validate({'input': {'index': 0, 'text': 'super-secret'}})
	output = AgentOutput.model_construct(
		evaluation_previous_goal='prev',
		memory='mem',
		next_goal='next',
		action=[input_action],
	)
	agent.history.history.append(
		AgentHistory.model_construct(
			model_output=output, result=[], state=BrowserStateHistory(url='', title='', tabs=[], interacted_element=[])
		)
	)

	with tempfile.TemporaryDirectory() as tmpdir:
		path = Path(tmpdir) / 'checkpoint.json'
		agent.save_checkpoint(path)
		serialized = path.read_text(encoding='utf-8')
		assert 'super-secret' not in serialized
		assert agent.state.plan[0].text == 'Use super-secret'
		assert agent.state.message_manager_state.history.system_message.content == 'Password: super-secret'

		restored_agent = _make_agent()
		restored_agent.load_checkpoint(path)
		assert restored_agent.history.usage is not None
		assert restored_agent.history.usage.total_cost == 0.6
		assert restored_agent.state.plan is not None
		assert restored_agent.state.plan[0].text == 'Use <secret>value</secret>'
		message_history = restored_agent.state.message_manager_state.history
		assert message_history.system_message is not None
		assert message_history.system_message.content == 'Password: <secret>value</secret>'
		assert message_history.context_messages[0].content == 'Use <secret>value</secret> here'


def test_checkpoint_saves_to_same_path_concurrently():
	"""Concurrent writers use independent temporary files and do not collide."""
	agent = _make_agent()

	with tempfile.TemporaryDirectory() as tmpdir:
		path = Path(tmpdir) / 'checkpoint.json'
		with ThreadPoolExecutor(max_workers=2) as executor:
			list(executor.map(agent.save_checkpoint, [path, path]))
		assert json.loads(path.read_text(encoding='utf-8'))['state']['agent_id'] == agent.state.agent_id
