from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from browser_use.agent.message_manager.service import MessageManager
from browser_use.agent.message_manager.views import HistoryItem
from browser_use.agent.views import AgentStepInfo, MessageCompactionSettings
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm import BaseChatModel, SystemMessage
from browser_use.llm.views import ChatInvokeCompletion


@pytest.mark.asyncio
async def test_zero_trigger_char_count_compacts_when_step_interval_is_reached(tmp_path: Path):
	manager = MessageManager(
		task='test task',
		system_message=SystemMessage(content='system'),
		file_system=FileSystem(tmp_path),
	)
	llm = AsyncMock(spec=BaseChatModel)
	llm.ainvoke.return_value = ChatInvokeCompletion(completion='Compacted history', usage=None)
	settings = MessageCompactionSettings(compact_every_n_steps=1, trigger_char_count=0)

	compacted = await manager.maybe_compact_messages(
		llm=llm,
		settings=settings,
		step_info=AgentStepInfo(step_number=1, max_steps=10),
	)

	assert compacted is True
	llm.ainvoke.assert_awaited_once()
	assert manager.state.compacted_memory == 'Compacted history'


@pytest.mark.asyncio
async def test_failed_compaction_is_throttled_by_step_interval(tmp_path: Path):
	"""A persistently failing compaction LLM must not retry on every step.

	Before the fix, last_compaction_step was only advanced on success, so once
	both gates passed (step interval reached + history over the char floor) a
	failing LLM call made maybe_compact_messages rebuild the full-history
	prompt and call the LLM again on every subsequent step.
	"""
	manager = MessageManager(
		task='test task',
		system_message=SystemMessage(content='system'),
		file_system=FileSystem(tmp_path),
	)
	manager.state.agent_history_items.append(HistoryItem(action_results='x' * 50_000))

	llm = AsyncMock(spec=BaseChatModel)
	llm.ainvoke.side_effect = RuntimeError('compaction model unavailable')
	settings = MessageCompactionSettings(compact_every_n_steps=5, trigger_char_count=40_000)

	# Step 25: both gates pass -> one attempt is made (and fails)
	assert (
		await manager.maybe_compact_messages(llm=llm, settings=settings, step_info=AgentStepInfo(step_number=25, max_steps=100))
		is False
	)

	# Steps 26-29: within the interval -> no further attempts
	for step in (26, 27, 28, 29):
		assert (
			await manager.maybe_compact_messages(
				llm=llm, settings=settings, step_info=AgentStepInfo(step_number=step, max_steps=100)
			)
			is False
		)

	# Step 30: interval elapsed -> exactly one retry
	assert (
		await manager.maybe_compact_messages(llm=llm, settings=settings, step_info=AgentStepInfo(step_number=30, max_steps=100))
		is False
	)

	assert llm.ainvoke.await_count == 2, f'expected compaction attempts only at the step interval, got {llm.ainvoke.await_count}'


@pytest.mark.asyncio
async def test_successful_compaction_still_updates_state(tmp_path: Path):
	"""Guard: recording the attempt up front must not change success semantics."""
	manager = MessageManager(
		task='test task',
		system_message=SystemMessage(content='system'),
		file_system=FileSystem(tmp_path),
	)
	manager.state.agent_history_items.append(HistoryItem(action_results='x' * 50_000))

	llm = AsyncMock(spec=BaseChatModel)
	llm.ainvoke.return_value = ChatInvokeCompletion(completion='Compacted history', usage=None)
	settings = MessageCompactionSettings(compact_every_n_steps=5, trigger_char_count=40_000)

	assert (
		await manager.maybe_compact_messages(llm=llm, settings=settings, step_info=AgentStepInfo(step_number=5, max_steps=100))
		is True
	)
	assert manager.state.compacted_memory == 'Compacted history'
	assert manager.state.compaction_count == 1
	assert manager.state.last_compaction_step == 5

	# Within the interval, no new attempt even though the history is rebuilt large
	manager.state.agent_history_items.append(HistoryItem(action_results='y' * 50_000))
	assert (
		await manager.maybe_compact_messages(llm=llm, settings=settings, step_info=AgentStepInfo(step_number=6, max_steps=100))
		is False
	)
	assert llm.ainvoke.await_count == 1
