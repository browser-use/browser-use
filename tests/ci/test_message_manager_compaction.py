from __future__ import annotations

from typing import cast

import pytest

from browser_use.agent.message_manager.service import MessageManager
from browser_use.agent.message_manager.views import HistoryItem
from browser_use.agent.views import AgentStepInfo, MessageCompactionSettings
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm.base import BaseChatModel
from browser_use.llm.messages import BaseMessage, SystemMessage
from browser_use.llm.views import ChatInvokeCompletion


class FakeCompactionLLM:
	model = 'fake-compactor'

	def __init__(self, completion: str = 'compact summary') -> None:
		self.completion = completion
		self.messages: list[BaseMessage] = []

	@property
	def provider(self) -> str:
		return 'fake'

	@property
	def name(self) -> str:
		return self.model

	async def ainvoke(
		self,
		messages: list[BaseMessage],
		output_format=None,
		**kwargs,
	) -> ChatInvokeCompletion[str]:
		self.messages = messages
		return ChatInvokeCompletion(completion=self.completion, usage=None)


@pytest.mark.asyncio
async def test_message_manager_compaction_trims_old_history(tmp_path) -> None:
	manager = MessageManager(
		task='Collect prices',
		system_message=SystemMessage(content='system'),
		file_system=FileSystem(tmp_path / 'files', create_default_files=False),
	)
	manager.state.agent_history_items.extend(
		[
			HistoryItem(step_number=1, memory='Found first price', action_results='Result\n$10'),
			HistoryItem(step_number=2, memory='Found second price', action_results='Result\n$12'),
		]
	)

	compacted = await manager.maybe_compact_messages(
		llm=cast(BaseChatModel, FakeCompactionLLM('Found two prices.')),
		settings=MessageCompactionSettings(compact_every_n_steps=1, trigger_char_count=1, keep_last_items=1),
		step_info=AgentStepInfo(step_number=3, max_steps=10),
	)

	assert compacted is True
	assert manager.state.compacted_memory == 'Found two prices.'
	assert manager.state.compaction_count == 1
	assert manager.state.last_compaction_step == 3
	assert [item.step_number for item in manager.state.agent_history_items] == [0, 2]


@pytest.mark.asyncio
async def test_message_manager_compaction_redacts_sensitive_values(tmp_path) -> None:
	manager = MessageManager(
		task='Login',
		system_message=SystemMessage(content='system'),
		file_system=FileSystem(tmp_path / 'files', create_default_files=False),
		sensitive_data={'password': 'secret-password'},
	)
	manager.state.agent_history_items.append(
		HistoryItem(step_number=1, memory='Typed password', action_results='Result\nsecret-password accepted')
	)
	fake_llm = FakeCompactionLLM('Password was accepted.')

	compacted = await manager.maybe_compact_messages(
		llm=cast(BaseChatModel, fake_llm),
		settings=MessageCompactionSettings(compact_every_n_steps=1, trigger_char_count=1, keep_last_items=0),
		step_info=AgentStepInfo(step_number=2, max_steps=10),
	)

	assert compacted is True
	assert 'secret-password' not in fake_llm.messages[1].text
	assert '<secret>password</secret>' in fake_llm.messages[1].text
