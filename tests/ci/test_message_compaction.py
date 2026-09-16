from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from browser_use.agent.message_manager.service import MessageManager
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
