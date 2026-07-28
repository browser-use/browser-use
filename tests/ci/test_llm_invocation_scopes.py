from unittest.mock import AsyncMock

import pytest

from browser_use.agent.service import Agent
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm.views import ChatInvokeCompletion
from browser_use.tools.service import Tools


class _FakeBrowserSession:
	id = 'browser-session'
	agent_focus_target_id = None
	cdp_client = None

	async def get_current_page_url(self) -> str:
		return 'https://example.test/'


@pytest.fixture
def extracted_markdown(monkeypatch):
	async def fake_extract_clean_markdown(*, browser_session, extract_links, extract_images=False):
		return 'Example page content', {
			'original_html_chars': 100,
			'initial_markdown_chars': 40,
			'filtered_chars_removed': 5,
			'final_filtered_chars': 35,
		}

	monkeypatch.setattr('browser_use.dom.markdown_extractor.extract_clean_markdown', fake_extract_clean_markdown)


@pytest.mark.parametrize('structured', [False, True])
async def test_extract_threads_agent_session_to_llm(tmp_path, extracted_markdown, structured):
	captured_kwargs = {}

	async def invoke(messages, output_format=None, **kwargs):
		captured_kwargs.update(kwargs)
		completion = output_format.model_validate({'answer': 'ok'}) if output_format is not None else 'ok'
		return ChatInvokeCompletion(completion=completion, usage=None)

	llm = AsyncMock()
	llm.ainvoke.side_effect = invoke
	llm.model = 'mock-model'
	tools = Tools()
	output_schema = (
		{
			'type': 'object',
			'properties': {'answer': {'type': 'string'}},
			'required': ['answer'],
		}
		if structured
		else None
	)

	result = await tools.extract(
		query='extract the answer',
		output_schema=output_schema,
		browser_session=_FakeBrowserSession(),
		page_extraction_llm=llm,
		file_system=FileSystem(str(tmp_path)),
		llm_session_id='agent-session',
	)

	assert result.error is None
	assert captured_kwargs['session_id'] == 'agent-session'
	assert captured_kwargs['invocation_scope'] == 'page_extraction'


async def test_rerun_ai_step_uses_agent_session_and_tracks_custom_llm(tmp_path, extracted_markdown):
	captured_kwargs = {}

	async def invoke(messages, **kwargs):
		captured_kwargs.update(kwargs)
		return ChatInvokeCompletion(completion='analysis', usage=None)

	llm = AsyncMock()
	llm.ainvoke.side_effect = invoke
	llm.model = 'mock-model'
	agent = object.__new__(Agent)
	agent.llm = llm
	agent.session_id = 'agent-session'
	agent.browser_session = _FakeBrowserSession()
	agent.file_system = FileSystem(str(tmp_path))
	agent._additional_session_llms = {}

	result = await agent._execute_ai_step(
		query='analyze the page',
		include_screenshot=False,
		ai_step_llm=llm,
	)

	assert result.error is None
	assert captured_kwargs['session_id'] == 'agent-session'
	assert captured_kwargs['invocation_scope'] == 'rerun_ai_step'
	assert agent._additional_session_llms[id(llm)] is llm
