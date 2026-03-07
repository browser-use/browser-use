"""Regression tests for the browser-use skill CLI agent command."""

import sys
from types import SimpleNamespace
from typing import cast

import pytest

from browser_use.browser.session import BrowserSession
from browser_use.skill_cli.commands import agent as agent_command
from browser_use.skill_cli.sessions import SessionInfo


def test_get_llm_uses_env_default_model(monkeypatch):
	"""BROWSER_USE_LLM_MODEL should control the local CLI default model."""

	class FakeChatBrowserUse:
		def __init__(self, model='bu-latest'):
			self.model = model

	monkeypatch.setenv('BROWSER_USE_API_KEY', 'bu_test_key')
	monkeypatch.setenv('BROWSER_USE_LLM_MODEL', 'bu-2-0')

	import browser_use.llm as llm_module

	monkeypatch.setattr(llm_module, 'ChatBrowserUse', FakeChatBrowserUse)

	llm = agent_command.get_llm()

	assert isinstance(llm, FakeChatBrowserUse)
	assert llm.model == 'bu-2-0'


@pytest.mark.asyncio
async def test_handle_local_task_accepts_sync_llm_factory(monkeypatch):
	"""Local CLI should not await the synchronous get_llm helper."""

	llm = object()
	run_state: dict[str, object] = {}

	class FakeResult:
		def final_result(self):
			return 'done'

		def is_done(self):
			return True

		def __len__(self):
			return 1

	class FakeAgent:
		def __init__(self, *, task, llm, browser_session):
			run_state['task'] = task
			run_state['llm'] = llm
			run_state['browser_session'] = browser_session

		async def run(self, **kwargs):
			run_state['kwargs'] = kwargs
			return FakeResult()

	monkeypatch.setattr(agent_command, 'get_llm', lambda model=None: llm)
	monkeypatch.setitem(sys.modules, 'browser_use.agent.service', SimpleNamespace(Agent=FakeAgent))

	session = SessionInfo(
		name='test',
		browser_mode='chromium',
		headed=False,
		profile=None,
		browser_session=cast(BrowserSession, object()),
	)
	result = await agent_command._handle_local_task(
		session,
		{
			'task': 'Fill the form',
			'llm': 'bu-2-0',
			'max_steps': 7,
		},
	)

	assert result == {
		'success': True,
		'task': 'Fill the form',
		'steps': 1,
		'result': 'done',
		'done': True,
	}
	assert run_state['task'] == 'Fill the form'
	assert run_state['llm'] is llm
	assert run_state['kwargs'] == {'max_steps': 7}
