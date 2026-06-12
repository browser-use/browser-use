from __future__ import annotations

import asyncio
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, cast, get_args, get_origin, get_type_hints

import pytest
from pydantic import BaseModel


@pytest.fixture(autouse=True)
def _disable_beta_agent_latest_version_check(monkeypatch):
	import browser_use.beta.service as beta_service

	async def no_latest_version():
		return None

	monkeypatch.setattr(beta_service, 'check_latest_browser_use_version', no_latest_version)
	monkeypatch.delenv('DEFAULT_LLM', raising=False)
	monkeypatch.setenv('BROWSER_USE_API_KEY', 'test-browser-use-api-key')


def test_top_level_agent_preserves_python_service():
	from browser_use import Agent as TopLevelAgent
	from browser_use.agent.service import Agent as BrowserUseAgent
	from browser_use.beta import Agent as BetaAgent

	assert TopLevelAgent is BrowserUseAgent
	assert TopLevelAgent is not BetaAgent


def test_agent_package_export_preserves_python_service():
	from browser_use.agent import Agent as AgentPackageAgent
	from browser_use.agent.service import Agent as BrowserUseAgent
	from browser_use.beta import Agent as BetaAgent

	assert AgentPackageAgent is BrowserUseAgent
	assert AgentPackageAgent is not BetaAgent


def test_agent_service_export_preserves_python_service():
	from browser_use.agent.service import Agent as ServiceAgent
	from browser_use.beta import Agent as BetaAgent

	assert ServiceAgent is not BetaAgent


def test_beta_package_reexports_chat_models_and_browser_config():
	from browser_use import Browser as TopLevelBrowser
	from browser_use import BrowserProfile as TopLevelBrowserProfile
	from browser_use import BrowserSession as TopLevelBrowserSession
	from browser_use import ChatBrowserUse as TopLevelChatBrowserUse
	from browser_use.beta import (
		Browser,
		BrowserProfile,
		BrowserSession,
		ChatAnthropic,
		ChatBrowserUse,
		ChatGoogle,
		ChatOpenAI,
	)
	from browser_use.llm.anthropic.chat import ChatAnthropic as LlmChatAnthropic
	from browser_use.llm.google.chat import ChatGoogle as LlmChatGoogle
	from browser_use.llm.openai.chat import ChatOpenAI as LlmChatOpenAI

	assert Browser is TopLevelBrowser
	assert BrowserProfile is TopLevelBrowserProfile
	assert BrowserSession is TopLevelBrowserSession
	assert ChatBrowserUse is TopLevelChatBrowserUse
	assert ChatGoogle is LlmChatGoogle
	assert ChatAnthropic is LlmChatAnthropic
	assert ChatOpenAI is LlmChatOpenAI


def test_beta_agent_class_metadata_matches_browser_use_service_surface():
	from browser_use import Agent as TopLevelAgent
	from browser_use.agent.service import Agent as ServiceAgent
	from browser_use.agent.service import _PythonAgent as BrowserUseAgent
	from browser_use.beta import Agent as BetaAgent

	assert TopLevelAgent is ServiceAgent is BrowserUseAgent
	assert BetaAgent is not BrowserUseAgent
	assert BetaAgent.__name__ == BrowserUseAgent.__name__ == 'Agent'
	assert BetaAgent.__qualname__ == BrowserUseAgent.__qualname__ == 'Agent'
	assert BetaAgent.__module__ == BrowserUseAgent.__module__ == 'browser_use.agent.service'
	assert BetaAgent.__doc__ == BrowserUseAgent.__doc__
	assert repr(BetaAgent) == repr(BrowserUseAgent)


def test_beta_agent_generic_subscription_matches_browser_use():
	from browser_use.agent.service import Agent as ServiceAgent
	from browser_use.agent.service import _PythonAgent as BrowserUseAgent
	from browser_use.beta import Agent as BetaAgent

	class Answer(BaseModel):
		answer: str

	browser_use_alias = BrowserUseAgent[dict, Answer]
	beta_alias = BetaAgent[dict, Answer]
	service_alias = ServiceAgent[dict, Answer]

	assert get_args(beta_alias) == get_args(browser_use_alias) == (dict, Answer)
	assert get_args(service_alias) == (dict, Answer)
	assert get_origin(beta_alias) is BetaAgent
	assert get_origin(service_alias) is BrowserUseAgent

	with pytest.raises(TypeError, match='Too few arguments'):
		BetaAgent[Answer]


def test_beta_agent_constructor_signature_matches_browser_use_order(tmp_path):
	from browser_use.agent.service import _PythonAgent as BrowserUseAgent
	from browser_use.beta import Agent as BetaAgent

	browser_use_params = list(inspect.signature(BrowserUseAgent.__init__).parameters)
	beta_params = list(inspect.signature(BetaAgent.__init__).parameters)

	assert beta_params == browser_use_params

	values = []
	for param in list(inspect.signature(BetaAgent.__init__).parameters.values())[1:]:
		if param.name == 'task':
			values.append('Check constructor parity.')
		elif param.name == 'llm':
			values.append(type('LLM', (), {'model': 'gpt-test', 'provider': 'test-provider'})())
		elif param.name == 'source':
			values.append('signature-source')
		elif param.name == 'file_system_path':
			values.append(str(tmp_path / 'agent-files'))
		elif param.name == 'task_id':
			values.append('signature-task-id')
			break
		else:
			assert param.default is not inspect.Parameter.empty
			values.append(param.default)

	agent = BetaAgent(*values)

	assert agent.source == 'signature-source'
	assert agent.file_system_path == str(tmp_path / 'agent-files')
	assert agent.task_id == 'signature-task-id'


def test_beta_agent_runtime_signatures_match_browser_use_callable_surface():
	from browser_use.agent.service import _PythonAgent as BrowserUseAgent
	from browser_use.beta import Agent as BetaAgent

	assert inspect.signature(BetaAgent) == inspect.signature(BrowserUseAgent)
	assert inspect.signature(BetaAgent.__init__) == inspect.signature(BrowserUseAgent.__init__)

	browser_use_callables = {
		name for name, value in vars(BrowserUseAgent).items() if callable(value) and not name.startswith('__')
	}
	beta_callables = {name for name, value in vars(BetaAgent).items() if callable(value) and not name.startswith('__')}

	for method_name in sorted(browser_use_callables & beta_callables):
		assert inspect.signature(getattr(BetaAgent, method_name)) == inspect.signature(getattr(BrowserUseAgent, method_name))


def test_beta_agent_constructor_type_hints_match_browser_use_core_params():
	from browser_use.agent.service import _PythonAgent as BrowserUseAgent
	from browser_use.beta import Agent as BetaAgent
	from browser_use.tools.service import Tools

	browser_use_hints = get_type_hints(BrowserUseAgent.__init__)
	beta_hints = get_type_hints(BetaAgent.__init__)

	for name in (
		'llm',
		'register_new_step_callback',
		'register_done_callback',
		'output_model_schema',
		'page_extraction_llm',
		'sample_images',
	):
		assert beta_hints[name] == browser_use_hints[name]

	def assert_tools_context_hint(annotation):
		inner = [arg for arg in get_args(annotation) if arg is not type(None)]
		assert len(inner) == 1
		assert get_origin(inner[0]) is Tools
		type_args = get_args(inner[0])
		assert len(type_args) == 1
		assert type_args[0].__name__ == 'Context'

	for name in ('tools', 'controller'):
		assert_tools_context_hint(browser_use_hints[name])
		assert_tools_context_hint(beta_hints[name])

	assert 'kwargs' not in beta_hints
	assert 'return' not in beta_hints


def test_beta_agent_run_type_hints_match_browser_use_hooks():
	from browser_use.agent.service import _PythonAgent as BrowserUseAgent
	from browser_use.beta import Agent as BetaAgent

	for method_name in ('run', 'run_sync'):
		browser_use_hints = get_type_hints(getattr(BrowserUseAgent, method_name))
		beta_hints = get_type_hints(getattr(BetaAgent, method_name))

		assert beta_hints == browser_use_hints


def test_beta_agent_action_model_helper_type_hints_match_browser_use():
	from browser_use.agent.service import _PythonAgent as BrowserUseAgent
	from browser_use.beta import Agent as BetaAgent

	for method_name in ('_convert_initial_actions', 'multi_act'):
		browser_use_hints = get_type_hints(getattr(BrowserUseAgent, method_name))
		beta_hints = get_type_hints(getattr(BetaAgent, method_name))

		assert beta_hints == browser_use_hints


def test_beta_agent_browser_state_helper_type_hints_match_browser_use():
	from browser_use.agent.service import _PythonAgent as BrowserUseAgent
	from browser_use.beta import Agent as BetaAgent

	for method_name in ('_finalize', '_get_next_action', '_log_step_context', '_make_history_item', '_prepare_context'):
		browser_use_hints = get_type_hints(getattr(BrowserUseAgent, method_name))
		beta_hints = get_type_hints(getattr(BetaAgent, method_name))

		assert beta_hints == browser_use_hints


def test_beta_agent_llm_message_helper_type_hints_match_browser_use():
	from browser_use.agent.service import _PythonAgent as BrowserUseAgent
	from browser_use.beta import Agent as BetaAgent

	for method_name in (
		'_get_model_output_with_retry',
		'_handle_post_llm_processing',
		'_process_messsages_and_replace_long_urls_shorter_ones',
		'get_model_output',
	):
		browser_use_hints = get_type_hints(getattr(BrowserUseAgent, method_name))
		beta_hints = get_type_hints(getattr(BetaAgent, method_name))

		assert beta_hints == browser_use_hints


def test_beta_agent_unannotated_helper_type_hints_match_browser_use():
	from browser_use.agent.service import _PythonAgent as BrowserUseAgent
	from browser_use.beta import Agent as BetaAgent

	for method_name in ('_log_action', '_verify_and_setup_llm', 'close', 'load_and_rerun'):
		browser_use_hints = get_type_hints(getattr(BrowserUseAgent, method_name))
		beta_hints = get_type_hints(getattr(BetaAgent, method_name))

		assert beta_hints == browser_use_hints


def test_rust_events_reconstruct_browser_use_history():
	from browser_use.beta.service import _history_from_events

	events = [
		{
			'event_type': 'browser.state',
			'payload': {'url': 'https://example.com', 'title': 'Example'},
		},
		{
			'event_type': 'model.usage',
			'payload': {'input_tokens': 11, 'cached_input_tokens': 3, 'output_tokens': 7, 'cost_usd': 0.12},
		},
		{
			'event_type': 'session.done',
			'payload': {'result': 'final answer'},
		},
	]

	history = _history_from_events(
		events,
		model='gpt-test',
		started=1.0,
		finished=2.5,
		output_model_schema=None,
		process_error=None,
	)

	assert history.final_result() == 'final answer'
	assert history.is_done() is True
	assert history.is_successful() is True
	assert history.urls() == ['https://example.com']
	assert history.usage is not None
	assert history.usage.total_prompt_tokens == 11
	assert history.usage.total_prompt_cached_tokens == 3
	assert history.usage.total_completion_tokens == 7


def test_rust_history_ignores_internal_browser_connection_url():
	from browser_use.beta.service import _history_from_events

	history = _history_from_events(
		[
			{'event_type': 'browser.connected', 'payload': {'url': 'http://127.0.0.1:41335'}},
			{
				'event_type': 'tool.output',
				'payload': {'name': 'browser', 'text': 'Connected to browser at http://127.0.0.1:41335'},
			},
			{'event_type': 'browser.state', 'payload': {'url': 'https://example.com', 'title': 'Example'}},
			{'event_type': 'session.done', 'payload': {'result': 'final answer'}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)
	local_page_history = _history_from_events(
		[
			{'event_type': 'browser.state', 'payload': {'url': 'http://127.0.0.1:8000/', 'title': 'Local app'}},
			{'event_type': 'session.done', 'payload': {'result': 'final answer'}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	assert history.urls() == ['https://example.com']
	assert local_page_history.urls() == ['http://127.0.0.1:8000/']


def test_rust_history_reconstructs_terminal_browser_script_urls():
	from browser_use.beta.service import _history_from_events

	output_history = _history_from_events(
		[
			{
				'type': 'tool.output',
				'payload': {
					'name': 'browser_script',
					'ok': True,
					'outputs': [
						{
							'label': 'start',
							'summary': {
								'kind': 'page',
								'title': 'AND Digital',
								'url': 'https://www.and.digital/',
							},
							'value': {
								'title': 'AND Digital',
								'url': 'https://www.and.digital/',
								'target': {'target_id': 'target-1'},
							},
						}
					],
				},
			},
			{'event_type': 'session.done', 'payload': {'result': 'final answer'}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	assert output_history.urls() == ['https://www.and.digital/']
	assert output_history.history[0].state.title == 'AND Digital'
	assert output_history.history[0].state.tabs[0].url == 'https://www.and.digital/'

	navigation_history = _history_from_events(
		[
			{
				'type': 'tool.started',
				'payload': {
					'name': 'browser_script',
					'arguments': {'code': "info = new_tab('https://example.com')\nwait_for_load(timeout=10)"},
				},
			},
			{'event_type': 'session.done', 'payload': {'result': 'Example Domain'}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	assert navigation_history.urls() == ['https://example.com']


def test_rust_history_reconstructs_terminal_browser_live_url():
	from browser_use.beta.service import _history_from_events

	history = _history_from_events(
		[
			{
				'type': 'browser.live_url',
				'payload': {
					'live_url': 'https://live.browser-use.com/watch/session-123',
					'url': 'https://live.browser-use.com/watch/session-123',
				},
			},
			{'event_type': 'session.done', 'payload': {'result': 'final answer'}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	assert history.urls() == ['https://live.browser-use.com/watch/session-123']
	assert history.history[0].state.url == 'https://live.browser-use.com/watch/session-123'
	assert history.history[0].state.tabs[0].url == 'https://live.browser-use.com/watch/session-123'


def test_rust_history_reconstructs_terminal_screenshot_paths(tmp_path):
	import base64

	from browser_use.beta.service import _history_from_events

	screenshot_path = tmp_path / 'terminal-shot.png'
	screenshot_bytes = b'\x89PNG\r\n\x1a\nterminal-shot'
	screenshot_path.write_bytes(screenshot_bytes)

	history = _history_from_events(
		[
			{
				'type': 'tool.output',
				'payload': {
					'name': 'browser_script',
					'tool_call_id': 'call-browser',
					'images': [{'path': str(screenshot_path), 'mime_type': 'image/png'}],
				},
			},
			{
				'type': 'tool.image',
				'payload': {
					'name': 'browser_script',
					'tool_call_id': 'call-browser',
					'image': {'path': str(screenshot_path), 'mime_type': 'image/png'},
				},
			},
			{'event_type': 'session.done', 'payload': {'result': 'final answer'}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	assert history.screenshot_paths() == [str(screenshot_path)]
	assert history.screenshots() == [base64.b64encode(screenshot_bytes).decode('utf-8')]


def test_rust_history_attaches_terminal_tool_images_to_actions(tmp_path):
	from browser_use.beta.service import _history_from_events

	screenshot_path = tmp_path / 'tool-image.png'
	screenshot_path.write_bytes(b'\x89PNG\r\n\x1a\nterminal-image')

	history = _history_from_events(
		[
			{
				'type': 'tool.started',
				'payload': {
					'name': 'browser_script',
					'tool_call_id': 'call-browser',
					'arguments': {'code': 'observe_page()'},
				},
			},
			{
				'type': 'tool.output',
				'payload': {
					'name': 'browser_script',
					'tool_call_id': 'call-browser',
					'text': 'Observed page.',
					'images': [{'path': str(screenshot_path), 'mime_type': 'image/png'}],
				},
			},
			{
				'type': 'tool.image',
				'payload': {
					'name': 'browser_script',
					'tool_call_id': 'call-browser',
					'image': {'path': str(screenshot_path), 'mime_type': 'image/png'},
				},
			},
			{'event_type': 'session.done', 'payload': {'result': 'final answer'}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	results = history.action_results()

	assert history.action_names() == ['browser_script', 'done']
	assert results[0].attachments == [str(screenshot_path)]
	assert results[0].extracted_content == 'Observed page.'
	assert results[-1].attachments is None
	assert history.screenshot_paths() == [str(screenshot_path)]


def test_rust_history_compacts_large_terminal_tool_memory():
	from browser_use.beta.service import _history_from_events

	large_output = 'large browser output\n' + ('row,value\n' * 200)

	history = _history_from_events(
		[
			{
				'type': 'tool.started',
				'payload': {
					'name': 'browser_script',
					'tool_call_id': 'call-browser',
					'arguments': {'code': 'print(document.body.innerText)'},
				},
			},
			{
				'type': 'tool.output',
				'payload': {
					'name': 'browser_script',
					'tool_call_id': 'call-browser',
					'text': large_output,
				},
			},
			{'event_type': 'session.done', 'payload': {'result': 'final answer'}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	result = history.action_results()[0]

	assert result.extracted_content == large_output.strip()
	assert result.include_extracted_content_only_once is True
	assert result.long_term_memory is not None
	assert 'browser_script returned' in result.long_term_memory
	assert large_output.strip() not in result.long_term_memory


def test_rust_history_reconstructs_terminal_tool_call_actions():
	from browser_use.beta.service import _history_from_events

	history = _history_from_events(
		[
			{
				'type': 'tool.started',
				'payload': {
					'name': 'browser_script',
					'tool_call_id': 'call-browser',
					'arguments': {'code': "goto_url('https://example.com')"},
				},
			},
			{
				'type': 'tool.output',
				'payload': {
					'name': 'browser_script',
					'tool_call_id': 'call-browser',
					'ok': True,
					'text': 'Opened Example Domain',
				},
			},
			{
				'type': 'tool.started',
				'payload': {
					'name': 'done',
					'tool_call_id': 'call-done',
					'arguments': {'text': 'Example Domain', 'success': True},
				},
			},
			{'event_type': 'session.done', 'payload': {'result': 'Example Domain'}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	actions = history.model_actions()
	action_history = history.action_history()

	assert history.action_names() == ['browser_script', 'done']
	assert actions[0]['browser_script']['code'] == "goto_url('https://example.com')"
	assert actions[1]['done'] == {'text': 'Example Domain', 'success': True}
	assert history.last_action() == {'done': {'text': 'Example Domain', 'success': True}}
	assert action_history[0][0]['result'] == 'Opened Example Domain'
	assert history.final_result() == 'Example Domain'
	assert history.action_results()[-1].is_done is True


def test_rust_history_reconstructs_eval_visible_multi_turn_actions_and_usage():
	from browser_use.beta.service import _history_from_events

	history = _history_from_events(
		[
			{'type': 'model.turn.request', 'ts_ms': 1_000, 'payload': {'model': 'claude-sonnet-4-6'}},
			{'type': 'browser.state', 'ts_ms': 1_010, 'payload': {'url': 'about:blank', 'title': ''}},
			{
				'type': 'tool.started',
				'ts_ms': 1_020,
				'payload': {
					'name': 'browser_script',
					'tool_call_id': 'call-open',
					'arguments': {'code': "goto_url('https://example.com')"},
				},
			},
			{
				'type': 'tool.output',
				'ts_ms': 1_030,
				'payload': {'name': 'browser_script', 'tool_call_id': 'call-open', 'text': 'Opened Example Domain'},
			},
			{'type': 'model.usage', 'payload': {'input_tokens': 100, 'cached_input_tokens': 20, 'output_tokens': 15}},
			{'type': 'model.turn.request', 'ts_ms': 2_000, 'payload': {'model': 'claude-sonnet-4-6'}},
			{'type': 'browser.state', 'ts_ms': 2_010, 'payload': {'url': 'https://example.com', 'title': 'Example Domain'}},
			{
				'type': 'model.tool_call',
				'ts_ms': 2_020,
				'payload': {
					'id': 'call-extract',
					'name': 'browser_script',
					'arguments': {'code': 'emit_output(page_info(), label="page_info")'},
				},
			},
			{
				'type': 'tool.output',
				'ts_ms': 2_030,
				'payload': {
					'name': 'browser_script',
					'tool_call_id': 'call-extract',
					'text': 'Page title: Example Domain',
				},
			},
			{'type': 'model.usage', 'payload': {'input_tokens': 140, 'cached_input_tokens': 90, 'output_tokens': 25}},
			{
				'type': 'tool.started',
				'ts_ms': 2_040,
				'payload': {
					'name': 'done',
					'tool_call_id': 'call-done',
					'arguments': {'text': 'Example Domain', 'success': True},
				},
			},
			{'type': 'session.done', 'ts_ms': 2_050, 'payload': {'result': 'Example Domain'}},
		],
		model='claude-sonnet-4-6',
		started=1.0,
		finished=2.5,
		output_model_schema=None,
		process_error=None,
	)

	dump = history.model_dump()
	action_history = history.action_history()

	assert history.number_of_steps() == 2
	assert len(dump['history']) == 2
	assert history.action_names() == ['browser_script', 'browser_script', 'done']
	assert action_history[0][0]['browser_script']['code'] == "goto_url('https://example.com')"
	assert action_history[0][0]['result'] == 'Opened Example Domain'
	assert action_history[1][0]['browser_script']['code'] == 'emit_output(page_info(), label="page_info")'
	assert action_history[1][0]['result'] == 'Page title: Example Domain'
	assert action_history[1][-1]['done'] == {'text': 'Example Domain', 'success': True}
	assert history.urls() == ['https://example.com', 'https://example.com']
	assert history.final_result() == 'Example Domain'
	assert history.usage is not None
	assert history.usage.total_prompt_tokens == 240
	assert history.usage.total_prompt_cached_tokens == 110
	assert history.usage.total_completion_tokens == 40
	assert history.usage.total_tokens == 280
	assert history.usage.entry_count == 2


def test_rust_history_reconstructs_terminal_model_tool_call_actions():
	from browser_use.beta.service import _history_from_events

	history = _history_from_events(
		[
			{
				'type': 'model.tool_call',
				'payload': {
					'id': 'call-browser',
					'name': 'browser_script',
					'arguments': {'code': "goto_url('https://example.com')"},
				},
			},
			{
				'type': 'tool.started',
				'payload': {
					'name': 'browser_script',
					'tool_call_id': 'call-browser',
					'arguments': {'code': 'duplicate_should_not_replace_original()'},
				},
			},
			{
				'type': 'tool.output',
				'payload': {
					'name': 'browser_script',
					'tool_call_id': 'call-browser',
					'text': 'Opened Example Domain',
				},
			},
			{
				'type': 'model.response.output_item',
				'payload': {
					'item': {
						'type': 'function_call',
						'call_id': 'call-done',
						'name': 'done',
						'arguments': '{"text": "Example Domain", "success": true}',
					}
				},
			},
			{'event_type': 'session.done', 'payload': {'result': 'Example Domain'}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	actions = history.model_actions()

	assert history.action_names() == ['browser_script', 'done']
	assert actions[0]['browser_script']['code'] == "goto_url('https://example.com')"
	assert actions[1]['done'] == {'text': 'Example Domain', 'success': True}
	assert history.action_history()[0][0]['result'] == 'Opened Example Domain'
	assert history.last_action() == {'done': {'text': 'Example Domain', 'success': True}}


def test_rust_history_reconstructs_terminal_response_input_item_tool_results():
	from browser_use.beta.service import _history_from_events

	history = _history_from_events(
		[
			{
				'type': 'model.tool_call',
				'payload': {
					'id': 'call-browser',
					'name': 'browser_script',
					'arguments': {'code': "goto_url('https://example.com')"},
				},
			},
			{
				'type': 'model.response.input_item',
				'payload': {
					'call_id': 'call-browser',
					'name': 'browser_script',
					'item': {
						'type': 'function_call_output',
						'call_id': 'call-browser',
						'output': [
							{'type': 'input_text', 'text': 'Opened '},
							{'type': 'input_text', 'text': 'Example Domain'},
							{'type': 'input_image', 'image_url': 'data:image/png;base64,AAAA'},
						],
					},
				},
			},
			{'event_type': 'session.done', 'payload': {'result': 'Example Domain'}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	first_result = history.action_results()[0]

	assert history.action_names() == ['browser_script', 'done']
	assert first_result.extracted_content == 'Opened Example Domain'
	assert first_result.long_term_memory == 'Opened Example Domain'
	assert history.action_history()[0][0]['result'] == 'Opened Example Domain'
	assert history.final_result() == 'Example Domain'


def test_rust_history_reconstructs_terminal_tool_finished_results():
	from browser_use.beta.service import _history_from_events

	history = _history_from_events(
		[
			{
				'type': 'tool.started',
				'payload': {
					'name': 'read_file',
					'tool_call_id': 'call-read',
					'arguments': {'path': 'README.md'},
				},
			},
			{
				'type': 'tool.finished',
				'payload': {
					'name': 'read_file',
					'tool_call_id': 'call-read',
				},
			},
			{
				'type': 'tool.started',
				'payload': {
					'name': 'browser_script',
					'tool_call_id': 'call-browser',
					'arguments': {'code': "goto_url('https://example.com')"},
				},
			},
			{
				'type': 'tool.output',
				'payload': {
					'name': 'browser_script',
					'tool_call_id': 'call-browser',
					'text': 'Opened Example Domain',
				},
			},
			{
				'type': 'tool.finished',
				'payload': {
					'name': 'browser_script',
					'tool_call_id': 'call-browser',
				},
			},
			{'event_type': 'session.done', 'payload': {'result': 'Example Domain'}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	results = history.action_results()

	assert history.action_names() == ['read_file', 'browser_script', 'done']
	assert results[0].extracted_content == 'read_file completed'
	assert results[0].long_term_memory == 'read_file completed'
	assert results[1].extracted_content == 'Opened Example Domain'
	assert history.action_history()[0][0]['result'] == 'read_file completed'
	assert history.action_history()[0][1]['result'] == 'Opened Example Domain'
	assert history.final_result() == 'Example Domain'


def test_rust_history_reconstructs_terminal_tool_output_deltas():
	from browser_use.beta.service import _history_from_events

	history = _history_from_events(
		[
			{
				'type': 'tool.started',
				'payload': {
					'name': 'python',
					'tool_call_id': 'call-python',
					'arguments': {'code': "print('hello world')"},
				},
			},
			{
				'type': 'tool.output_delta',
				'payload': {
					'name': 'python',
					'tool_call_id': 'call-python',
					'stream': 'stdout',
					'text': 'hello',
				},
			},
			{
				'type': 'tool.output_delta',
				'payload': {
					'name': 'python',
					'tool_call_id': 'call-python',
					'stream': 'stdout',
					'text': ' world\n',
				},
			},
			{
				'type': 'tool.finished',
				'payload': {
					'name': 'python',
					'tool_call_id': 'call-python',
				},
			},
			{'event_type': 'session.done', 'payload': {'result': 'final answer'}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	first_result = history.action_results()[0]

	assert history.action_names() == ['python', 'done']
	assert history.model_actions()[0]['python']['code'] == "print('hello world')"
	assert first_result.extracted_content == 'hello world'
	assert first_result.long_term_memory == 'hello world'
	assert history.action_history()[0][0]['result'] == 'hello world'
	assert history.final_result() == 'final answer'


def test_rust_history_reconstructs_terminal_exec_command_output_deltas():
	from browser_use.beta.service import _history_from_events

	history = _history_from_events(
		[
			{
				'type': 'tool.started',
				'payload': {
					'name': 'exec_command',
					'tool_call_id': 'call-exec',
					'arguments': {'cmd': "printf 'hello world'"},
				},
			},
			{
				'type': 'tool.output_delta',
				'payload': {
					'name': 'exec_command',
					'tool_call_id': 'call-exec',
					'process_id': '1000',
					'session_id': 1000,
					'stream': 'stdout',
					'text': 'hello ',
				},
			},
			{
				'type': 'exec_command.output_delta',
				'payload': {
					'call_id': 'call-exec',
					'process_id': '1000',
					'session_id': 1000,
					'stream': 'stdout',
					'chunk': 'hello ',
				},
			},
			{
				'type': 'exec_command.output_delta',
				'payload': {
					'call_id': 'call-exec',
					'process_id': '1000',
					'session_id': 1000,
					'stream': 'stdout',
					'chunk': 'world\n',
				},
			},
			{'event_type': 'session.done', 'payload': {'result': 'final answer'}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	first_result = history.action_results()[0]

	assert history.action_names() == ['exec_command', 'done']
	assert history.model_actions()[0]['exec_command']['cmd'] == "printf 'hello world'"
	assert first_result.extracted_content == 'hello world'
	assert first_result.long_term_memory == 'hello world'
	assert history.action_history()[0][0]['result'] == 'hello world'
	assert history.final_result() == 'final answer'


def test_rust_history_reconstructs_terminal_exec_command_end_output():
	from browser_use.beta.service import _history_from_events

	history = _history_from_events(
		[
			{
				'type': 'tool.started',
				'payload': {
					'name': 'exec_command',
					'tool_call_id': 'call-exec',
					'arguments': {'cmd': "printf 'final stdout'"},
				},
			},
			{
				'type': 'exec_command.end',
				'payload': {
					'name': 'exec_command',
					'tool_call_id': 'call-exec',
					'process_id': '1000',
					'session_id': 1000,
					'exit_code': 0,
					'wall_time_seconds': 0.1,
					'output': 'final stdout\n',
				},
			},
			{'event_type': 'session.done', 'payload': {'result': 'final answer'}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	first_result = history.action_results()[0]

	assert history.action_names() == ['exec_command', 'done']
	assert history.model_actions()[0]['exec_command']['cmd'] == "printf 'final stdout'"
	assert first_result.extracted_content == 'final stdout'
	assert first_result.long_term_memory == 'final stdout'
	assert history.action_history()[0][0]['result'] == 'final stdout'
	assert history.final_result() == 'final answer'


def test_rust_history_surfaces_terminal_exec_command_end_failure():
	from browser_use.beta.service import _history_from_events

	history = _history_from_events(
		[
			{'event_type': 'model.turn.request', 'payload': {'model': 'gpt-test'}},
			{
				'type': 'tool.started',
				'payload': {
					'name': 'exec_command',
					'tool_call_id': 'call-exec',
					'arguments': {'cmd': 'exit 2'},
				},
			},
			{
				'type': 'exec_command.end',
				'payload': {
					'name': 'exec_command',
					'tool_call_id': 'call-exec',
					'process_id': '1000',
					'session_id': 1000,
					'exit_code': 2,
					'wall_time_seconds': 0.1,
					'output': 'command failed\n',
				},
			},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	error = 'exec_command failed: exit code 2: command failed'
	first_result = history.action_results()[0]

	assert history.final_result() is None
	assert history.is_done() is False
	assert history.errors() == [error]
	assert first_result.error == error
	assert first_result.extracted_content == 'command failed'
	assert first_result.long_term_memory == 'command failed'
	assert history.action_history()[0][0]['result'] == 'command failed'
	assert history.action_results()[-1].error == error


def test_rust_history_reconstructs_terminal_command_waiting_result():
	from browser_use.beta.service import _history_from_events

	history = _history_from_events(
		[
			{
				'type': 'tool.started',
				'payload': {
					'name': 'exec_command',
					'tool_call_id': 'call-exec',
					'arguments': {'cmd': 'sleep 60 && echo done', 'yield_time_ms': 250},
				},
			},
			{
				'type': 'tool.output_delta',
				'payload': {
					'name': 'exec_command',
					'tool_call_id': 'call-exec',
					'process_id': '1000',
					'session_id': 1000,
					'stream': 'stdout',
					'text': 'started\n',
				},
			},
			{
				'type': 'command.waiting',
				'payload': {
					'name': 'exec_command',
					'tool_call_id': 'call-exec',
					'process_id': '1000',
					'session_id': 1000,
				},
			},
			{'event_type': 'session.done', 'payload': {'result': 'command is still running'}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	first_result = history.action_results()[0]
	waiting_result = 'started\n\nProcess running with session ID 1000'

	assert history.action_names() == ['exec_command', 'done']
	assert first_result.extracted_content == waiting_result
	assert first_result.long_term_memory == waiting_result
	assert first_result.error is None
	assert history.action_history()[0][0]['result'] == waiting_result
	assert history.final_result() == 'command is still running'


def test_rust_history_reconstructs_terminal_unkeyed_tool_results():
	from browser_use.beta.service import _history_from_events

	history = _history_from_events(
		[
			{'event_type': 'model.turn.request', 'payload': {'model': 'gpt-test'}},
			{
				'type': 'tool.started',
				'payload': {
					'name': 'python',
					'arguments': {'code': "print('full output')"},
				},
			},
			{
				'type': 'tool.output',
				'payload': {
					'name': 'python',
					'stream': True,
					'text': 'partial output',
				},
			},
			{
				'type': 'tool.output',
				'payload': {
					'name': 'python',
					'ok': True,
					'text': 'full output',
				},
			},
			{
				'type': 'tool.finished',
				'payload': {
					'name': 'python',
				},
			},
			{'event_type': 'session.done', 'payload': {'result': 'final answer'}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	first_result = history.action_results()[0]

	assert history.action_names() == ['python', 'done']
	assert history.model_actions()[0]['python']['code'] == "print('full output')"
	assert first_result.extracted_content == 'full output'
	assert first_result.long_term_memory == 'full output'
	assert history.action_history()[0][0]['result'] == 'full output'
	assert 'partial output' not in json.dumps(history.action_history(), sort_keys=True)
	assert history.final_result() == 'final answer'


def test_rust_history_reconstructs_terminal_structured_tool_output_results():
	from browser_use.beta.service import _history_from_events

	history = _history_from_events(
		[
			{'event_type': 'model.turn.request', 'payload': {'model': 'gpt-test'}},
			{
				'type': 'tool.started',
				'payload': {
					'name': 'browser_script',
					'tool_call_id': 'call-browser',
					'arguments': {'code': 'return page.summary()'},
				},
			},
			{
				'type': 'tool.output',
				'payload': {
					'name': 'browser_script',
					'tool_call_id': 'call-browser',
					'ok': True,
					'text': '',
					'summary': {
						'kind': 'page',
						'title': 'Example Domain',
						'url': 'https://example.com',
					},
					'data': {'ignored_when_summary_exists': True},
					'outputs': [{'label': 'page', 'value': {'url': 'https://example.com'}}],
				},
			},
			{'event_type': 'session.done', 'payload': {'result': 'Example Domain'}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	first_result = history.action_results()[0]
	structured_result = json.loads(first_result.extracted_content or '{}')

	assert history.action_names() == ['browser_script', 'done']
	assert structured_result == {
		'kind': 'page',
		'title': 'Example Domain',
		'url': 'https://example.com',
	}
	assert first_result.long_term_memory == first_result.extracted_content
	assert json.loads(history.action_history()[0][0]['result'])['url'] == 'https://example.com'
	assert history.final_result() == 'Example Domain'


def test_rust_history_synthesizes_done_action_from_terminal_completion():
	from browser_use.beta.service import _history_from_events

	history = _history_from_events(
		[
			{
				'type': 'tool.started',
				'payload': {
					'name': 'browser_script',
					'tool_call_id': 'call-browser',
					'arguments': {'code': "goto_url('https://example.com')"},
				},
			},
			{
				'type': 'tool.output',
				'payload': {
					'name': 'browser_script',
					'tool_call_id': 'call-browser',
					'text': 'Opened Example Domain',
				},
			},
			{'event_type': 'session.done', 'payload': {'result': 'Example Domain'}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	assert history.is_done() is True
	assert history.action_names() == ['browser_script', 'done']
	assert history.last_action() == {'done': {'text': 'Example Domain', 'success': True}}
	assert history.model_actions_filtered(['done']) == [
		{'done': {'text': 'Example Domain', 'success': True}, 'interacted_element': None}
	]
	assert history.action_history()[0][-1]['result'] == 'Example Domain'


def test_rust_history_reconstructs_terminal_model_turn_steps():
	from browser_use.beta.service import _history_from_events

	events = [
		{'type': 'session.created', 'ts_ms': 1_000, 'payload': {}},
		{'type': 'model.turn.request', 'ts_ms': 2_000, 'payload': {'model': 'gpt-test', 'attempt': 0}},
		{'type': 'model.stream_delta', 'ts_ms': 2_010, 'payload': {'text': 'Connect the browser.'}},
		{
			'type': 'tool.started',
			'ts_ms': 2_020,
			'payload': {
				'name': 'browser',
				'tool_call_id': 'call-browser',
				'arguments': {'cmd': 'connect managed --headless'},
			},
		},
		{
			'type': 'tool.output',
			'ts_ms': 2_030,
			'payload': {'name': 'browser', 'tool_call_id': 'call-browser', 'text': 'Connected browser'},
		},
		{
			'type': 'browser.state',
			'ts_ms': 2_040,
			'payload': {'url': 'https://example.com', 'title': 'Example Domain'},
		},
		{'type': 'model.turn.request', 'ts_ms': 3_000, 'payload': {'model': 'gpt-test', 'attempt': 0}},
		{'type': 'model.stream_delta', 'ts_ms': 3_010, 'payload': {'text': 'Return the page title.'}},
		{
			'type': 'tool.started',
			'ts_ms': 3_020,
			'payload': {
				'name': 'done',
				'tool_call_id': 'call-done',
				'arguments': {'text': 'Example Domain', 'success': True},
			},
		},
		{
			'type': 'tool.output',
			'ts_ms': 3_030,
			'payload': {'name': 'done', 'tool_call_id': 'call-done', 'text': 'done:Example Domain'},
		},
		{'type': 'session.done', 'ts_ms': 3_040, 'payload': {'result': 'Example Domain'}},
	]

	history = _history_from_events(
		events,
		model='gpt-test',
		started=1.0,
		finished=4.0,
		output_model_schema=None,
		process_error=None,
	)

	action_history = history.action_history()

	assert history.number_of_steps() == 2
	assert history.urls() == ['https://example.com', 'https://example.com']
	assert history.action_names() == ['browser', 'done']
	assert history.model_outputs()[0].memory == 'Connect the browser.'
	assert history.model_outputs()[1].memory == 'Return the page title.'
	assert action_history[0][0]['result'] == 'Connected browser'
	assert action_history[1][0]['result'] == 'Example Domain'
	assert history.final_result() == 'Example Domain'
	assert history.is_done() is True


def test_rust_history_prefers_done_tool_text_over_session_summary():
	from browser_use.beta.service import _history_from_events

	history = _history_from_events(
		[
			{'type': 'model.turn.request', 'ts_ms': 1_000, 'payload': {'model': 'claude-sonnet-4-0', 'attempt': 0}},
			{
				'type': 'tool.started',
				'ts_ms': 1_010,
				'payload': {
					'name': 'done',
					'tool_call_id': 'call-done',
					'arguments': {'text': 'Paramjit Uppal, Founder', 'success': True},
				},
			},
			{
				'type': 'tool.output',
				'ts_ms': 1_020,
				'payload': {'name': 'done', 'tool_call_id': 'call-done', 'text': 'done:Paramjit Uppal, Founder'},
			},
			{
				'type': 'session.done',
				'ts_ms': 1_030,
				'payload': {'result': 'I found the founder and will now provide the requested final format.'},
			},
		],
		model='claude-sonnet-4-0',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	assert history.final_result() == 'Paramjit Uppal, Founder'
	assert history.action_results()[-1].extracted_content == 'Paramjit Uppal, Founder'
	assert history.is_successful() is True


def test_rust_history_applies_terminal_session_rollback():
	from browser_use.beta.service import _history_from_events

	history = _history_from_events(
		[
			{'event_type': 'session.input', 'seq': 1, 'payload': {'text': 'first task'}},
			{'event_type': 'model.turn.request', 'seq': 2, 'ts_ms': 2_000, 'payload': {'model': 'gpt-test'}},
			{'event_type': 'model.stream_delta', 'seq': 3, 'payload': {'text': 'First turn'}},
			{
				'event_type': 'tool.started',
				'seq': 4,
				'payload': {
					'name': 'browser',
					'tool_call_id': 'call-first',
					'arguments': {'cmd': 'connect managed --headless'},
				},
			},
			{
				'event_type': 'tool.output',
				'seq': 5,
				'payload': {'name': 'browser', 'tool_call_id': 'call-first', 'text': 'First kept'},
			},
			{'event_type': 'session.followup', 'seq': 6, 'payload': {'text': 'second task'}},
			{'event_type': 'model.turn.request', 'seq': 7, 'ts_ms': 3_000, 'payload': {'model': 'gpt-test'}},
			{'event_type': 'model.stream_delta', 'seq': 8, 'payload': {'text': 'Second rolled back'}},
			{
				'event_type': 'tool.started',
				'seq': 9,
				'payload': {
					'name': 'browser_script',
					'tool_call_id': 'call-second',
					'arguments': {'code': "goto_url('https://rolled-back.example')"},
				},
			},
			{
				'event_type': 'tool.output',
				'seq': 10,
				'payload': {'name': 'browser_script', 'tool_call_id': 'call-second', 'text': 'Second removed'},
			},
			{'event_type': 'session.done', 'seq': 11, 'payload': {'result': 'Rolled Back Result'}},
			{'event_type': 'session.rollback', 'seq': 12, 'payload': {'num_turns': 1}},
			{'event_type': 'session.followup', 'seq': 13, 'payload': {'text': 'third task'}},
			{'event_type': 'model.turn.request', 'seq': 14, 'ts_ms': 4_000, 'payload': {'model': 'gpt-test'}},
			{'event_type': 'model.stream_delta', 'seq': 15, 'payload': {'text': 'Third turn'}},
			{
				'event_type': 'tool.started',
				'seq': 16,
				'payload': {
					'name': 'browser_script',
					'tool_call_id': 'call-third',
					'arguments': {'code': "goto_url('https://example.com')"},
				},
			},
			{
				'event_type': 'tool.output',
				'seq': 17,
				'payload': {'name': 'browser_script', 'tool_call_id': 'call-third', 'text': 'Third kept'},
			},
			{'event_type': 'session.done', 'seq': 18, 'payload': {'result': 'Third result'}},
		],
		model='gpt-test',
		started=1.0,
		finished=5.0,
		output_model_schema=None,
		process_error=None,
	)

	serialized_actions = json.dumps(history.model_actions(), sort_keys=True)

	assert history.number_of_steps() == 2
	assert history.action_names() == ['browser', 'browser_script', 'done']
	assert [output.memory for output in history.model_outputs()] == ['First turn', 'Third turn']
	assert history.action_history()[0][0]['result'] == 'First kept'
	assert history.action_history()[1][0]['result'] == 'Third kept'
	assert history.final_result() == 'Third result'
	assert 'Second rolled back' not in serialized_actions
	assert 'rolled-back.example' not in serialized_actions


def test_rust_history_applies_terminal_session_compaction_boundary():
	from browser_use.beta.service import _history_from_events

	history = _history_from_events(
		[
			{'event_type': 'session.input', 'seq': 1, 'payload': {'text': 'old task'}},
			{'event_type': 'model.turn.request', 'seq': 2, 'ts_ms': 2_000, 'payload': {'model': 'gpt-test'}},
			{'event_type': 'model.stream_delta', 'seq': 3, 'payload': {'text': 'Old turn'}},
			{
				'event_type': 'tool.started',
				'seq': 4,
				'payload': {
					'name': 'browser_script',
					'tool_call_id': 'call-old',
					'arguments': {'code': "goto_url('https://old.example')"},
				},
			},
			{
				'event_type': 'tool.output',
				'seq': 5,
				'payload': {'name': 'browser_script', 'tool_call_id': 'call-old', 'text': 'Old removed'},
			},
			{'event_type': 'session.done', 'seq': 6, 'payload': {'result': 'Old result'}},
			{
				'event_type': 'session.compacted',
				'seq': 7,
				'payload': {
					'replacement_messages': [{'role': 'user', 'content': 'compacted summary'}],
				},
			},
			{'event_type': 'session.followup', 'seq': 8, 'payload': {'text': 'post-compaction task'}},
			{'event_type': 'model.turn.request', 'seq': 9, 'ts_ms': 3_000, 'payload': {'model': 'gpt-test'}},
			{'event_type': 'model.stream_delta', 'seq': 10, 'payload': {'text': 'Post compaction turn'}},
			{
				'event_type': 'tool.started',
				'seq': 11,
				'payload': {
					'name': 'browser_script',
					'tool_call_id': 'call-post',
					'arguments': {'code': "goto_url('https://example.com')"},
				},
			},
			{
				'event_type': 'tool.output',
				'seq': 12,
				'payload': {'name': 'browser_script', 'tool_call_id': 'call-post', 'text': 'Post kept'},
			},
			{'event_type': 'session.done', 'seq': 13, 'payload': {'result': 'Post result'}},
		],
		model='gpt-test',
		started=1.0,
		finished=4.0,
		output_model_schema=None,
		process_error=None,
	)

	serialized_actions = json.dumps(history.model_actions(), sort_keys=True)

	assert history.number_of_steps() == 1
	assert history.action_names() == ['browser_script', 'done']
	assert history.model_outputs()[0].memory == 'Post compaction turn'
	assert history.action_history()[0][0]['result'] == 'Post kept'
	assert history.final_result() == 'Post result'
	assert 'Old turn' not in serialized_actions
	assert 'old.example' not in serialized_actions
	assert 'Old result' not in (history.final_result() or '')


def test_rust_history_reconstructs_terminal_streamed_model_thoughts():
	from browser_use.beta.service import _history_from_events

	history = _history_from_events(
		[
			{'event_type': 'model.turn.request', 'payload': {'model': 'gpt-test'}},
			{'event_type': 'model.stream_delta', 'payload': {'text': 'stale text'}},
			{'event_type': 'model.thinking_delta', 'payload': {'text': 'stale thinking'}},
			{'event_type': 'model.turn.error', 'payload': {'transient': True, 'error': 'retry'}},
			{'event_type': 'model.turn.retry', 'payload': {'attempt': 1, 'max_retries': 3}},
			{'event_type': 'model.thinking_delta', 'payload': {'text': 'checking '}},
			{'event_type': 'model.thinking_delta', 'payload': {'text': 'checking page'}},
			{'event_type': 'model.stream_delta', 'payload': {'text': 'Opening '}},
			{'event_type': 'model.stream_delta', 'payload': {'text': 'Opening Example Domain'}},
			{
				'type': 'tool.started',
				'payload': {
					'name': 'browser_script',
					'tool_call_id': 'call-browser',
					'arguments': {'code': "goto_url('https://example.com')"},
				},
			},
			{'event_type': 'session.done', 'payload': {'result': 'Example Domain'}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	output = history.model_outputs()[0]
	thought = history.model_thoughts()[0]

	assert output.thinking == 'checking page'
	assert output.memory == 'Opening Example Domain'
	assert thought.thinking == 'checking page'
	assert thought.memory == 'Opening Example Domain'
	assert 'stale' not in thought.memory
	assert 'stale' not in (thought.thinking or '')


def test_rust_history_reconstructs_terminal_response_item_model_text():
	from browser_use.beta.service import _history_from_events

	history = _history_from_events(
		[
			{'event_type': 'model.turn.request', 'payload': {'model': 'gpt-test'}},
			{'event_type': 'model.stream_delta', 'payload': {'text': 'I will '}},
			{
				'event_type': 'model.response.output_item',
				'payload': {
					'item': {
						'type': 'message',
						'role': 'assistant',
						'content': [
							{'type': 'output_text', 'text': 'I will inspect the page, '},
							{'type': 'text', 'text': 'then report the title.'},
						],
					}
				},
			},
			{
				'type': 'model.tool_call',
				'payload': {
					'id': 'call-browser',
					'name': 'browser_script',
					'arguments': {'code': "goto_url('https://example.com')"},
				},
			},
			{
				'type': 'tool.output',
				'payload': {
					'name': 'browser_script',
					'tool_call_id': 'call-browser',
					'text': 'Opened Example Domain',
				},
			},
			{'event_type': 'session.done', 'payload': {'result': 'Example Domain'}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	output = history.model_outputs()[0]

	assert output.memory == 'I will inspect the page, then report the title.'
	assert output.current_state.memory == 'I will inspect the page, then report the title.'
	assert history.action_history()[0][0]['result'] == 'Opened Example Domain'


def test_rust_history_reconstructs_terminal_response_item_reasoning():
	from browser_use.beta.service import _history_from_events

	history = _history_from_events(
		[
			{'event_type': 'model.turn.request', 'payload': {'model': 'gpt-test'}},
			{'event_type': 'model.thinking_delta', 'payload': {'text': 'stale thinking'}},
			{'event_type': 'model.turn.retry', 'payload': {'attempt': 1, 'max_retries': 3}},
			{
				'event_type': 'model.response.output_item',
				'payload': {
					'item': {
						'type': 'reasoning',
						'summary': [
							{'type': 'summary_text', 'text': 'checking '},
							{'type': 'summary_text', 'text': 'page'},
						],
					}
				},
			},
			{
				'event_type': 'model.response.output_item',
				'payload': {
					'item': {
						'type': 'message',
						'role': 'assistant',
						'content': [{'type': 'output_text', 'text': 'I will inspect the page.'}],
					}
				},
			},
			{
				'type': 'model.tool_call',
				'payload': {
					'id': 'call-browser',
					'name': 'browser_script',
					'arguments': {'code': "goto_url('https://example.com')"},
				},
			},
			{
				'type': 'tool.output',
				'payload': {
					'name': 'browser_script',
					'tool_call_id': 'call-browser',
					'text': 'Opened Example Domain',
				},
			},
			{'event_type': 'session.done', 'payload': {'result': 'Example Domain'}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	output = history.model_outputs()[0]
	thought = history.model_thoughts()[0]

	assert output.thinking == 'checking page'
	assert output.memory == 'I will inspect the page.'
	assert thought.thinking == 'checking page'
	assert 'stale' not in (thought.thinking or '')
	assert history.action_history()[0][0]['result'] == 'Opened Example Domain'


def test_rust_history_reconstructs_terminal_token_count_usage():
	from browser_use.beta.service import _history_from_events

	history = _history_from_events(
		[
			{
				'event_type': 'token_count',
				'payload': {
					'info': {
						'last_token_usage': {
							'cached_input_tokens': 2,
							'input_tokens': 5,
							'output_tokens': 7,
							'total_tokens': 12,
						},
						'total_token_usage': {
							'cached_input_tokens': 13,
							'input_tokens': 29,
							'output_tokens': 31,
							'total_tokens': 60,
						},
					}
				},
			},
			{'event_type': 'session.done', 'payload': {'result': 'final answer'}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	assert history.usage is not None
	assert history.usage.total_prompt_tokens == 29
	assert history.usage.total_prompt_cached_tokens == 13
	assert history.usage.total_completion_tokens == 31
	assert history.usage.total_tokens == 60
	assert history.usage.entry_count == 1
	assert history.usage.by_model['gpt-test'].prompt_tokens == 29
	assert history.usage.by_model['gpt-test'].completion_tokens == 31


def test_rust_history_sums_token_count_last_usage_when_latest_total_underreports():
	from browser_use.beta.service import _history_from_events

	history = _history_from_events(
		[
			{
				'event_type': 'token_count',
				'payload': {
					'info': {
						'last_token_usage': {
							'cached_input_tokens': 20,
							'input_tokens': 100,
							'output_tokens': 10,
							'total_tokens': 110,
						},
						'total_token_usage': {
							'cached_input_tokens': 20,
							'input_tokens': 100,
							'output_tokens': 10,
							'total_tokens': 110,
						},
					}
				},
			},
			{
				'event_type': 'token_count',
				'payload': {
					'info': {
						'last_token_usage': {
							'cached_input_tokens': 80,
							'input_tokens': 200,
							'output_tokens': 20,
							'total_tokens': 220,
						},
						# Some terminal recompute paths preserve only the latest context
						# counters here. Dashboard usage should still reflect the full run.
						'total_token_usage': {
							'cached_input_tokens': 80,
							'input_tokens': 200,
							'output_tokens': 20,
							'total_tokens': 220,
						},
					}
				},
			},
			{'event_type': 'session.done', 'payload': {'result': 'final answer'}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	assert history.usage is not None
	assert history.usage.total_prompt_tokens == 300
	assert history.usage.total_prompt_cached_tokens == 100
	assert history.usage.total_completion_tokens == 30
	assert history.usage.total_tokens == 330
	assert history.usage.entry_count == 2


def test_rust_history_reconstructs_terminal_reasoning_token_usage():
	from browser_use.beta.service import _history_from_events

	history = _history_from_events(
		[
			{
				'event_type': 'token_count',
				'payload': {
					'info': {
						'last_token_usage': {
							'cached_input_tokens': 2,
							'input_tokens': 50,
							'output_tokens': 20,
							'reasoning_output_tokens': 5,
							'total_tokens': 75,
						},
						'total_token_usage': {
							'cached_input_tokens': 10,
							'input_tokens': 100,
							'output_tokens': 40,
							'reasoning_output_tokens': 15,
							'total_tokens': 155,
						},
					}
				},
			},
			{'event_type': 'session.done', 'payload': {'result': 'final answer'}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	assert history.usage is not None
	assert history.usage.total_prompt_tokens == 100
	assert history.usage.total_prompt_cached_tokens == 10
	assert history.usage.total_completion_tokens == 55
	assert history.usage.total_tokens == 155
	assert history.usage.entry_count == 1
	assert history.usage.by_model['gpt-test'].completion_tokens == 55
	assert history.usage.by_model['gpt-test'].total_tokens == 155


def test_rust_history_reconstructs_terminal_nested_model_usage():
	from browser_use.beta.service import _history_from_events

	history = _history_from_events(
		[
			{
				'event_type': 'model.usage',
				'payload': {
					'usage': {
						'input_tokens': 17,
						'cached_input_tokens': 5,
						'output_tokens': 11,
					},
					'cost_usd': 0.0123,
				},
			},
			{'event_type': 'session.done', 'payload': {'result': 'final answer'}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	assert history.usage is not None
	assert history.usage.total_prompt_tokens == 17
	assert history.usage.total_prompt_cached_tokens == 5
	assert history.usage.total_completion_tokens == 11
	assert history.usage.total_tokens == 28
	assert history.usage.total_cost == 0.0123
	assert history.usage.entry_count == 1
	assert history.usage.by_model['gpt-test'].prompt_tokens == 17
	assert history.usage.by_model['gpt-test'].completion_tokens == 11
	assert history.usage.by_model['gpt-test'].cost == 0.0123


def test_rust_history_token_count_does_not_shrink_model_usage_totals():
	from browser_use.beta.service import _history_from_events

	history = _history_from_events(
		[
			{
				'event_type': 'model.usage',
				'payload': {
					'input_tokens': 120_000,
					'cached_input_tokens': 119_000,
					'input_cache_creation_tokens': 4_000,
					'output_tokens': 2_000,
					'total_tokens': 126_000,
				},
			},
			{
				'event_type': 'token_count',
				'payload': {
					'info': {
						'last_token_usage': {
							'input_tokens': 8_000,
							'cached_input_tokens': 7_000,
							'output_tokens': 200,
							'total_tokens': 8_200,
						},
						'total_token_usage': {
							'input_tokens': 8_000,
							'cached_input_tokens': 7_000,
							'output_tokens': 200,
							'total_tokens': 8_200,
						},
					},
				},
			},
			{'event_type': 'session.done', 'payload': {'result': 'final answer'}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	assert history.usage is not None
	assert history.usage.total_prompt_tokens == 120_000
	assert history.usage.total_prompt_cached_tokens == 119_000
	assert history.usage.total_prompt_cache_creation_tokens == 4_000
	assert history.usage.total_completion_tokens == 2_000
	assert history.usage.total_tokens == 126_000
	assert history.usage.entry_count == 1


async def test_rust_terminal_usage_prices_token_count_events(monkeypatch):
	from browser_use.beta.service import _usage_from_events_with_costs
	from browser_use.tokens.service import TokenCost

	async def fail_fetch(_self):
		raise AssertionError('custom model pricing should not fetch remote pricing')

	monkeypatch.setattr(TokenCost, '_fetch_and_cache_pricing_data', fail_fetch)

	events = [
		{
			'event_type': 'token_count',
			'payload': {
				'info': {
					'last_token_usage': {
						'cached_input_tokens': 20,
						'input_tokens': 100,
						'output_tokens': 10,
						'total_tokens': 110,
					},
					'total_token_usage': {
						'cached_input_tokens': 20,
						'input_tokens': 100,
						'output_tokens': 10,
						'total_tokens': 110,
					},
				},
			},
		},
		{
			'event_type': 'token_count',
			'payload': {
				'info': {
					'last_token_usage': {
						'cached_input_tokens': 0,
						'input_tokens': 200,
						'output_tokens': 20,
						'total_tokens': 220,
					},
					'total_token_usage': {
						'cached_input_tokens': 20,
						'input_tokens': 300,
						'output_tokens': 30,
						'total_tokens': 330,
					},
				},
			},
		},
	]

	summary = await _usage_from_events_with_costs(events, 'claude-sonnet-4-6', TokenCost(include_cost=True))

	assert summary.total_prompt_tokens == 300
	assert summary.total_prompt_cached_tokens == 20
	assert summary.total_prompt_cache_creation_tokens == 0
	assert summary.total_completion_tokens == 30
	assert summary.total_tokens == 330
	assert summary.entry_count == 2
	assert summary.total_prompt_cost == pytest.approx(0.000846)
	assert summary.total_prompt_cached_cost == pytest.approx(0.000006)
	assert summary.total_prompt_cache_creation_cost == pytest.approx(0.0)
	assert summary.total_completion_cost == pytest.approx(0.00045)
	assert summary.total_cost == pytest.approx(0.001296)
	assert summary.by_model['claude-sonnet-4-6'].cost == pytest.approx(0.001296)


async def test_rust_terminal_usage_prices_anthropic_raw_cache_reads(monkeypatch):
	from browser_use.beta.service import _usage_from_events_with_costs
	from browser_use.tokens.service import TokenCost

	async def fail_fetch(_self):
		raise AssertionError('custom model pricing should not fetch remote pricing')

	monkeypatch.setattr(TokenCost, '_fetch_and_cache_pricing_data', fail_fetch)

	events = [
		{
			'event_type': 'model.usage',
			'payload': {
				'usage': {
					'input_tokens': 12,
					'cache_read_input_tokens': 183250,
					'cache_creation_input_tokens': 44,
					'output_tokens': 3088,
				},
			},
		},
	]

	summary = await _usage_from_events_with_costs(events, 'claude-sonnet-4-6', TokenCost(include_cost=True))

	assert summary.total_prompt_tokens == 183262
	assert summary.total_prompt_cached_tokens == 183250
	assert summary.total_prompt_cache_creation_tokens == 44
	assert summary.total_completion_tokens == 3088
	assert summary.total_tokens == 186394
	assert summary.total_prompt_cost == pytest.approx(0.055176)
	assert summary.total_prompt_cached_cost == pytest.approx(0.054975)
	assert summary.total_prompt_cache_creation_cost == pytest.approx(0.000165)
	assert summary.total_completion_cost == pytest.approx(0.04632)
	assert summary.total_cost == pytest.approx(0.101496)
	assert summary.by_model['claude-sonnet-4-6'].prompt_tokens == 183262
	assert summary.by_model['claude-sonnet-4-6'].cost == pytest.approx(0.101496)


async def test_rust_terminal_usage_sums_token_count_cache_creation(monkeypatch):
	from browser_use.beta.service import _usage_from_events_with_costs
	from browser_use.tokens.service import TokenCost

	async def fail_fetch(_self):
		raise AssertionError('custom model pricing should not fetch remote pricing')

	monkeypatch.setattr(TokenCost, '_fetch_and_cache_pricing_data', fail_fetch)

	events = [
		{
			'event_type': 'token_count',
			'payload': {
				'info': {
					'last_token_usage': {
						'cached_input_tokens': 0,
						'input_cache_creation_tokens': 18462,
						'input_tokens': 3,
						'output_tokens': 71,
						'total_tokens': 18536,
					},
					'total_token_usage': {
						'cached_input_tokens': 0,
						'input_cache_creation_tokens': 18462,
						'input_tokens': 3,
						'output_tokens': 71,
						'total_tokens': 18536,
					},
				},
			},
		},
		{
			'event_type': 'token_count',
			'payload': {
				'info': {
					'last_token_usage': {
						'cached_input_tokens': 18462,
						'input_cache_creation_tokens': 1506,
						'input_tokens': 18463,
						'output_tokens': 177,
						'total_tokens': 20146,
					},
					'total_token_usage': {
						'cached_input_tokens': 18462,
						'input_tokens': 18466,
						'output_tokens': 248,
						'total_tokens': 38682,
					},
				},
			},
		},
		{
			'event_type': 'token_count',
			'payload': {
				'info': {
					'last_token_usage': {
						'cached_input_tokens': 18462,
						'input_cache_creation_tokens': 5067,
						'input_tokens': 18463,
						'output_tokens': 182,
						'total_tokens': 23712,
					},
					'total_token_usage': {
						'cached_input_tokens': 36924,
						'input_tokens': 36929,
						'output_tokens': 430,
						'total_tokens': 62394,
					},
				},
			},
		},
	]

	summary = await _usage_from_events_with_costs(events, 'claude-sonnet-4-6', TokenCost(include_cost=True))

	assert summary.total_prompt_tokens == 36929
	assert summary.total_prompt_cached_tokens == 36924
	assert summary.total_prompt_cache_creation_tokens == 25035
	assert summary.total_completion_tokens == 430
	assert summary.total_tokens == 62394
	assert summary.total_prompt_cost == pytest.approx(0.10497345)
	assert summary.total_prompt_cached_cost == pytest.approx(0.0110772)
	assert summary.total_prompt_cache_creation_cost == pytest.approx(0.09388125)
	assert summary.total_completion_cost == pytest.approx(0.00645)
	assert summary.total_cost == pytest.approx(0.11142345)


async def test_rust_terminal_usage_priced_summary_sums_cache_read_tokens(monkeypatch):
	from browser_use.beta.service import _usage_from_events_with_costs
	from browser_use.tokens.service import TokenCost

	async def fail_fetch(_self):
		raise AssertionError('custom model pricing should not fetch remote pricing')

	monkeypatch.setattr(TokenCost, '_fetch_and_cache_pricing_data', fail_fetch)

	events = [
		{
			'event_type': 'token_count',
			'payload': {
				'info': {
					'last_token_usage': {
						'cached_input_tokens': 1000,
						'input_cache_creation_tokens': 200,
						'input_tokens': 1001,
						'output_tokens': 10,
						'total_tokens': 1211,
					},
					'total_token_usage': {
						'cached_input_tokens': 1000,
						'input_cache_creation_tokens': 200,
						'input_tokens': 1001,
						'output_tokens': 10,
						'total_tokens': 1211,
					},
				},
			},
		},
		{
			'event_type': 'token_count',
			'payload': {
				'info': {
					'last_token_usage': {
						'cached_input_tokens': 1000,
						'input_cache_creation_tokens': 50,
						'input_tokens': 1001,
						'output_tokens': 20,
						'total_tokens': 1071,
					},
					'total_token_usage': {
						'cached_input_tokens': 1000,
						'input_cache_creation_tokens': 200,
						'input_tokens': 1001,
						'output_tokens': 30,
						'total_tokens': 1231,
					},
				},
			},
		},
	]

	summary = await _usage_from_events_with_costs(events, 'claude-sonnet-4-6', TokenCost(include_cost=True))

	assert summary.entry_count == 2
	assert summary.total_prompt_tokens == 2002
	assert summary.total_prompt_cached_tokens == 2000
	assert summary.total_prompt_cache_creation_tokens == 250
	assert summary.total_completion_tokens == 30
	assert summary.total_tokens == 2282
	assert summary.total_prompt_cached_cost == pytest.approx(2000 * (0.30 / 1_000_000))
	assert summary.total_prompt_cache_creation_cost == pytest.approx(250 * (3.75 / 1_000_000))
	assert summary.total_completion_cost == pytest.approx(30 * (15 / 1_000_000))
	assert summary.by_model['claude-sonnet-4-6'].prompt_tokens == 2002
	assert summary.by_model['claude-sonnet-4-6'].total_tokens == 2282
	assert summary.by_model['claude-sonnet-4-6'].invocations == 2


def test_rust_terminal_usage_mixed_events_do_not_shrink_totals():
	from browser_use.beta.service import _usage_from_events

	summary = _usage_from_events(
		[
			{
				'event_type': 'model.usage',
				'payload': {
					'usage': {
						'input_tokens': 500,
						'cached_input_tokens': 200,
						'input_cache_creation_tokens': 50,
						'output_tokens': 20,
						'total_tokens': 570,
					}
				},
			},
			{
				'event_type': 'token_count',
				'payload': {
					'info': {
						'total_token_usage': {
							'input_tokens': 10,
							'cached_input_tokens': 5,
							'output_tokens': 1,
							'total_tokens': 11,
						}
					}
				},
			},
		],
		'claude-sonnet-4-6',
	)

	assert summary.total_prompt_tokens == 500
	assert summary.total_prompt_cached_tokens == 200
	assert summary.total_prompt_cache_creation_tokens == 50
	assert summary.total_completion_tokens == 20
	assert summary.total_tokens == 570


def test_rust_sdk_event_dedupe_removes_projected_usage_duplicates():
	from browser_use.beta.service import _dedupe_sdk_events, _usage_from_events

	usage_payload = {
		'info': {
			'last_token_usage': {
				'input_tokens': 100,
				'cached_input_tokens': 40,
				'input_cache_creation_tokens': 10,
				'output_tokens': 5,
				'total_tokens': 115,
			},
			'total_token_usage': {
				'input_tokens': 100,
				'cached_input_tokens': 40,
				'input_cache_creation_tokens': 10,
				'output_tokens': 5,
				'total_tokens': 115,
			},
		}
	}
	events = [
		{'seq': 1, 'id': 'usage-id', 'event_type': 'token_count', 'payload': usage_payload},
		{'seq': 1, 'event_type': 'token_count', 'payload': usage_payload},
		{'seq': 2, 'event_type': 'session.done', 'payload': {'result': 'done'}},
		{'seq': 2, 'id': 'done-id', 'event_type': 'session.done', 'payload': {'result': 'done'}},
	]

	deduped = _dedupe_sdk_events(events)
	summary = _usage_from_events(deduped, 'claude-sonnet-4-6')

	assert len(deduped) == 2
	assert deduped[0]['id'] == 'usage-id'
	assert deduped[1]['id'] == 'done-id'
	assert summary.entry_count == 1
	assert summary.total_prompt_tokens == 100
	assert summary.total_prompt_cached_tokens == 40
	assert summary.total_prompt_cache_creation_tokens == 10
	assert summary.total_completion_tokens == 5
	assert summary.total_tokens == 115


async def test_rust_terminal_priced_usage_prefers_model_usage_over_token_count(monkeypatch):
	from browser_use.beta.service import _usage_from_events_with_costs
	from browser_use.tokens.service import TokenCost

	async def fail_fetch(_self):
		raise AssertionError('custom model pricing should not fetch remote pricing')

	monkeypatch.setattr(TokenCost, '_fetch_and_cache_pricing_data', fail_fetch)

	summary = await _usage_from_events_with_costs(
		[
			{
				'event_type': 'model.usage',
				'payload': {
					'input_tokens': 500,
					'cached_input_tokens': 200,
					'input_cache_creation_tokens': 50,
					'output_tokens': 20,
					'total_tokens': 570,
				},
			},
			{
				'event_type': 'token_count',
				'payload': {
					'info': {
						'last_token_usage': {
							'input_tokens': 500,
							'cached_input_tokens': 200,
							'input_cache_creation_tokens': 50,
							'output_tokens': 20,
							'total_tokens': 570,
						},
						'total_token_usage': {
							'input_tokens': 500,
							'cached_input_tokens': 200,
							'input_cache_creation_tokens': 50,
							'output_tokens': 20,
							'total_tokens': 570,
						},
					}
				},
			},
		],
		'claude-sonnet-4-6',
		TokenCost(include_cost=True),
	)

	assert summary.total_prompt_tokens == 500
	assert summary.total_prompt_cached_tokens == 200
	assert summary.total_prompt_cache_creation_tokens == 50
	assert summary.total_completion_tokens == 20
	assert summary.total_tokens == 570
	assert summary.entry_count == 1
	assert summary.total_prompt_cached_cost == pytest.approx(200 * (0.30 / 1_000_000))
	assert summary.total_prompt_cache_creation_cost == pytest.approx(50 * (3.75 / 1_000_000))
	assert summary.total_completion_cost == pytest.approx(20 * (15 / 1_000_000))
	assert summary.total_cost == pytest.approx((300 * 3 + 200 * 0.30 + 50 * 3.75 + 20 * 15) / 1_000_000)


async def test_rust_token_summary_does_not_double_count_cache_reads(monkeypatch):
	from browser_use.llm.views import ChatInvokeUsage
	from browser_use.tokens.service import TokenCost

	async def fail_fetch(_self):
		raise AssertionError('custom model pricing should not fetch remote pricing')

	monkeypatch.setattr(TokenCost, '_fetch_and_cache_pricing_data', fail_fetch)

	token_cost = TokenCost(include_cost=True)
	token_cost.add_usage(
		'claude-sonnet-4-6',
		ChatInvokeUsage(
			prompt_tokens=110,
			prompt_cached_tokens=100,
			prompt_cache_creation_tokens=40,
			prompt_image_tokens=None,
			completion_tokens=20,
			total_tokens=170,
		),
	)

	summary = await token_cost.get_usage_summary()

	assert summary.total_prompt_cost == pytest.approx(0.00021)
	assert summary.total_prompt_cached_cost == pytest.approx(0.00003)
	assert summary.total_prompt_cache_creation_tokens == 40
	assert summary.total_prompt_cache_creation_cost == pytest.approx(0.00015)
	assert summary.total_completion_cost == pytest.approx(0.0003)
	assert summary.total_cost == pytest.approx(0.00051)
	assert summary.by_model['claude-sonnet-4-6'].cost == pytest.approx(summary.total_cost)


def test_rust_history_supports_structured_output():
	from browser_use.beta.service import _history_from_events

	class Answer(BaseModel):
		answer: str

	history = _history_from_events(
		[{'event_type': 'session.done', 'payload': {'result': '{"answer": "ok"}'}}],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=Answer,
		process_error=None,
	)

	assert isinstance(history.structured_output, Answer)
	assert history.structured_output.answer == 'ok'


def test_rust_history_extracts_fenced_structured_output():
	from browser_use.beta.service import _history_from_events

	class Answer(BaseModel):
		answer: str

	history = _history_from_events(
		[{'event_type': 'session.done', 'payload': {'result': 'Here is the answer:\n```json\n{"answer": "ok"}\n```'}}],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=Answer,
		process_error=None,
	)

	assert history.final_result() == '{"answer": "ok"}'
	assert isinstance(history.structured_output, Answer)
	assert history.structured_output.answer == 'ok'


def test_rust_history_reconstructs_terminal_agent_completed_result():
	from browser_use.beta.service import _history_from_events

	history = _history_from_events(
		[
			{
				'event_type': 'agent.completed',
				'payload': {
					'child_session_id': 'child-1',
					'status': 'done',
					'payload': {'result': 'child answer\n'},
				},
			}
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	session_done_history = _history_from_events(
		[
			{
				'event_type': 'agent.completed',
				'payload': {
					'child_session_id': 'child-1',
					'status': 'done',
					'payload': {'result': 'child answer'},
				},
			},
			{'event_type': 'session.done', 'payload': {'result': 'parent answer'}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	assert history.final_result() == 'child answer'
	assert history.is_done() is True
	assert history.action_names() == ['done']
	assert history.last_action() == {'done': {'text': 'child answer', 'success': True}}
	assert session_done_history.final_result() == 'parent answer'


def test_rust_history_exposes_result_file_attachments():
	from browser_use.beta.service import _history_from_events

	history = _history_from_events(
		[
			{
				'event_type': 'session.done',
				'payload': {
					'result': 'Saved structured report.',
					'result_file': {'url': 'file:///tmp/report.json', 'path': '/tmp/report.json', 'bytes': 123},
				},
			}
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	results = history.action_results()

	assert history.final_result() == 'Saved structured report.'
	assert results[0].attachments == ['file:///tmp/report.json']


def test_rust_history_reconstructs_terminal_artifact_attachments():
	from browser_use.beta.service import _history_from_events

	history = _history_from_events(
		[
			{
				'type': 'tool.started',
				'payload': {
					'name': 'browser_script',
					'tool_call_id': 'call-artifacts',
					'arguments': {'code': "write_file('report.csv', rows)"},
				},
			},
			{
				'type': 'tool.output',
				'payload': {
					'name': 'browser_script',
					'tool_call_id': 'call-artifacts',
					'text': 'Generated report.csv',
					'artifacts': [
						{'path': '/tmp/report.csv', 'kind': 'file', 'mime': 'text/csv'},
						{'path': '/tmp/screenshot.png', 'kind': 'image', 'mime_type': 'image/png'},
					],
				},
			},
			{
				'type': 'artifact.created',
				'payload': {
					'name': 'browser_script',
					'tool_call_id': 'call-artifacts',
					'artifact': {'path': '/tmp/report.csv', 'kind': 'file', 'mime': 'text/csv'},
				},
			},
			{
				'type': 'tool.output_spilled',
				'payload': {
					'name': 'browser_script',
					'tool_call_id': 'call-large',
					'artifact': {'path': '/tmp/large-output.txt', 'original_tokens_estimate': 75000},
				},
			},
			{
				'event_type': 'session.done',
				'payload': {
					'result': 'Generated reports.',
					'result_file': {'url': 'file:///tmp/final.json', 'path': '/tmp/final.json'},
				},
			},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	attachments = ['/tmp/report.csv', '/tmp/large-output.txt', 'file:///tmp/final.json']

	assert history.final_result() == 'Generated reports.'
	assert history.action_results()[-1].attachments == attachments
	assert history.last_action() == {'done': {'text': 'Generated reports.', 'success': True, 'files_to_display': attachments}}


def test_rust_history_reconstructs_terminal_capture_curation_gif_attachment():
	from browser_use.beta.service import _history_from_events

	history = _history_from_events(
		[
			{
				'event_type': 'capture.curation',
				'payload': {
					'source': 'fallback_uncurated',
					'gif_path': '/tmp/browser-use-agent/capture-summary.gif',
				},
			},
			{
				'event_type': 'artifact.created',
				'payload': {
					'name': 'capture',
					'artifact': {
						'path': '/tmp/browser-use-agent/capture-summary.gif',
						'kind': 'summary_gif',
						'mime': 'image/gif',
					},
				},
			},
			{'event_type': 'session.done', 'payload': {'result': 'Generated browser summary.'}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	attachments = ['/tmp/browser-use-agent/capture-summary.gif']

	assert history.action_results()[-1].attachments == attachments
	assert history.last_action() == {
		'done': {'text': 'Generated browser summary.', 'success': True, 'files_to_display': attachments}
	}


def test_rust_history_reconstructs_terminal_text_artifact_attachments():
	from browser_use.beta.service import _history_from_events

	history = _history_from_events(
		[
			{
				'type': 'tool.started',
				'payload': {
					'name': 'python',
					'arguments': {'code': "print('large report')"},
				},
			},
			{
				'type': 'tool.output',
				'payload': {
					'name': 'python',
					'ok': True,
					'text': 'large report...',
					'text_truncated': True,
					'text_artifact': {
						'artifact_id': 'tool-output-python-1234',
						'path': '/tmp/artifacts/session/tool-output-python-1234.txt',
						'file_name': 'tool-output-python-1234.txt',
						'bytes': 8192,
						'preview': 'large report...',
						'token_budget': 2048,
					},
				},
			},
			{'event_type': 'session.done', 'payload': {'result': 'Generated large report.'}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	attachments = ['/tmp/artifacts/session/tool-output-python-1234.txt']

	assert history.action_history()[0][0]['result'] == 'large report...'
	assert history.action_results()[-1].attachments == attachments
	assert history.last_action() == {
		'done': {'text': 'Generated large report.', 'success': True, 'files_to_display': attachments}
	}


def test_beta_agent_translates_browser_use_args_to_terminal(monkeypatch):
	from browser_use.beta import Agent

	class LLM:
		model = 'gpt-test'

	class Browser:
		cdp_url = 'wss://browser.example/devtools/browser/1'

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')
	agent = Agent(
		task='report title',
		llm=LLM(),
		browser_session=Browser(),
		initial_actions=[{'go_to_url': {'url': 'https://example.com'}}],
	)

	env = agent._run_env()
	server_argv = agent._sdk_server_argv()

	assert server_argv == ['/tmp/browser-use-terminal', 'sdk-server', '--transport', 'stdio']
	assert "First navigate to 'https://example.com'" in agent.task
	assert env['BU_CDP_URL'] == 'wss://browser.example/devtools/browser/1'
	assert env['LLM_BROWSER_BROWSER_MODE'] == 'remote-cdp'
	assert env['BROWSER_USE_PYTHON'] == sys.executable
	assert 'BUT_FULL_LLM_INPUT_EVENTS' not in env

	params = agent._sdk_run_params(max_steps=12, task=agent.task)
	assert params['max_steps'] == 12
	assert params['browser_mode'] == 'remote-cdp'
	assert params['llm'] == {'provider': 'browser-use', 'model': 'gpt-test', 'timeout': 75}
	assert params['browser']['cdp_url'] == 'wss://browser.example/devtools/browser/1'
	assert 'cdp_headers' not in params['browser']
	assert params['config_overrides'] == {'full_llm_input_events': True}
	assert "First navigate to 'https://example.com'" in params['task']


def test_rust_terminal_binary_missing_error_mentions_install(monkeypatch):
	import browser_use.beta.service as beta_service

	monkeypatch.delenv('BROWSER_USE_TERMINAL_BINARY', raising=False)
	monkeypatch.setitem(sys.modules, 'browser_use_core', None)
	monkeypatch.setattr(beta_service.Path, 'exists', lambda self: False)
	monkeypatch.setattr(beta_service.shutil, 'which', lambda binary: None)

	with pytest.raises(beta_service.BetaAgentError) as exc_info:
		beta_service.find_browser_use_terminal_binary()

	message = str(exc_info.value)
	assert 'https://browser-use.com/terminal/install.sh' in message
	assert 'browser-use-core' in message
	assert 'BROWSER_USE_TERMINAL_BINARY' in message


def test_rust_terminal_binary_prefers_packaged_binary(monkeypatch):
	import browser_use.beta.service as beta_service

	class PackagedCore:
		@staticmethod
		def binary_path(binary_name):
			assert binary_name == 'browser-use-terminal'
			return '/tmp/packaged-browser-use-terminal'

	monkeypatch.delenv('BROWSER_USE_TERMINAL_BINARY', raising=False)
	monkeypatch.setitem(sys.modules, 'browser_use_core', PackagedCore)
	monkeypatch.setattr(beta_service.Path, 'exists', lambda self: False)
	monkeypatch.setattr(beta_service.shutil, 'which', lambda binary_name: None)

	assert beta_service.find_browser_use_terminal_binary() == '/tmp/packaged-browser-use-terminal'


def test_beta_agent_run_env_sets_packaged_agent_tools_dir(monkeypatch, tmp_path):
	from browser_use.beta import Agent

	class LLM:
		model = 'gpt-test'

	package_dir = tmp_path / 'browser_use_core'
	terminal = package_dir / 'bin' / 'browser-use-terminal'
	agent_tools = package_dir / 'bin' / 'agent-tools'
	terminal.parent.mkdir(parents=True)
	agent_tools.mkdir(parents=True)
	terminal.write_text('#!/bin/sh\n')
	(agent_tools / 'rg').write_text('#!/bin/sh\n')

	class PackagedCore:
		@staticmethod
		def agent_tools_dir():
			return str(agent_tools)

		@staticmethod
		def binary_path(binary_name):
			assert binary_name == 'browser-use-terminal'
			return str(terminal)

	monkeypatch.delenv('BROWSER_USE_TERMINAL_BINARY', raising=False)
	monkeypatch.delenv('BUT_AGENT_TOOLS_DIR', raising=False)
	monkeypatch.setenv('PATH', '/usr/bin')
	monkeypatch.setitem(sys.modules, 'browser_use_core', PackagedCore)

	agent = Agent(task='report title', llm=LLM())
	env = agent._run_env()

	assert env['BUT_AGENT_TOOLS_DIR'] == str(agent_tools)
	assert env['PATH'].split(os.pathsep)[0] == str(agent_tools)


def test_beta_agent_run_env_preserves_explicit_agent_tools_dir(monkeypatch, tmp_path):
	from browser_use.beta import Agent

	class LLM:
		model = 'gpt-test'

	agent_tools = tmp_path / 'agent-tools'
	agent_tools.mkdir()
	(agent_tools / 'rg').write_text('#!/bin/sh\n')

	monkeypatch.setenv('BUT_AGENT_TOOLS_DIR', str(agent_tools))
	monkeypatch.setenv('PATH', '/usr/bin')

	agent = Agent(task='report title', llm=LLM())
	env = agent._run_env()

	assert env['BUT_AGENT_TOOLS_DIR'] == str(agent_tools)
	assert env['PATH'].split(os.pathsep)[0] == str(agent_tools)


def test_rust_terminal_binary_finds_default_terminal_install(monkeypatch, tmp_path):
	import browser_use.beta.service as beta_service

	binary = tmp_path / '.browser-use-terminal' / 'packages' / 'standalone' / 'current' / 'bin' / 'browser-use-terminal'
	binary.parent.mkdir(parents=True)
	binary.write_text('#!/bin/sh\nif [ "$1" = "--help" ]; then\n  echo "sdk-server"\nfi\n')
	binary.chmod(0o755)

	monkeypatch.delenv('BROWSER_USE_TERMINAL_BINARY', raising=False)
	monkeypatch.setitem(sys.modules, 'browser_use_core', None)
	monkeypatch.chdir(tmp_path)
	monkeypatch.setenv('BUT_HOME', str(tmp_path / '.browser-use-terminal'))
	monkeypatch.setenv('BUT_INSTALL_DIR', str(tmp_path / '.local' / 'bin'))
	monkeypatch.setattr(beta_service.shutil, 'which', lambda binary_name: None)

	assert beta_service.find_browser_use_terminal_binary() == str(binary)


def test_rust_terminal_binary_from_installed_browser_use_core_answers_ping(monkeypatch):
	browser_use_core = pytest.importorskip('browser_use_core')
	import browser_use.beta.service as beta_service

	monkeypatch.delenv('BROWSER_USE_TERMINAL_BINARY', raising=False)

	binary = beta_service.find_browser_use_terminal_binary()
	assert binary == browser_use_core.binary_path('browser-use-terminal')

	proc = subprocess.run(
		[binary, 'sdk-server', '--transport', 'stdio'],
		input='{"jsonrpc":"2.0","id":1,"method":"runtime.ping","params":{}}\n',
		text=True,
		capture_output=True,
		timeout=10,
		check=True,
	)
	response = json.loads(proc.stdout.strip())
	assert response['result']['ok'] is True
	assert response['result']['sdk_protocol_version'] == 1


async def test_rust_sdk_client_start_wraps_missing_binary_error():
	import browser_use.beta.service as beta_service

	client = beta_service.RustSdkClient(['/definitely/missing-browser-use-terminal'], env={})

	with pytest.raises(beta_service.BetaAgentError) as exc_info:
		await client.start()

	message = str(exc_info.value)
	assert '/definitely/missing-browser-use-terminal' in message
	assert 'https://browser-use.com/terminal/install.sh' in message


def test_beta_agent_sdk_params_leave_terminal_tools_unrestricted(monkeypatch):
	from browser_use.beta import Agent

	class LLM:
		model = 'gpt-test'

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')
	agent = Agent(task='use the best available terminal tools', llm=LLM(), directly_open_url=False)

	params = agent._sdk_run_params(max_steps=8, task=agent.task)

	assert params['config_overrides'] == {'full_llm_input_events': True}
	assert 'tool_allowlist' not in json.dumps(params)


def test_beta_agent_sdk_browser_payload_includes_profile_domains_window_and_proxy(monkeypatch, tmp_path):
	from browser_use.beta import Agent

	class BrowserProfile:
		cdp_url = 'http://127.0.0.1:9222'
		allowed_domains = ['example.com']
		prohibited_domains = ['*.tracking.example']
		window_size = {'width': 1440, 'height': 900}
		proxy_country_code = 'DE'
		state_dir = tmp_path

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')

	agent = Agent(task='report title', llm=type('LLM', (), {'model': 'gpt-test'})(), browser_profile=BrowserProfile())
	params = agent._sdk_run_params(max_steps=4, task=agent.task)

	assert params['browser_mode'] == 'remote-cdp'
	assert params['browser']['cdp_url'] == 'http://127.0.0.1:9222'
	assert params['browser']['allowed_domains'] == ['example.com']
	assert params['browser']['blocked_domains'] == ['*.tracking.example']
	assert params['browser']['window_size'] == {'width': 1440, 'height': 900}
	assert params['browser']['proxy_country_code'] == 'DE'
	assert params['browser']['state_dir'] == str(tmp_path)


async def test_beta_agent_runs_through_sdk_and_reuses_session_for_followup(monkeypatch):
	from browser_use.beta import Agent, BrowserProfile, BrowserSession

	class LLM:
		model = 'fake'

	class FakeSdk:
		def __init__(self):
			self.calls = []
			self.stderr_lines = []

		async def call(self, method, params):
			self.calls.append((method, params))
			if method == 'agent.run_task':
				return {
					'agent_id': 'agent-1',
					'session_id': 'session-1',
					'browser_id': 'browser-1',
					'history': {
						'output': 'first done',
						'success': True,
						'done': True,
						'errors': [],
						'events': [
							{'event_type': 'session.input', 'payload': {'text': params['task']}},
							{'event_type': 'session.done', 'payload': {'result': 'first done', 'success': True}},
						],
					},
				}
			if method == 'agent.run':
				return {
					'agent_id': params['agent_id'],
					'session_id': 'session-1',
					'browser_id': params['browser_id'],
					'history': {
						'output': 'followup done',
						'success': True,
						'done': True,
						'errors': [],
						'events': [
							{'event_type': 'session.followup', 'payload': {'text': params['followups'][0]}},
							{'event_type': 'session.done', 'payload': {'result': 'followup done', 'success': True}},
						],
					},
				}
			raise AssertionError(f'unexpected SDK method {method}')

	fake_sdk = FakeSdk()

	async def fake_ensure_sdk_client(self):
		self._sdk_client = fake_sdk
		return fake_sdk

	monkeypatch.setattr(Agent, '_ensure_sdk_client', fake_ensure_sdk_client)

	browser_session = BrowserSession(browser_profile=BrowserProfile(keep_alive=True), id='browser-session-1')
	agent = Agent(task='answer first', llm=LLM(), browser_session=browser_session, directly_open_url=False)
	first = await agent.run(max_steps=7)
	followup = await agent.follow_up('answer second', max_steps=5)

	assert first.final_result() == 'first done'
	assert followup.final_result() == 'followup done'
	assert fake_sdk.calls[0][0] == 'agent.run_task'
	assert fake_sdk.calls[0][1]['task'] == 'answer first'
	assert fake_sdk.calls[0][1]['max_steps'] == 7
	assert fake_sdk.calls[1][0] == 'agent.run'
	assert fake_sdk.calls[1][1]['agent_id'] == 'agent-1'
	assert fake_sdk.calls[1][1]['browser_id'] == 'browser-1'
	assert fake_sdk.calls[1][1]['followups'] == ['answer second']
	assert fake_sdk.calls[1][1]['max_steps'] == 5


async def test_beta_agent_prices_sdk_child_usage_events_without_overriding_parent_result(monkeypatch):
	from browser_use.beta import Agent

	class LLM:
		model = 'fake'

	class FakeSdk:
		stderr_lines = []
		notifications = []

		async def call(self, method, params):
			assert method == 'agent.run_task'
			parent_events = [
				{'event_type': 'model.usage', 'payload': {'input_tokens': 7000, 'output_tokens': 20}},
				{'event_type': 'session.done', 'payload': {'result': 'parent answer', 'success': True}},
			]
			child_events = [
				{
					'event_type': 'model.usage',
					'session_id': 'child-1',
					'payload': {'input_tokens': 3000, 'cached_input_tokens': 1000, 'output_tokens': 10},
				},
				{'event_type': 'session.done', 'session_id': 'child-1', 'payload': {'result': 'child answer'}},
			]
			return {
				'agent_id': 'agent-1',
				'session_id': 'parent-1',
				'browser_id': 'browser-1',
				'history': {
					'output': 'parent answer',
					'success': True,
					'done': True,
					'errors': [],
					'events': parent_events,
					'child_events': child_events,
					'usage_events': [*parent_events, *child_events],
				},
			}

	fake_sdk = FakeSdk()

	async def fake_ensure_sdk_client(self):
		return fake_sdk

	monkeypatch.setattr(Agent, '_ensure_sdk_client', fake_ensure_sdk_client)

	agent = Agent(task='parent task', llm=LLM(), directly_open_url=False)
	history = await agent.run(max_steps=3)

	assert history.final_result() == 'parent answer'
	assert agent.last_events[-1]['payload']['result'] == 'parent answer'
	assert agent.last_child_events[-1]['payload']['result'] == 'child answer'
	assert history.usage is not None
	assert history.usage.total_prompt_tokens == 10_000
	assert history.usage.total_prompt_cached_tokens == 1000
	assert history.usage.total_completion_tokens == 30
	assert history.usage.entry_count == 2


async def test_beta_agent_recovers_final_result_from_sdk_notifications_after_transport_error(monkeypatch):
	from browser_use.beta import Agent

	class LLM:
		model = 'fake'

	class FakeSdk:
		stderr_lines = []

		def __init__(self):
			self.notifications = [
				{
					'method': 'agent.event',
					'params': {'event': {'seq': 1, 'id': 'event-1', 'event_type': 'session.input', 'payload': {'text': 'task'}}},
				},
				{
					'method': 'agent.event',
					'params': {
						'event': {
							'seq': 2,
							'id': 'event-2',
							'event_type': 'session.done',
							'payload': {'result': 'final from notification', 'success': True},
						}
					},
				},
			]

		async def call(self, method, params):
			raise RuntimeError('Rust SDK JSON-RPC line exceeded 536870912 bytes without newline')

	fake_sdk = FakeSdk()

	async def fake_ensure_sdk_client(self):
		return fake_sdk

	monkeypatch.setattr(Agent, '_ensure_sdk_client', fake_ensure_sdk_client)

	agent = Agent(task='task', llm=LLM(), directly_open_url=False)
	history = await agent.run(max_steps=3)

	assert history.final_result() == 'final from notification'
	assert history.is_successful() is True
	assert [event['event_type'] for event in agent.last_events] == ['session.input', 'session.done']


async def test_beta_agent_recovers_nested_sdk_notification_events(monkeypatch):
	from browser_use.beta import Agent

	class LLM:
		model = 'fake'

	class FakeSdk:
		stderr_lines = []

		def __init__(self):
			self.notifications = [
				{
					'method': 'agent.event',
					'params': {
						'event': {
							'kind': 'observed',
							'payload': {
								'seq': 1,
								'id': 'event-1',
								'event_type': 'session.input',
								'payload': {'text': 'task'},
							},
						}
					},
				},
				{
					'method': 'agent.event',
					'params': {
						'event': {
							'kind': 'observed',
							'payload': {
								'seq': 2,
								'id': 'event-2',
								'event_type': 'session.done',
								'payload': {'result': 'final from nested notification', 'success': True},
							},
						}
					},
				},
			]

		async def call(self, method, params):
			return {'history': {'success': True, 'done': True, 'events': []}}

	fake_sdk = FakeSdk()

	async def fake_ensure_sdk_client(self):
		return fake_sdk

	monkeypatch.setattr(Agent, '_ensure_sdk_client', fake_ensure_sdk_client)

	agent = Agent(task='task', llm=LLM(), directly_open_url=False)
	history = await agent.run(max_steps=3)

	assert history.final_result() == 'final from nested notification'
	assert history.is_successful() is True
	assert [event['event_type'] for event in agent.last_events] == ['session.input', 'session.done']


async def test_beta_agent_recovers_projected_sdk_final_events(monkeypatch):
	from browser_use.beta import Agent

	class LLM:
		model = 'fake'

	class FakeSdk:
		stderr_lines = []

		def __init__(self):
			self.notifications = [
				{
					'method': 'agent.projected_event',
					'params': {
						'event': {
							'kind': 'observed',
							'payload': {
								'event_type': 'session.input',
								'payload': {'text': 'task'},
							},
						}
					},
				},
				{
					'method': 'agent.projected_event',
					'params': {
						'event': {
							'kind': 'observed',
							'payload': {
								'event_type': 'session.done',
								'payload': {'result': 'final from projected notification', 'success': True},
							},
						}
					},
				},
			]

		async def call(self, method, params):
			return {'history': {'success': True, 'done': True, 'events': []}}

	fake_sdk = FakeSdk()

	async def fake_ensure_sdk_client(self):
		return fake_sdk

	monkeypatch.setattr(Agent, '_ensure_sdk_client', fake_ensure_sdk_client)

	agent = Agent(task='task', llm=LLM(), directly_open_url=False)
	history = await agent.run(max_steps=3)

	assert history.final_result() == 'final from projected notification'
	assert history.is_successful() is True
	assert [event['event_type'] for event in agent.last_events] == ['session.input', 'session.done']


async def test_beta_agent_prefers_notification_final_when_response_history_lacks_result(monkeypatch):
	from browser_use.beta import Agent

	class LLM:
		model = 'fake'

	def notification(seq: int, event_type: str, payload: dict):
		return {
			'method': 'agent.event',
			'params': {
				'event': {
					'seq': seq,
					'id': f'event-{seq}',
					'event_type': event_type,
					'payload': payload,
				}
			},
		}

	class FakeSdk:
		stderr_lines = []

		def __init__(self):
			self.notifications = [
				notification(1, 'session.input', {'text': 'task'}),
				notification(
					2,
					'token_count',
					{
						'info': {
							'last_token_usage': {
								'input_tokens': 100,
								'cached_input_tokens': 40,
								'output_tokens': 10,
								'total_tokens': 110,
							},
							'total_token_usage': {
								'input_tokens': 100,
								'cached_input_tokens': 40,
								'output_tokens': 10,
								'total_tokens': 110,
							},
						}
					},
				),
				notification(
					3,
					'token_count',
					{
						'info': {
							'last_token_usage': {
								'input_tokens': 200,
								'cached_input_tokens': 60,
								'output_tokens': 20,
								'total_tokens': 220,
							},
							'total_token_usage': {
								'input_tokens': 300,
								'cached_input_tokens': 100,
								'output_tokens': 30,
								'total_tokens': 330,
							},
						}
					},
				),
				notification(4, 'session.done', {'result': 'final from retained notifications', 'success': True}),
			]

		async def call(self, method, params):
			return {
				'history': {
					'success': False,
					'done': True,
					'errors': ['compacted response did not include final tail'],
					'events': [
						{'event_type': 'session.input', 'payload': {'text': 'task'}},
						{'event_type': 'browser.navigated', 'payload': {'url': 'https://example.com'}},
						{'event_type': 'sdk.transport.truncated', 'payload': {'omitted_events': 100}},
						{'event_type': 'browser.released', 'payload': {}},
						{'event_type': 'agent.turn.completed', 'payload': {}},
					],
					'usage_events': [],
				}
			}

	fake_sdk = FakeSdk()

	async def fake_ensure_sdk_client(self):
		return fake_sdk

	monkeypatch.setattr(Agent, '_ensure_sdk_client', fake_ensure_sdk_client)

	agent = Agent(task='task', llm=LLM(), directly_open_url=False)
	history = await agent.run(max_steps=3)

	assert history.final_result() == 'final from retained notifications'
	assert history.is_successful() is True
	assert history.usage is not None
	assert history.usage.total_prompt_tokens == 300
	assert history.usage.total_prompt_cached_tokens == 100
	assert history.usage.total_completion_tokens == 30
	assert history.usage.total_tokens == 330
	assert history.usage.entry_count == 2
	assert [event['event_type'] for event in agent.last_events] == [
		'session.input',
		'token_count',
		'token_count',
		'session.done',
	]


async def test_beta_agent_uses_sdk_history_usage_when_events_do_not_include_usage(monkeypatch):
	from browser_use.beta import Agent

	class LLM:
		model = 'fake'

	class FakeSdk:
		stderr_lines = []
		notifications = []

		async def call(self, method, params):
			return {
				'history': {
					'success': True,
					'done': True,
					'errors': [],
					'events': [{'event_type': 'session.done', 'payload': {'result': 'answer', 'success': True}}],
					'usage_events': [],
					'usage': {
						'input_tokens': 120,
						'cached_input_tokens': 30,
						'input_cache_creation_tokens': 10,
						'output_tokens': 15,
						'total_tokens': 145,
					},
				}
			}

	fake_sdk = FakeSdk()

	async def fake_ensure_sdk_client(self):
		return fake_sdk

	monkeypatch.setattr(Agent, '_ensure_sdk_client', fake_ensure_sdk_client)

	agent = Agent(task='task', llm=LLM(), directly_open_url=False)
	history = await agent.run(max_steps=3)

	assert history.final_result() == 'answer'
	assert history.usage is not None
	assert history.usage.total_prompt_tokens == 120
	assert history.usage.total_prompt_cached_tokens == 30
	assert history.usage.total_prompt_cache_creation_tokens == 10
	assert history.usage.total_completion_tokens == 15
	assert history.usage.total_tokens == 145


async def test_beta_agent_preserves_sdk_notification_history_on_cancel(monkeypatch):
	from browser_use.beta import Agent

	class LLM:
		model = 'fake'

	class FakeSdk:
		stderr_lines = []

		def __init__(self):
			self.notifications = [
				{
					'method': 'agent.event',
					'params': {'event': {'seq': 1, 'id': 'event-1', 'event_type': 'session.input', 'payload': {'text': 'task'}}},
				},
				{
					'method': 'agent.event',
					'params': {
						'event': {
							'seq': 2,
							'id': 'event-2',
							'event_type': 'tool.output',
							'payload': {'name': 'browser_script', 'output': 'partial evidence'},
						}
					},
				},
			]

		async def call(self, method, params):
			raise asyncio.CancelledError

	fake_sdk = FakeSdk()

	async def fake_ensure_sdk_client(self):
		return fake_sdk

	monkeypatch.setattr(Agent, '_ensure_sdk_client', fake_ensure_sdk_client)

	agent = Agent(task='task', llm=LLM(), directly_open_url=False)
	with pytest.raises(asyncio.CancelledError):
		await agent.run(max_steps=3)

	assert [event['event_type'] for event in agent.last_events] == ['session.input', 'tool.output']
	assert any('CancelledError' in error for error in agent.history.errors())


async def test_rust_sdk_client_reads_large_json_rpc_lines(monkeypatch):
	import browser_use.beta.service as beta_service

	monkeypatch.setenv('BROWSER_USE_SDK_STREAM_LIMIT_BYTES', '4096')
	monkeypatch.setenv('BROWSER_USE_SDK_READ_CHUNK_BYTES', '1024')
	script = """
import json
import sys

sys.stdin.readline()
print(json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"text": "x" * 70000}}), flush=True)
"""
	client = beta_service.RustSdkClient([sys.executable, '-c', script], {'PYTHONUNBUFFERED': '1'})

	try:
		result = await client.call('large.response')
	finally:
		await client.close()

	assert result == {'text': 'x' * 70000}


async def test_rust_sdk_client_queues_agent_notifications_before_response():
	import browser_use.beta.service as beta_service

	script = r"""
import json
import sys

sys.stdin.readline()
print(json.dumps({
	"jsonrpc": "2.0",
	"method": "agent.event",
	"params": {
		"run_id": "run-1",
		"session_id": "session-1",
		"event": {"kind": "AgentStarted", "payload": {"task": "inspect"}}
	},
}), flush=True)
print(json.dumps({
	"jsonrpc": "2.0",
	"method": "agent.projected_event",
	"params": {
		"run_id": "run-1",
		"session_id": "session-1",
		"event": {"kind": "item_started", "payload": {"name": "browser_script"}}
	},
}), flush=True)
print(json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}), flush=True)
"""
	client = beta_service.RustSdkClient([sys.executable, '-c', script], {'PYTHONUNBUFFERED': '1'})

	try:
		result = await client.call('run.with.notifications')
		first_notification = await client.notification_queue.get()
		second_notification = await client.notification_queue.get()
	finally:
		await client.close()

	assert result == {'ok': True}
	assert [item['method'] for item in client.notifications] == ['agent.event', 'agent.projected_event']
	assert first_notification['params']['event']['kind'] == 'AgentStarted'
	assert second_notification['params']['event']['kind'] == 'item_started'
	assert beta_service._sdk_notification_summary(first_notification) == 'AgentStarted task=inspect'
	assert beta_service._sdk_notification_summary(second_notification) == 'projected.item_started name=browser_script'


async def test_beta_agent_rejects_incompatible_sdk_protocol(monkeypatch):
	import browser_use.beta.service as beta_service
	from browser_use.beta import Agent

	class LLM:
		model = 'gpt-test'

	script = r"""
import json
import sys

request = json.loads(sys.stdin.readline())
print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": {"ok": True}}), flush=True)
"""
	agent = Agent(task='answer', llm=LLM())
	monkeypatch.setattr(agent, '_sdk_server_argv', lambda: [sys.executable, '-c', script])

	with pytest.raises(beta_service.BetaAgentError) as exc_info:
		await agent._ensure_sdk_client()

	assert 'Unsupported browser-use-terminal SDK protocol' in str(exc_info.value)


async def test_beta_agent_clears_sdk_client_when_protocol_ping_fails(monkeypatch):
	import browser_use.beta.service as beta_service
	from browser_use.beta import Agent

	class LLM:
		model = 'gpt-test'

	script = r"""
import json
import sys

request = json.loads(sys.stdin.readline())
print(json.dumps({
	"jsonrpc": "2.0",
	"id": request["id"],
	"error": {"code": -32000, "message": "ping failed"},
}), flush=True)
"""
	agent = Agent(task='answer', llm=LLM())
	monkeypatch.setattr(agent, '_sdk_server_argv', lambda: [sys.executable, '-c', script])

	with pytest.raises(beta_service.BetaAgentError) as exc_info:
		await agent._ensure_sdk_client()

	assert 'Failed to negotiate browser-use-terminal SDK protocol via runtime.ping' in str(exc_info.value)
	assert agent._sdk_client is None


def test_beta_agent_bridges_llm_credentials_to_terminal_env(monkeypatch):
	from browser_use.beta import Agent

	class LLM:
		def __init__(self, provider, model, api_key=None, base_url=None):
			self.provider = provider
			self.model = model
			self.api_key = api_key
			self.base_url = base_url

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')
	for key in (
		'LLM_BROWSER_OPENAI_BASE_URL',
		'LLM_BROWSER_ANTHROPIC_BASE_URL',
		'LLM_BROWSER_OPENAI_COMPAT_API_KEY',
		'LLM_BROWSER_OPENAI_COMPAT_BASE_URL',
		'OPENROUTER_API_KEY',
		'OPENROUTER_BASE_URL',
		'DEEPSEEK_API_KEY',
		'LLM_BROWSER_BROWSER_USE_API_KEY',
		'LLM_BROWSER_BROWSER_USE_BASE_URL',
	):
		monkeypatch.delenv(key, raising=False)
	monkeypatch.setenv('LLM_BROWSER_OPENAI_API_KEY', 'ambient-openai-key')
	monkeypatch.setenv('LLM_BROWSER_ANTHROPIC_API_KEY', 'ambient-anthropic-key')

	openai_env = Agent(
		task='OpenAI credentials.',
		llm=LLM('openai', 'gpt-test', api_key='llm-openai-key', base_url='https://openai.example/v1'),
	)._run_env()
	openai_agent = Agent(
		task='OpenAI command.',
		llm=LLM('openai', 'gpt-test', api_key='llm-openai-key'),
	)
	anthropic_agent = Agent(
		task='Anthropic credentials.',
		llm=LLM('anthropic', 'claude-test', api_key='llm-anthropic-key', base_url='https://anthropic.example'),
	)
	openrouter_agent = Agent(
		task='OpenRouter credentials.',
		llm=LLM('openrouter', 'openrouter/model', api_key='llm-openrouter-key', base_url='https://openrouter.example/api/v1'),
	)
	deepseek_agent = Agent(
		task='DeepSeek credentials.',
		llm=LLM('deepseek', 'deepseek-chat', api_key='llm-deepseek-key', base_url='https://ignored.example'),
	)
	browser_use_agent = Agent(
		task='Browser Use credentials.',
		llm=LLM('browser-use', 'bu-2-0', api_key='llm-browser-use-key', base_url='https://llm.example/v1'),
	)
	ambient_env = Agent(
		task='Ambient credentials.',
		llm=LLM('anthropic', 'claude-test'),
	)._run_env()
	anthropic_env = anthropic_agent._run_env()
	openrouter_env = openrouter_agent._run_env()
	deepseek_env = deepseek_agent._run_env()
	browser_use_env = browser_use_agent._run_env()

	assert openai_env['LLM_BROWSER_OPENAI_API_KEY'] == 'llm-openai-key'
	assert openai_env['LLM_BROWSER_OPENAI_BASE_URL'] == 'https://openai.example/v1'
	assert anthropic_env['LLM_BROWSER_ANTHROPIC_API_KEY'] == 'llm-anthropic-key'
	assert anthropic_env['LLM_BROWSER_ANTHROPIC_BASE_URL'] == 'https://anthropic.example'
	assert openrouter_env['OPENROUTER_API_KEY'] == 'llm-openrouter-key'
	assert openrouter_env['OPENROUTER_BASE_URL'] == 'https://openrouter.example/api/v1'
	assert deepseek_env['DEEPSEEK_API_KEY'] == 'llm-deepseek-key'
	assert 'LLM_BROWSER_OPENAI_COMPAT_BASE_URL' not in deepseek_env
	assert browser_use_env['LLM_BROWSER_BROWSER_USE_API_KEY'] == 'llm-browser-use-key'
	assert browser_use_env['LLM_BROWSER_BROWSER_USE_BASE_URL'] == 'https://llm.example'
	assert ambient_env['LLM_BROWSER_ANTHROPIC_API_KEY'] == 'ambient-anthropic-key'

	assert openai_agent._sdk_run_params(max_steps=3, task=openai_agent.task)['llm'] | {'timeout': None} == {
		'provider': 'openai',
		'model': 'gpt-test',
		'timeout': None,
	}
	assert anthropic_agent._sdk_run_params(max_steps=3, task=anthropic_agent.task)['llm'] | {'timeout': None} == {
		'provider': 'anthropic',
		'model': 'claude-test',
		'timeout': None,
	}
	assert openrouter_agent._sdk_run_params(max_steps=3, task=openrouter_agent.task)['llm'] | {'timeout': None} == {
		'provider': 'openrouter',
		'model': 'openrouter/model',
		'timeout': None,
	}
	assert deepseek_agent._sdk_run_params(max_steps=3, task=deepseek_agent.task)['llm'] | {'timeout': None} == {
		'provider': 'deepseek',
		'model': 'deepseek-chat',
		'timeout': None,
	}
	assert browser_use_agent._sdk_run_params(max_steps=3, task=browser_use_agent.task)['llm'] | {'timeout': None} == {
		'provider': 'browser-use',
		'model': 'bu-2-0',
		'timeout': None,
	}


def test_beta_agent_requests_openai_compatible_usage_for_cost_calculation(monkeypatch):
	from browser_use.beta import Agent

	class LLM:
		def __init__(self, provider, model):
			self.provider = provider
			self.model = model
			self.api_key = 'test-key'

	monkeypatch.delenv('LLM_BROWSER_OPENAI_COMPAT_INCLUDE_USAGE', raising=False)
	monkeypatch.delenv('BU_USE_CALCULATE_COST', raising=False)

	openrouter_env = Agent(
		task='Track OpenRouter usage.',
		llm=LLM('openrouter', 'openrouter/model'),
		calculate_cost=True,
	)._run_env()
	deepseek_env = Agent(
		task='Track DeepSeek usage.',
		llm=LLM('deepseek', 'deepseek-chat'),
		calculate_cost=True,
	)._run_env()
	default_env = Agent(
		task='Default OpenRouter usage.',
		llm=LLM('openrouter', 'openrouter/model'),
	)._run_env()
	openai_env = Agent(
		task='OpenAI usage.',
		llm=LLM('openai', 'gpt-test'),
		calculate_cost=True,
	)._run_env()

	assert openrouter_env['BU_USE_CALCULATE_COST'] == 'true'
	assert openrouter_env['LLM_BROWSER_OPENAI_COMPAT_INCLUDE_USAGE'] == 'true'
	assert deepseek_env['BU_USE_CALCULATE_COST'] == 'true'
	assert deepseek_env['LLM_BROWSER_OPENAI_COMPAT_INCLUDE_USAGE'] == 'true'
	assert 'LLM_BROWSER_OPENAI_COMPAT_INCLUDE_USAGE' not in default_env
	assert 'LLM_BROWSER_OPENAI_COMPAT_INCLUDE_USAGE' not in openai_env


def test_beta_agent_translates_browser_profile_cdp_url(monkeypatch):
	from browser_use.beta import Agent

	class BrowserProfile:
		cdp_url = 'http://127.0.0.1:9222'

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')
	agent = Agent(task='report title', llm=type('LLM', (), {'model': 'gpt-test'})(), browser_profile=BrowserProfile())
	env = agent._run_env()

	assert agent._sdk_run_params(max_steps=4, task=agent.task)['browser_mode'] == 'remote-cdp'
	assert env['BU_CDP_URL'] == 'http://127.0.0.1:9222'
	assert env['LLM_BROWSER_BROWSER_MODE'] == 'remote-cdp'


def test_beta_agent_translates_browser_profile_cdp_headers(monkeypatch):
	from browser_use.beta import Agent

	class BrowserProfile:
		cdp_url = 'http://127.0.0.1:9222'
		headers = {'Authorization': 'Bearer test-token', 'X-Browser-Use': 'rust', 'Retries': 3}

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')

	agent = Agent(task='report title', browser_profile=BrowserProfile())
	env = agent._run_env()

	assert env['LLM_BROWSER_BROWSER_MODE'] == 'remote-cdp'
	assert agent.cdp_headers == {
		'Authorization': 'Bearer test-token',
		'X-Browser-Use': 'rust',
		'Retries': '3',
	}
	assert json.loads(env['BU_CDP_HEADERS']) == agent.cdp_headers


def test_beta_agent_translates_browser_profile_remote_user_agent(monkeypatch):
	from browser_use.beta import Agent

	class BrowserProfile:
		cdp_url = 'http://127.0.0.1:9222'
		user_agent = 'BrowserUseRemote/2.0'

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')

	agent = Agent(task='report title', browser_profile=BrowserProfile())
	env = agent._run_env()

	assert env['LLM_BROWSER_BROWSER_MODE'] == 'remote-cdp'
	assert agent.browser_user_agent == 'BrowserUseRemote/2.0'
	assert env['BU_BROWSER_USER_AGENT'] == 'BrowserUseRemote/2.0'


def test_beta_agent_translates_browser_profile_highlights(monkeypatch):
	from browser_use.beta import Agent

	class BrowserProfile:
		highlight_elements = True
		dom_highlight_elements = False
		interaction_highlight_color = 'rgb(255, 127, 39)'
		interaction_highlight_duration = 1.75
		cdp_url = 'http://127.0.0.1:9222'

	class DomHighlightProfile:
		highlight_elements = True
		dom_highlight_elements = True
		cdp_url = 'http://127.0.0.1:9222'

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')

	agent = Agent(task='report title', browser_profile=BrowserProfile())
	env = agent._run_env()

	assert env['BROWSER_USE_TERMINAL_AUTO_HIGHLIGHT'] == 'true'
	assert env['BROWSER_USE_TERMINAL_HIGHLIGHT_COLOR'] == 'rgb(255, 127, 39)'
	assert env['BROWSER_USE_TERMINAL_HIGHLIGHT_DURATION_MS'] == '1750'

	dom_agent = Agent(task='report title', browser_profile=DomHighlightProfile())
	dom_env = dom_agent._run_env()

	assert dom_agent.highlight_enabled is False
	assert dom_env['BROWSER_USE_TERMINAL_AUTO_HIGHLIGHT'] == 'false'


def test_beta_agent_translates_browser_profile_wait_timings(monkeypatch):
	from browser_use.beta import Agent

	class BrowserProfile:
		minimum_wait_page_load_time = 0.25
		wait_for_network_idle_page_load_time = 0.75
		wait_between_actions = 0.125
		cdp_url = 'http://127.0.0.1:9222'

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')

	agent = Agent(task='report title', browser_profile=BrowserProfile())
	env = agent._run_env()

	assert agent.wait_timing_env == {
		'BU_BROWSER_MINIMUM_WAIT_PAGE_LOAD_MS': '250',
		'BU_BROWSER_NETWORK_IDLE_PAGE_LOAD_MS': '750',
		'BU_BROWSER_WAIT_BETWEEN_ACTIONS_MS': '125',
	}
	assert env['BU_BROWSER_MINIMUM_WAIT_PAGE_LOAD_MS'] == '250'
	assert env['BU_BROWSER_NETWORK_IDLE_PAGE_LOAD_MS'] == '750'
	assert env['BU_BROWSER_WAIT_BETWEEN_ACTIONS_MS'] == '125'


def test_beta_agent_translates_browser_profile_block_ip_addresses(monkeypatch):
	from browser_use.beta import Agent

	class BrowserProfile:
		block_ip_addresses = True
		cdp_url = 'http://127.0.0.1:9222'

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')

	agent = Agent(task='report title', browser_profile=BrowserProfile())
	env = agent._run_env()

	assert agent.block_ip_addresses is True
	assert env['BU_BROWSER_BLOCK_IP_ADDRESSES'] == 'true'


def test_beta_agent_translates_browser_profile_headless(monkeypatch):
	from browser_use.beta import Agent

	class HeadedProfile:
		headless = False

	class HeadlessProfile:
		headless = True

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')
	monkeypatch.delenv('BROWSER_USE_RUST_BROWSER_MODE', raising=False)
	monkeypatch.delenv('BROWSER_USE_BROWSER_MODE', raising=False)

	headed = Agent(task='report title', llm=type('LLM', (), {'model': 'gpt-test'})(), browser_profile=HeadedProfile())
	headless = Agent(task='report title', llm=type('LLM', (), {'model': 'gpt-test'})(), browser_profile=HeadlessProfile())

	assert headed._sdk_run_params(max_steps=4, task=headed.task)['browser_mode'] == 'managed-headed'
	assert headed._run_env()['LLM_BROWSER_BROWSER_MODE'] == 'managed-headed'
	assert headless._sdk_run_params(max_steps=4, task=headless.task)['browser_mode'] == 'managed-headless'
	assert headless._run_env()['LLM_BROWSER_BROWSER_MODE'] == 'managed-headless'


def test_beta_agent_browser_mode_env_overrides_profile_headless(monkeypatch):
	from browser_use.beta import Agent

	class HeadedProfile:
		headless = False

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')
	monkeypatch.setenv('BROWSER_USE_BROWSER_MODE', 'cloud')

	agent = Agent(task='report title', llm=type('LLM', (), {'model': 'gpt-test'})(), browser_profile=HeadedProfile())

	assert agent._sdk_run_params(max_steps=4, task=agent.task)['browser_mode'] == 'cloud'
	assert agent._run_env()['LLM_BROWSER_BROWSER_MODE'] == 'cloud'


def test_beta_agent_translates_browser_profile_cloud(monkeypatch):
	from browser_use.beta import Agent

	class CloudProfile:
		use_cloud = True
		headless = False

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')
	monkeypatch.delenv('BROWSER_USE_RUST_BROWSER_MODE', raising=False)
	monkeypatch.delenv('BROWSER_USE_BROWSER_MODE', raising=False)

	agent = Agent(task='report title', llm=type('LLM', (), {'model': 'gpt-test'})(), browser_profile=CloudProfile())

	assert agent._sdk_run_params(max_steps=4, task=agent.task)['browser_mode'] == 'cloud'
	assert agent._run_env()['LLM_BROWSER_BROWSER_MODE'] == 'cloud'


def test_beta_agent_translates_browser_profile_managed_launch_args(monkeypatch):
	from browser_use.beta import Agent

	class Proxy:
		server = 'http://proxy.example:8080'
		bypass = 'localhost,127.0.0.1'

	class BrowserProfile:
		headless = True
		args = ['--lang=en-US']
		disable_security = True
		proxy = Proxy()
		window_size = {'width': 1440, 'height': 900}
		user_agent = 'BrowserUseTest/1.0'

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')
	monkeypatch.delenv('BROWSER_USE_RUST_BROWSER_MODE', raising=False)
	monkeypatch.delenv('BROWSER_USE_BROWSER_MODE', raising=False)

	agent = Agent(task='report title', browser_profile=BrowserProfile())
	env = agent._run_env()
	launch_args = json.loads(env['BU_MANAGED_BROWSER_ARGS'])

	assert env['LLM_BROWSER_BROWSER_MODE'] == 'managed-headless'
	assert agent.managed_browser_args == launch_args
	assert agent.browser_user_agent == 'BrowserUseTest/1.0'
	assert env['BU_BROWSER_USER_AGENT'] == 'BrowserUseTest/1.0'
	assert '--lang=en-US' in launch_args
	assert '--window-size=1440,900' in launch_args
	assert '--proxy-server=http://proxy.example:8080' in launch_args
	assert '--proxy-bypass-list=localhost,127.0.0.1' in launch_args
	assert '--disable-web-security' in launch_args
	assert '--user-agent=BrowserUseTest/1.0' in launch_args


def test_beta_agent_translates_browser_profile_chromium_sandbox(monkeypatch):
	from browser_use.beta import Agent

	class BrowserProfile:
		headless = True
		chromium_sandbox = False
		args = ['--no-sandbox']

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')
	monkeypatch.delenv('BROWSER_USE_RUST_BROWSER_MODE', raising=False)
	monkeypatch.delenv('BROWSER_USE_BROWSER_MODE', raising=False)

	agent = Agent(task='report title', browser_profile=BrowserProfile())
	launch_args = json.loads(agent._run_env()['BU_MANAGED_BROWSER_ARGS'])

	assert launch_args.count('--no-sandbox') == 1
	assert '--disable-gpu-sandbox' in launch_args
	assert '--disable-setuid-sandbox' in launch_args
	assert '--disable-dev-shm-usage' in launch_args


def test_beta_agent_translates_browser_profile_window_position(monkeypatch):
	from browser_use.beta import Agent

	class BrowserProfile:
		headless = False
		window_position = {'width': 32, 'height': 64}

	class TuplePositionProfile:
		headless = False
		window_position = (12, 24)

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')
	monkeypatch.delenv('BROWSER_USE_RUST_BROWSER_MODE', raising=False)
	monkeypatch.delenv('BROWSER_USE_BROWSER_MODE', raising=False)

	agent = Agent(task='report title', browser_profile=BrowserProfile())
	tuple_agent = Agent(task='report title', browser_profile=TuplePositionProfile())

	assert '--window-position=32,64' in json.loads(agent._run_env()['BU_MANAGED_BROWSER_ARGS'])
	assert '--window-position=12,24' in json.loads(tuple_agent._run_env()['BU_MANAGED_BROWSER_ARGS'])


def test_beta_agent_translates_browser_profile_devtools(monkeypatch):
	from browser_use.beta import Agent

	class BrowserProfile:
		headless = False
		devtools = True

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')
	monkeypatch.delenv('BROWSER_USE_RUST_BROWSER_MODE', raising=False)
	monkeypatch.delenv('BROWSER_USE_BROWSER_MODE', raising=False)

	agent = Agent(task='report title', browser_profile=BrowserProfile())
	env = agent._run_env()
	launch_args = json.loads(env['BU_MANAGED_BROWSER_ARGS'])

	assert env['LLM_BROWSER_BROWSER_MODE'] == 'managed-headed'
	assert '--auto-open-devtools-for-tabs' in launch_args


def test_beta_agent_translates_browser_profile_profile_directory(monkeypatch):
	from browser_use.beta import Agent

	class BrowserProfile:
		headless = False
		profile_directory = 'Profile 7'

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')
	monkeypatch.delenv('BROWSER_USE_RUST_BROWSER_MODE', raising=False)
	monkeypatch.delenv('BROWSER_USE_BROWSER_MODE', raising=False)

	agent = Agent(task='report title', browser_profile=BrowserProfile())
	launch_args = json.loads(agent._run_env()['BU_MANAGED_BROWSER_ARGS'])

	assert '--profile-directory=Profile 7' in launch_args


def test_beta_agent_translates_browser_profile_permissions(monkeypatch):
	from browser_use.beta import Agent

	class BrowserProfile:
		permissions = ['clipboardReadWrite', 'notifications', 'clipboardReadWrite']
		cdp_url = 'http://127.0.0.1:9222'

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')

	agent = Agent(task='report title', browser_profile=BrowserProfile())
	env = agent._run_env()

	assert env['LLM_BROWSER_BROWSER_MODE'] == 'remote-cdp'
	assert agent.browser_permissions == ['clipboardReadWrite', 'notifications']
	assert json.loads(env['BU_BROWSER_PERMISSIONS']) == ['clipboardReadWrite', 'notifications']


def test_beta_agent_translates_browser_profile_downloads(monkeypatch, tmp_path):
	from browser_use.beta import Agent

	profile_downloads_path = tmp_path / 'downloads'

	class BrowserProfile:
		accept_downloads = True
		downloads_path = profile_downloads_path
		cdp_url = 'http://127.0.0.1:9222'

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')

	agent = Agent(task='report title', browser_profile=BrowserProfile())
	env = agent._run_env()

	assert env['LLM_BROWSER_BROWSER_MODE'] == 'remote-cdp'
	assert agent.browser_accept_downloads is True
	assert agent.browser_downloads_path == str(profile_downloads_path)
	assert env['BU_BROWSER_ACCEPT_DOWNLOADS'] == 'true'
	assert env['BU_BROWSER_DOWNLOADS_PATH'] == str(profile_downloads_path)


def test_beta_agent_translates_browser_profile_viewport(monkeypatch):
	from browser_use.beta import Agent

	class BrowserProfile:
		viewport = {'width': 1024, 'height': 768}
		screen = (1440, 900)
		device_scale_factor = 2
		no_viewport = False
		cdp_url = 'http://127.0.0.1:9222'

	class NoViewportProfile:
		viewport = {'width': 1024, 'height': 768}
		no_viewport = True
		cdp_url = 'http://127.0.0.1:9222'

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')

	agent = Agent(task='report title', browser_profile=BrowserProfile())
	env = agent._run_env()
	viewport = json.loads(env['BU_BROWSER_VIEWPORT'])

	assert env['LLM_BROWSER_BROWSER_MODE'] == 'remote-cdp'
	assert env['BU_BROWSER_NO_VIEWPORT'] == 'false'
	assert viewport == {
		'width': 1024,
		'height': 768,
		'deviceScaleFactor': 2,
		'screenWidth': 1440,
		'screenHeight': 900,
	}

	no_viewport_agent = Agent(task='report title', browser_profile=NoViewportProfile())
	no_viewport_env = no_viewport_agent._run_env()

	assert no_viewport_env['BU_BROWSER_NO_VIEWPORT'] == 'true'
	assert 'BU_BROWSER_VIEWPORT' not in no_viewport_env


def test_beta_agent_translates_browser_profile_storage_state(monkeypatch, tmp_path):
	from browser_use.beta import Agent

	profile_storage_state_path = tmp_path / 'storage_state.json'
	storage_state = {
		'cookies': [
			{
				'name': 'sid',
				'value': 'secret',
				'domain': '.example.com',
				'path': '/',
			}
		],
		'origins': [
			{
				'origin': 'https://example.com',
				'localStorage': [{'name': 'theme', 'value': 'dark'}],
			}
		],
	}
	profile_storage_state_path.write_text(json.dumps(storage_state))

	class BrowserProfile:
		storage_state = profile_storage_state_path
		cdp_url = 'http://127.0.0.1:9222'

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')

	agent = Agent(task='report title', browser_profile=BrowserProfile())
	env = agent._run_env()

	assert env['LLM_BROWSER_BROWSER_MODE'] == 'remote-cdp'
	assert agent.browser_storage_state == storage_state
	assert json.loads(env['BU_BROWSER_STORAGE_STATE']) == storage_state


def test_beta_agent_translates_browser_profile_user_data_dir(monkeypatch, tmp_path):
	from browser_use.beta import Agent

	profile_dir = tmp_path / 'browser profile'

	class BrowserProfile:
		headless = False
		user_data_dir = profile_dir

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')
	monkeypatch.delenv('BROWSER_USE_RUST_BROWSER_MODE', raising=False)
	monkeypatch.delenv('BROWSER_USE_BROWSER_MODE', raising=False)
	monkeypatch.delenv('BU_MANAGED_BROWSER_PROFILE', raising=False)

	agent = Agent(task='report title', browser_profile=BrowserProfile())
	env = agent._run_env()

	assert env['LLM_BROWSER_BROWSER_MODE'] == 'managed-headed'
	assert agent.managed_browser_profile_dir == str(profile_dir)
	assert env['BU_MANAGED_BROWSER_PROFILE'] == str(profile_dir)


def test_beta_agent_translates_browser_profile_executable_path(monkeypatch, tmp_path):
	from browser_use.beta import Agent

	chrome_path = tmp_path / 'custom chrome'

	class BrowserProfile:
		headless = True
		executable_path = chrome_path

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')
	monkeypatch.setenv('CHROME_PATH', '/usr/bin/existing-chrome')
	monkeypatch.delenv('BROWSER_USE_RUST_BROWSER_MODE', raising=False)
	monkeypatch.delenv('BROWSER_USE_BROWSER_MODE', raising=False)

	agent = Agent(task='report title', browser_profile=BrowserProfile())
	env = agent._run_env()

	assert env['LLM_BROWSER_BROWSER_MODE'] == 'managed-headless'
	assert agent.managed_browser_executable_path == str(chrome_path)
	assert env['CHROME_PATH'] == str(chrome_path)

	monkeypatch.setenv('BROWSER_USE_BROWSER_MODE', 'cloud')
	cloud_agent = Agent(task='report title', browser_profile=BrowserProfile())
	cloud_env = cloud_agent._run_env()

	assert cloud_env['LLM_BROWSER_BROWSER_MODE'] == 'cloud'
	assert cloud_env['CHROME_PATH'] == '/usr/bin/existing-chrome'


def test_beta_agent_translates_browser_profile_env(monkeypatch):
	from browser_use.beta import Agent

	class BrowserProfile:
		headless = True
		env = {
			'BU_BROWSER_FLAG': 'enabled',
			'BU_BROWSER_BOOL': True,
			'BU_BROWSER_RETRIES': 3,
			'IGNORED_NESTED': {'nested': 'value'},
		}

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')
	monkeypatch.setenv('BU_BROWSER_FLAG', 'outer')
	monkeypatch.delenv('BROWSER_USE_RUST_BROWSER_MODE', raising=False)
	monkeypatch.delenv('BROWSER_USE_BROWSER_MODE', raising=False)

	agent = Agent(task='report title', browser_profile=BrowserProfile())
	env = agent._run_env()

	assert env['LLM_BROWSER_BROWSER_MODE'] == 'managed-headless'
	assert agent.managed_browser_env == {
		'BU_BROWSER_FLAG': 'enabled',
		'BU_BROWSER_BOOL': 'true',
		'BU_BROWSER_RETRIES': '3',
	}
	assert env['BU_BROWSER_FLAG'] == 'enabled'
	assert env['BU_BROWSER_BOOL'] == 'true'
	assert env['BU_BROWSER_RETRIES'] == '3'
	assert 'IGNORED_NESTED' not in env

	monkeypatch.setenv('BROWSER_USE_BROWSER_MODE', 'cloud')
	cloud_agent = Agent(task='report title', browser_profile=BrowserProfile())
	cloud_env = cloud_agent._run_env()

	assert cloud_env['LLM_BROWSER_BROWSER_MODE'] == 'cloud'
	assert cloud_env['BU_BROWSER_FLAG'] == 'outer'
	assert 'BU_BROWSER_BOOL' not in cloud_env


def test_beta_agent_adds_browser_profile_domain_constraints():
	from browser_use.beta import Agent

	class BrowserProfile:
		allowed_domains = ['example.com', '*.browser-use.com']
		prohibited_domains = {'ads.example.com'}

	agent = Agent(task='Open the allowed site.', browser_profile=BrowserProfile())
	env = agent._run_env()

	assert agent.allowed_domains == ['example.com', '*.browser-use.com']
	assert agent.prohibited_domains == ['ads.example.com']
	assert json.loads(env['BU_BROWSER_ALLOWED_DOMAINS']) == ['example.com', '*.browser-use.com']
	assert json.loads(env['BU_BROWSER_PROHIBITED_DOMAINS']) == ['ads.example.com']
	assert 'Browser profile navigation constraints:' in agent.task
	assert 'Allowed domains:' in agent.task
	assert '- example.com' in agent.task
	assert '- *.browser-use.com' in agent.task
	assert 'Prohibited domains:' in agent.task
	assert '- ads.example.com' in agent.task


def test_beta_agent_adds_sensitive_data_placeholders_without_values():
	from browser_use.beta import Agent

	agent = Agent(
		task='Log in to the portal.',
		sensitive_data={
			'username': 'alice@example.com',
			'https://example.com': {'password': 'super-secret-password'},
		},
	)

	assert agent.sensitive_data_context == {
		'global_placeholders': ['username'],
		'domain_placeholders': {'https://example.com': ['password']},
	}
	assert 'Sensitive data placeholders are available.' in agent.task
	assert '- username' in agent.task
	assert '- https://example.com: password' in agent.task
	assert '<secret>placeholder</secret>' in agent.task
	assert 'alice@example.com' not in agent.task
	assert 'super-secret-password' not in agent.task


def test_beta_agent_warns_about_sensitive_data_domain_constraints(monkeypatch):
	from browser_use.beta import Agent

	class RecordingLogger:
		def __init__(self):
			self.messages = []

		def error(self, message, *args, **kwargs):
			self.messages.append(('error', message))

		def warning(self, message, *args, **kwargs):
			self.messages.append(('warning', message))

	logger = RecordingLogger()
	monkeypatch.setattr(Agent, 'logger', property(lambda self: logger))

	Agent(
		task='Use credentials safely.',
		sensitive_data={'password': 'super-secret-password'},
		directly_open_url=False,
	)

	messages = '\n'.join(message for _level, message in logger.messages)
	assert 'not locked down' in messages
	assert 'super-secret-password' not in messages

	logger.messages.clear()

	class BrowserProfile:
		allowed_domains = ['*.example.com']

	Agent(
		task='Use domain-scoped credentials safely.',
		browser_profile=BrowserProfile(),
		sensitive_data={
			'https://secure.example.com': {'password': 'covered-secret'},
			'https://evil.test': {'token': 'uncovered-secret'},
		},
		directly_open_url=False,
	)

	messages = '\n'.join(message for _level, message in logger.messages)
	assert 'Domain pattern "https://evil.test" in sensitive_data is not covered' in messages
	assert 'https://secure.example.com' not in messages
	assert 'covered-secret' not in messages
	assert 'uncovered-secret' not in messages


def test_beta_agent_sensitive_data_warnings_match_browser_use(monkeypatch):
	from browser_use.agent.service import _PythonAgent as BrowserUseAgent
	from browser_use.beta import Agent as BetaAgent
	from browser_use.browser import BrowserProfile

	class LLM:
		model = 'gpt-test'
		provider = 'test'

		async def ainvoke(self, messages, output_format=None, **kwargs):
			return type('Result', (), {'usage': None})()

	class RecordingLogger:
		def __init__(self):
			self.messages = []

		def info(self, message, *args, **kwargs):
			pass

		def debug(self, message, *args, **kwargs):
			pass

		def error(self, message, *args, **kwargs):
			self.messages.append(('error', message))

		def warning(self, message, *args, **kwargs):
			self.messages.append(('warning', message))

	for kwargs in (
		{
			'sensitive_data': {'password': 'unlocked-secret'},
		},
		{
			'browser_profile': BrowserProfile(allowed_domains=['*.example.com']),
			'sensitive_data': {'https://evil.test': {'password': 'uncovered-secret'}},
		},
	):
		browser_use_logger = RecordingLogger()
		beta_logger = RecordingLogger()
		monkeypatch.setattr(BrowserUseAgent, 'logger', property(lambda self, logger=browser_use_logger: logger))
		monkeypatch.setattr(BetaAgent, 'logger', property(lambda self, logger=beta_logger: logger))

		BrowserUseAgent(task='Use credentials safely.', llm=LLM(), directly_open_url=False, **kwargs)
		BetaAgent(task='Use credentials safely.', llm=LLM(), directly_open_url=False, **kwargs)

		assert beta_logger.messages == browser_use_logger.messages
		message_text = '\n'.join(message for _level, message in beta_logger.messages)
		assert 'unlocked-secret' not in message_text
		assert 'uncovered-secret' not in message_text


def test_beta_agent_mirrors_direct_url_startup():
	from browser_use.beta import Agent

	agent = Agent(task='Open example.com and report the title.')

	assert agent.initial_url == 'https://example.com'
	assert agent.initial_action_payloads == [{'navigate': {'url': 'https://example.com', 'new_tab': False}}]
	assert agent.initial_actions[0].model_dump(exclude_unset=True) == {
		'navigate': {'url': 'https://example.com', 'new_tab': False}
	}
	assert "First navigate to 'https://example.com'" in agent.task


def test_beta_agent_logs_direct_url_startup_like_browser_use(monkeypatch):
	from browser_use.agent.service import _PythonAgent as BrowserUseAgent
	from browser_use.beta import Agent as BetaAgent

	class LLM:
		model = 'gpt-test'
		provider = 'test'

		async def ainvoke(self, messages, output_format=None, **kwargs):
			return type('Result', (), {'usage': None})()

	class RecordingLogger:
		def __init__(self):
			self.infos = []

		def info(self, message, *args, **kwargs):
			self.infos.append(message)

		def debug(self, message, *args, **kwargs):
			pass

		def warning(self, message, *args, **kwargs):
			pass

		def error(self, message, *args, **kwargs):
			pass

	browser_use_logger = RecordingLogger()
	beta_logger = RecordingLogger()
	monkeypatch.setattr(BrowserUseAgent, 'logger', property(lambda self: browser_use_logger))
	monkeypatch.setattr(BetaAgent, 'logger', property(lambda self: beta_logger))

	BrowserUseAgent(task='Open example.com and report the title.', llm=LLM())
	BetaAgent(task='Open example.com and report the title.', llm=LLM())
	BrowserUseAgent(task='Use https://XXX.XX only as an example price placeholder.', llm=LLM())
	BetaAgent(task='Use https://XXX.XX only as an example price placeholder.', llm=LLM())

	expected = ['🔗 Found URL in task: https://example.com, adding as initial action...']
	assert browser_use_logger.infos == expected
	assert beta_logger.infos == expected


def test_beta_agent_exposes_task_helper_methods():
	from browser_use.agent.service import _PythonAgent as BrowserUseAgent
	from browser_use.beta import Agent

	class Answer(BaseModel):
		answer: str

	class LLM:
		model = 'gpt-test'
		provider = 'test'

		async def ainvoke(self, messages, output_format=None, **kwargs):
			return type('Result', (), {'usage': None})()

	agent = Agent(task='Open example.com and report the title.')
	browser_use_agent = BrowserUseAgent(task='Inspect URL extraction.', llm=LLM(), directly_open_url=False)

	enhanced = agent._enhance_task_with_schema('Return the answer.', Answer)

	assert agent._enhance_task_with_schema('Return the answer.', None) == 'Return the answer.'
	assert 'Expected output format: Answer' in enhanced
	assert '"answer"' in enhanced
	assert agent._extract_start_url('Open example.com and report the title.') == 'https://example.com'
	assert agent._extract_start_url('Email support@example.com only.') is None
	assert agent._extract_start_url('Open https://example.com/report.pdf and summarize it.') is None
	assert agent._extract_start_url('Use https://XXX.XX as a placeholder in the table.') is None
	assert browser_use_agent._extract_start_url('Use https://XXX.XX as a placeholder in the table.') is None
	numbered_task = '1. Navigate to https://elibrary.ferc.gov/eLibrary/search.\\n2. Ensure "General Search" is selected.'
	assert agent._extract_start_url(numbered_task) == 'https://elibrary.ferc.gov/eLibrary/search'
	assert browser_use_agent._extract_start_url(numbered_task) == 'https://elibrary.ferc.gov/eLibrary/search'


def test_beta_agent_exposes_url_text_helper_methods():
	from browser_use.beta import Agent
	from browser_use.llm.messages import ContentPartTextParam, UserMessage

	class Nested(BaseModel):
		url: str

	class Restored(BaseModel):
		text: str
		nested: Nested
		items: list
		pair: tuple[str, str]

	agent = Agent(task='Shorten URLs.', _url_shortening_limit=8)
	original_url = 'https://example.com/path?abcdefghijklmnopqrstuvwxyz#section'
	text = f'Open {original_url} now.'

	cleaned = agent._remove_think_tags('visible <think>hidden</think> answer')
	shortened_text, replacements = agent._replace_urls_in_text(text)
	shortened_url = next(iter(replacements))
	message = UserMessage(content=[ContentPartTextParam(text=text)])
	message_replacements = agent._process_messsages_and_replace_long_urls_shorter_ones([message])
	model = Restored(
		text=shortened_url,
		nested=Nested(url=shortened_url),
		items=[shortened_url, {'url': shortened_url}],
		pair=(shortened_url, 'untouched'),
	)

	Agent._recursive_process_all_strings_inside_pydantic_model(model, replacements)

	assert cleaned == 'visible  answer'
	assert original_url not in shortened_text
	assert replacements[shortened_url] == original_url
	assert Agent._replace_shortened_urls_in_string(shortened_text, replacements) == text
	assert message_replacements
	assert original_url not in message.content[0].text
	assert model.text == original_url
	assert model.nested.url == original_url
	assert model.items == [original_url, {'url': original_url}]
	assert model.pair == (original_url, 'untouched')


def test_beta_agent_preserves_ordered_initial_actions_context():
	from browser_use.beta import Agent

	agent = Agent(
		task='Report what is visible after setup.',
		initial_actions=[
			{'navigate': {'url': 'https://example.com', 'new_tab': False}},
			{'click_element_by_index': {'index': 3}},
		],
	)
	converted = [action.model_dump(exclude_unset=True) for action in agent.initial_actions]

	assert agent.initial_action_payloads == [
		{'navigate': {'url': 'https://example.com', 'new_tab': False}},
		{'click_element_by_index': {'index': 3}},
	]
	assert converted == [
		{'navigate': {'url': 'https://example.com', 'new_tab': False}},
		{'click': {'index': 3}},
	]
	assert 'Browser Use initial actions in order' in agent.task
	assert '"navigate"' in agent.task
	assert '"click_element_by_index"' in agent.task
	assert 'Then complete the task.' in agent.task


def test_beta_agent_skips_ambiguous_or_excluded_direct_urls():
	from browser_use.beta import Agent

	class LLM:
		model = 'gpt-test'
		provider = 'test-provider'

	ambiguous = Agent(task='Compare example.com and browser-use.com.', llm=cast(Any, LLM()))
	document = Agent(task='Open https://example.com/report.pdf and summarize it.', llm=cast(Any, LLM()))

	assert ambiguous.initial_url is None
	assert 'First navigate to' not in ambiguous.task
	assert document.initial_url is None
	assert 'First navigate to' not in document.task


def test_beta_agent_exposes_browser_use_settings():
	from browser_use.beta import Agent

	class LLM:
		model = 'gpt-test'
		provider = 'test-provider'

	agent = Agent(
		task='Open example.com',
		llm=cast(Any, LLM()),
		use_vision=False,
		max_actions_per_step=2,
		directly_open_url=False,
		available_file_paths=['/tmp/report.txt'],
		file_system_path='/tmp/browser-use-files',
		include_recent_events=True,
	)

	assert agent.initial_url is None
	assert agent.settings.use_vision is True
	assert agent._sdk_run_params(max_steps=2, task=agent.task)['use_vision'] is True
	assert agent.settings.max_actions_per_step == 2
	assert agent.directly_open_url is False
	assert agent.available_file_paths == ['/tmp/report.txt']
	assert agent.file_system_path == '/tmp/browser-use-files'
	assert agent.include_recent_events is True


def test_beta_agent_defaults_page_extraction_llm_to_main_llm():
	from browser_use.beta import Agent

	class LLM:
		model = 'gpt-test'
		provider = 'test'

		async def ainvoke(self, messages, output_format=None, **kwargs):
			return type('Result', (), {'usage': None})()

	class ExtractionLLM:
		model = 'extract-test'
		provider = 'test'

		async def ainvoke(self, messages, output_format=None, **kwargs):
			return type('Result', (), {'usage': None})()

	llm = LLM()
	extraction_llm = ExtractionLLM()

	default_agent = Agent(task='Extract with the main model.', llm=llm)
	override_agent = Agent(
		task='Extract with a dedicated model.',
		llm=llm,
		page_extraction_llm=extraction_llm,
	)

	assert default_agent.settings.page_extraction_llm is llm
	assert override_agent.settings.page_extraction_llm is extraction_llm
	assert str(id(llm)) in default_agent.token_cost_service.registered_llms
	assert str(id(extraction_llm)) in override_agent.token_cost_service.registered_llms


def test_beta_agent_default_llm_matches_browser_use_default(monkeypatch):
	from browser_use.agent.service import _PythonAgent as BrowserUseAgent
	from browser_use.beta import Agent as BetaAgent

	monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-anthropic-key')

	browser_use_agent = BrowserUseAgent(task='Use the default model.', directly_open_url=False)
	beta_agent = BetaAgent(task='Use the default model.', directly_open_url=False)

	assert browser_use_agent.llm.provider == 'browser-use'
	assert beta_agent.llm.provider == browser_use_agent.llm.provider
	assert beta_agent.model == browser_use_agent.llm.model


def test_beta_agent_default_llm_respects_default_llm_env(monkeypatch):
	from browser_use.beta import Agent

	monkeypatch.setenv('OPENAI_API_KEY', 'test-openai-key')
	monkeypatch.setenv('DEFAULT_LLM', 'openai_gpt_4_1_mini')

	agent = Agent(task='Use configured default model.', directly_open_url=False)

	assert agent.llm.provider == 'openai'
	assert agent.llm.model == 'gpt-4.1-mini'


def test_beta_agent_explicit_llm_ignores_default_llm_env(monkeypatch):
	from browser_use.beta import Agent

	monkeypatch.setenv('DEFAULT_LLM', 'openai_gpt_4_1_mini')

	class LLM:
		model = 'gpt-test'
		provider = 'test-provider'

	agent = Agent(task='Use configured default model.', llm=cast(Any, LLM()), directly_open_url=False)

	assert agent.llm.provider == 'test-provider'
	assert agent.llm.model == 'gpt-test'


def test_beta_agent_enables_flash_mode_for_browser_use_llm_provider():
	from browser_use.agent.service import _PythonAgent as BrowserUseAgent
	from browser_use.beta import Agent as BetaAgent

	class BrowserUseLLM:
		model = 'browser-use-test'
		provider = 'browser-use'

		async def ainvoke(self, messages, output_format=None, **kwargs):
			return type('Result', (), {'usage': None})()

	class OtherLLM:
		model = 'gpt-test'
		provider = 'test'

		async def ainvoke(self, messages, output_format=None, **kwargs):
			return type('Result', (), {'usage': None})()

	browser_use_llm = BrowserUseLLM()
	browser_use_agent = BrowserUseAgent(task='Use Browser Use model.', llm=browser_use_llm, directly_open_url=False)
	beta_browser_use_agent = BetaAgent(task='Use Browser Use model.', llm=browser_use_llm, directly_open_url=False)
	beta_other_agent = BetaAgent(task='Use another model.', llm=OtherLLM(), directly_open_url=False)

	assert browser_use_agent.settings.flash_mode is True
	assert beta_browser_use_agent.settings.flash_mode is True
	assert beta_other_agent.settings.flash_mode is False
	assert beta_browser_use_agent.AgentOutput.__name__ == browser_use_agent.AgentOutput.__name__


def test_beta_agent_llm_timeout_defaults_match_browser_use_model_families():
	from browser_use.agent.service import _PythonAgent as BrowserUseAgent
	from browser_use.beta import Agent as BetaAgent

	class LLM:
		provider = 'test'

		def __init__(self, model):
			self.model = model

		async def ainvoke(self, messages, output_format=None, **kwargs):
			return type('Result', (), {'usage': None})()

	for model in ['gpt-test', 'gemini-2.5-pro', 'groq-llama', 'o3-mini', 'claude-sonnet', 'deepseek-chat']:
		browser_use_agent = BrowserUseAgent(task='Inspect timeout.', llm=LLM(model), directly_open_url=False)
		beta_agent = BetaAgent(task='Inspect timeout.', llm=LLM(model), directly_open_url=False)

		assert beta_agent.settings.llm_timeout == browser_use_agent.settings.llm_timeout

	override_agent = BetaAgent(task='Override timeout.', llm=LLM('gemini-2.5-pro'), llm_timeout=12)

	assert override_agent.settings.llm_timeout == 12


def test_beta_agent_forces_vision_for_all_model_families():
	from browser_use.beta import Agent as BetaAgent

	class LLM:
		provider = 'test'

		def __init__(self, model):
			self.model = model

		async def ainvoke(self, messages, output_format=None, **kwargs):
			return type('Result', (), {'usage': None})()

	for model in ['deepseek-chat', 'grok-3', 'grok-code']:
		beta_agent = BetaAgent(task='Inspect vision.', llm=LLM(model), directly_open_url=False, use_vision=False)

		assert beta_agent.settings.use_vision is True

	normal_agent = BetaAgent(task='Inspect vision.', llm=LLM('gpt-test'), directly_open_url=False, use_vision=False)

	assert normal_agent.settings.use_vision is True


def test_beta_agent_does_not_warn_when_forcing_vision(monkeypatch):
	from browser_use.beta import Agent as BetaAgent

	class LLM:
		provider = 'test'

		def __init__(self, model):
			self.model = model

		async def ainvoke(self, messages, output_format=None, **kwargs):
			return type('Result', (), {'usage': None})()

	class RecordingLogger:
		def __init__(self):
			self.warnings = []

		def info(self, message, *args, **kwargs):
			pass

		def debug(self, message, *args, **kwargs):
			pass

		def warning(self, message, *args, **kwargs):
			self.warnings.append(message)

		def error(self, message, *args, **kwargs):
			pass

	for model in ['deepseek-chat', 'grok-2']:
		beta_logger = RecordingLogger()
		monkeypatch.setattr(BetaAgent, 'logger', property(lambda self, logger=beta_logger: logger))

		BetaAgent(task='Inspect vision warning.', llm=LLM(model), directly_open_url=False, use_vision=False)

		assert beta_logger.warnings == []


def test_beta_agent_constructor_debug_summary_matches_browser_use(monkeypatch):
	import browser_use.agent.service as agent_service
	import browser_use.beta.service as beta_service
	from browser_use.agent.service import _PythonAgent as BrowserUseAgent
	from browser_use.beta import Agent as BetaAgent

	class LLM:
		model = 'gpt-test'
		provider = 'test'

		async def ainvoke(self, messages, output_format=None, **kwargs):
			return type('Result', (), {'usage': None})()

	class RecordingModuleLogger:
		def __init__(self):
			self.debugs = []

		def debug(self, message, *args, **kwargs):
			self.debugs.append(message)

	browser_use_logger = RecordingModuleLogger()
	beta_logger = RecordingModuleLogger()
	monkeypatch.setattr(agent_service, 'logger', browser_use_logger)
	monkeypatch.setattr(beta_service, 'logger', beta_logger)

	BrowserUseAgent(task='Inspect constructor setup.', llm=LLM(), directly_open_url=False)
	BetaAgent(task='Inspect constructor setup.', llm=LLM(), directly_open_url=False)

	expected = ' +vision extraction_model=gpt-test +file_system'
	assert browser_use_logger.debugs[-1] == expected
	assert beta_logger.debugs[-1] == expected


def test_beta_agent_state_id_defaults_like_browser_use():
	from browser_use.agent.service import _PythonAgent as BrowserUseAgent
	from browser_use.agent.views import AgentState
	from browser_use.beta import Agent as BetaAgent

	class LLM:
		model = 'gpt-test'
		provider = 'test'

		async def ainvoke(self, messages, output_format=None, **kwargs):
			return type('Result', (), {'usage': None})()

	llm = LLM()
	browser_use_task_id = 'browser_use_state'
	beta_task_id = 'rust_state_id'
	browser_use_agent = BrowserUseAgent(
		task='Inspect state.',
		llm=llm,
		task_id=browser_use_task_id,
		directly_open_url=False,
	)
	beta_agent = BetaAgent(task='Inspect state.', llm=llm, task_id=beta_task_id, directly_open_url=False)

	assert browser_use_agent.task_id == browser_use_task_id
	assert beta_agent.task_id == beta_task_id
	assert browser_use_agent.state.agent_id != browser_use_task_id
	assert beta_agent.state.agent_id != beta_task_id
	assert beta_agent.state.n_steps == browser_use_agent.state.n_steps == 1

	injected_state = AgentState(agent_id='restored-state-id')
	restored_agent = BetaAgent(task='Restore state.', injected_agent_state=injected_state)

	assert restored_agent.state is injected_state
	assert restored_agent.state.agent_id == 'restored-state-id'


def test_beta_agent_eventbus_name_matches_browser_use_suffix_prefix():
	from browser_use.agent.service import _PythonAgent as BrowserUseAgent
	from browser_use.beta import Agent as BetaAgent

	class LLM:
		model = 'gpt-test'
		provider = 'test'

		async def ainvoke(self, messages, output_format=None, **kwargs):
			return type('Result', (), {'usage': None})()

	browser_use_agent = BrowserUseAgent(task='Inspect event bus.', llm=LLM(), task_id='browseruseabcd', directly_open_url=False)
	beta_agent = BetaAgent(task='Inspect event bus.', llm=LLM(), task_id='rustagentwxyz', directly_open_url=False)

	assert browser_use_agent.eventbus.name == 'Agent_abcd'
	assert beta_agent.eventbus.name == 'Agent_wxyz'

	beta_agent_with_hyphen = BetaAgent(task='Inspect event bus.', llm=LLM(), task_id='task-1', directly_open_url=False)
	initial_name = beta_agent_with_hyphen.eventbus.name
	beta_agent_with_hyphen.add_new_task('Follow up.')

	assert initial_name == 'Agent_sk_1'
	assert beta_agent_with_hyphen.eventbus.name.startswith(f'{initial_name}_')
	assert beta_agent_with_hyphen.eventbus.name.isidentifier()


def test_beta_agent_constructor_aliases_match_browser_use():
	from browser_use.agent.service import _PythonAgent as BrowserUseAgent
	from browser_use.beta import Agent as BetaAgent
	from browser_use.tools.service import Tools

	class LLM:
		model = 'gpt-test'
		provider = 'test'

		async def ainvoke(self, messages, output_format=None, **kwargs):
			return type('Result', (), {'usage': None})()

	tools = Tools()
	controller = Tools()

	browser_use_agent = BrowserUseAgent(
		task='Resolve aliases.',
		llm=LLM(),
		tools=tools,
		controller=controller,
		directly_open_url=False,
	)
	beta_agent = BetaAgent(
		task='Resolve aliases.',
		llm=LLM(),
		tools=tools,
		controller=controller,
		directly_open_url=False,
	)

	assert browser_use_agent.tools is tools
	assert beta_agent.tools is tools

	expected_error = 'Cannot specify both "browser" and "browser_session" parameters. Use "browser" for the cleaner API.'
	for agent_class in (BrowserUseAgent, BetaAgent):
		with pytest.raises(ValueError) as exc_info:
			agent_class(
				task='Conflicting browser aliases.',
				llm=LLM(),
				browser=object(),
				browser_session=object(),
				directly_open_url=False,
			)
		assert str(exc_info.value) == expected_error


def test_beta_agent_initializes_tools_and_action_models():
	from browser_use.beta import Agent
	from browser_use.tools.service import Tools

	class Answer(BaseModel):
		answer: str

	agent = Agent(
		task='Return structured answer.',
		output_model_schema=Answer,
		use_vision=False,
	)

	action_names = set(agent.tools.registry.registry.actions)
	done_schema = agent.DoneActionModel.model_json_schema()

	assert isinstance(agent.tools, Tools)
	assert 'done' in action_names
	assert agent.settings.use_vision is True
	assert 'screenshot' in action_names
	assert agent.ActionModel is not None
	assert agent.DoneActionModel is not None
	assert agent.AgentOutput is not None
	assert 'done' in str(done_schema)


def test_beta_agent_setup_action_models_signature_matches_browser_use():
	from browser_use.agent.service import _PythonAgent as BrowserUseAgent
	from browser_use.beta import Agent as BetaAgent

	browser_use_signature = inspect.signature(BrowserUseAgent._setup_action_models)
	beta_signature = inspect.signature(BetaAgent._setup_action_models)

	assert list(beta_signature.parameters) == list(browser_use_signature.parameters) == ['self']

	agent = BetaAgent(task='Rebuild action models.')
	agent.ActionModel = None
	agent.DoneActionModel = None
	agent.AgentOutput = None
	agent.DoneAgentOutput = None

	agent._setup_action_models()

	assert agent.ActionModel is not None
	assert agent.DoneActionModel is not None
	assert agent.AgentOutput is not None
	assert agent.DoneAgentOutput is not None


async def test_beta_agent_updates_action_models_for_page(monkeypatch):
	from browser_use.beta import Agent

	agent = Agent(task='Use page-specific tools.')
	registry = agent.tools.registry
	original_create_action_model = registry.create_action_model
	seen = []

	def recording_create_action_model(*args, **kwargs):
		seen.append(kwargs)
		return original_create_action_model(*args, **kwargs)

	monkeypatch.setattr(registry, 'create_action_model', recording_create_action_model)

	await agent._update_action_models_for_page('https://example.com/settings')

	assert seen == [
		{'page_url': 'https://example.com/settings'},
		{'include_actions': ['done'], 'page_url': 'https://example.com/settings'},
	]
	assert agent.ActionModel is not None
	assert agent.DoneActionModel is not None
	assert agent.AgentOutput is not None
	assert agent.DoneAgentOutput is not None


def test_beta_agent_initializes_runtime_metadata_and_observability(monkeypatch):
	from browser_use.beta import Agent
	from browser_use.tokens.service import TokenCost

	monkeypatch.delenv('BU_USE_CALCULATE_COST', raising=False)

	class LLM:
		model = 'gpt-test'
		provider = 'test'

		async def ainvoke(self, messages, output_format=None, **kwargs):
			return type('Result', (), {'usage': None})()

	llm = LLM()
	agent = Agent(
		task='Inspect metadata.',
		llm=llm,
		task_id='task-1234',
		source='ci',
		calculate_cost=True,
		use_thinking=False,
	)

	assert agent.version
	assert agent.source == 'ci'
	assert agent.logger.name.endswith('1234 ⇢ 🅑 1234 🅣 --')
	assert agent.eventbus is not None
	assert callable(agent.telemetry.capture)
	assert callable(agent.telemetry.flush)
	assert isinstance(agent.token_cost_service, TokenCost)
	assert agent.token_cost_service.include_cost is True
	assert str(id(llm)) in agent.token_cost_service.registered_llms
	assert agent.DoneAgentOutput is not None
	assert agent._run_env()['BU_USE_CALCULATE_COST'] == 'true'

	default_agent = Agent(task='Inspect default metadata.', llm=LLM())
	assert 'BU_USE_CALCULATE_COST' not in default_agent._run_env()


async def test_beta_agent_logger_name_matches_browser_use(monkeypatch):
	import browser_use.beta.service as beta_service
	from browser_use.agent.service import _PythonAgent as BrowserUseAgent
	from browser_use.beta import Agent as BetaAgent
	from browser_use.browser import BrowserProfile, BrowserSession

	class TestEventBus:
		def __init__(self, name):
			self.name = name

		def stop(self, *args, **kwargs):
			return None

	monkeypatch.setattr(beta_service, 'EventBus', TestEventBus)

	class LLM:
		model = 'gpt-test'
		provider = 'test'

		async def ainvoke(self, messages, output_format=None, **kwargs):
			return type('Result', (), {'usage': None})()

	async def stop_eventbus(eventbus):
		try:
			result = eventbus.stop(timeout=0.1, clear=True)
		except TypeError:
			result = eventbus.stop(timeout=0.1)
		if inspect.isawaitable(result):
			await result

	browser_use_agent = BrowserUseAgent(
		task='Inspect logger name.',
		llm=LLM(),
		browser_session=BrowserSession(browser_profile=BrowserProfile(), id='browser-abcd'),
		task_id='task-1234',
		directly_open_url=False,
	)
	browser_use_logger_name = browser_use_agent.logger.name
	await stop_eventbus(browser_use_agent.eventbus)

	beta_agent = BetaAgent(
		task='Inspect logger name.',
		llm=LLM(),
		browser_session=BrowserSession(browser_profile=BrowserProfile(), id='browser-abcd'),
		task_id='task-1234',
		directly_open_url=False,
	)

	assert beta_agent.logger.name == browser_use_logger_name
	assert beta_agent.logger.name == 'browser_use.Agent🅰 1234 ⇢ 🅑 abcd 🅣 --'
	await stop_eventbus(beta_agent.eventbus)


async def test_beta_agent_exposes_logging_helper_methods(monkeypatch):
	import time

	import browser_use.beta.service as beta_service
	from browser_use.agent.views import ActionResult
	from browser_use.beta import Agent

	class LLM:
		model = 'gpt-test'
		provider = 'test-provider'

	class BrowserProfile:
		downloads_path = None

	class BrowserSession:
		cdp_url = 'wss://browser.example/devtools/browser/1'
		browser_profile = BrowserProfile()

	class FakeAction:
		def model_dump(self, **kwargs):
			return {'navigate': {'url': 'https://example.com', 'new_tab': False}}

	class Parsed:
		action = [FakeAction()]

	class DomState:
		selector_map = {1: object(), 2: object()}

	class BrowserStateSummary:
		url = 'https://example.com/a/very/long/path/that/will/be/shortened/in/logging'
		dom_state = DomState()

	async def no_latest_version():
		return None

	captured_events = []

	class Telemetry:
		def capture(self, event):
			captured_events.append(event)

	monkeypatch.setattr(beta_service, 'check_latest_browser_use_version', no_latest_version)
	agent = Agent(task='Log helper parity.', llm=LLM(), browser_session=BrowserSession())
	agent.telemetry = Telemetry()

	await agent._log_agent_run()
	agent._log_first_step_startup()
	agent._log_step_context(BrowserStateSummary())
	agent._log_next_action_summary(Parsed())
	agent._log_step_completion_summary(time.time() - 1, [ActionResult(extracted_content='ok')])
	agent._log_action(FakeAction(), 'navigate', 1, 2)
	agent.history = beta_service._history_from_events(
		[
			{'event_type': 'browser.state', 'payload': {'url': 'https://example.com', 'title': 'Example'}},
			{
				'event_type': 'model.usage',
				'payload': {'input_tokens': 11, 'cached_input_tokens': 3, 'output_tokens': 7, 'cost_usd': 0.12},
			},
			{'event_type': 'session.done', 'payload': {'result': 'done'}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.5,
		output_model_schema=None,
		process_error=None,
	)
	agent._sync_state_from_history()
	agent.state.n_steps = 99
	agent._log_final_outcome_messages()
	agent._log_agent_event(max_steps=9, agent_run_error='manual-error')

	assert captured_events
	assert captured_events[0].model == 'gpt-test'
	assert captured_events[0].model_provider == 'test-provider'
	assert captured_events[0].agent_type == 'rust_core'
	assert captured_events[0].cdp_url == 'browser.example'
	assert captured_events[0].action_history == [[{'done': {'text': 'done', 'success': True}}]]
	assert captured_events[0].urls_visited == ['https://example.com']
	assert captured_events[0].steps == 1
	assert captured_events[0].total_input_tokens == 11
	assert captured_events[0].total_output_tokens == 7
	assert captured_events[0].prompt_cached_tokens == 3
	assert captured_events[0].final_result_response == '"done"'
	assert captured_events[0].error_message == 'manual-error'


def test_beta_agent_telemetry_filters_empty_reconstructed_urls():
	import browser_use.beta.service as beta_service
	from browser_use.beta import Agent

	class LLM:
		model = 'gpt-test'
		provider = 'test-provider'

	captured_events = []

	class Telemetry:
		def capture(self, event):
			captured_events.append(event)

	agent = Agent(task='Log telemetry URLs.', llm=cast(Any, LLM()), directly_open_url=False)
	agent.telemetry = Telemetry()
	agent.history = beta_service._history_from_events(
		[
			{'event_type': 'model.turn.request', 'payload': {'model': 'gpt-test'}},
			{
				'event_type': 'tool.output',
				'payload': {'name': 'browser', 'text': 'Connected to browser at http://127.0.0.1:41335'},
			},
			{'event_type': 'model.turn.request', 'payload': {'model': 'gpt-test'}},
			{'event_type': 'browser.state', 'payload': {'url': 'https://example.com', 'title': 'Example'}},
			{'event_type': 'session.done', 'payload': {'result': 'done'}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	agent._log_agent_event(max_steps=3)

	assert captured_events[0].agent_type == 'rust_core'
	assert captured_events[0].urls_visited == ['https://example.com']


def test_beta_agent_telemetry_records_cloud_cdp_hostname():
	import browser_use.beta.service as beta_service
	from browser_use.beta import Agent

	class LLM:
		model = 'gpt-test'
		provider = 'test-provider'

	class BrowserProfile:
		downloads_path = None

	class BrowserSession:
		cdp_url = 'wss://cloud-browser.example/devtools/browser/session'
		browser_profile = BrowserProfile()

	captured_events = []

	class Telemetry:
		def capture(self, event):
			captured_events.append(event)

	agent = Agent(task='Log cloud CDP telemetry.', llm=cast(Any, LLM()), browser_session=cast(Any, BrowserSession()))
	agent.telemetry = Telemetry()
	agent.history = beta_service._history_from_events(
		[
			{'event_type': 'browser.state', 'payload': {'url': 'https://example.com', 'title': 'Example'}},
			{'event_type': 'session.done', 'payload': {'result': 'done'}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	agent._log_agent_event(max_steps=3)

	assert captured_events[0].name == 'agent_event'
	assert captured_events[0].agent_type == 'rust_core'
	assert captured_events[0].cdp_url == 'cloud-browser.example'
	assert captured_events[0].urls_visited == ['https://example.com']


async def test_beta_agent_run_metadata_logs_match_browser_use(monkeypatch):
	import browser_use.agent.service as agent_service
	import browser_use.beta.service as beta_service
	from browser_use.agent.service import _PythonAgent as BrowserUseAgent
	from browser_use.beta import Agent as BetaAgent

	class LLM:
		model = 'gpt-test'
		provider = 'test'

		async def ainvoke(self, messages, output_format=None, **kwargs):
			return type('Result', (), {'usage': None})()

	class RecordingLogger:
		def __init__(self):
			self.infos = []
			self.debugs = []

		def info(self, message, *args, **kwargs):
			self.infos.append(message)

		def debug(self, message, *args, **kwargs):
			self.debugs.append(message)

	async def latest_version():
		return '99.99.99'

	browser_use_logger = RecordingLogger()
	beta_logger = RecordingLogger()
	monkeypatch.setattr(agent_service, 'check_latest_browser_use_version', latest_version)
	monkeypatch.setattr(beta_service, 'check_latest_browser_use_version', latest_version)
	monkeypatch.setattr(BrowserUseAgent, 'logger', property(lambda self: browser_use_logger))
	monkeypatch.setattr(BetaAgent, 'logger', property(lambda self: beta_logger))

	browser_use_agent = BrowserUseAgent(
		task='Log run metadata parity.',
		llm=LLM(),
		task_id='runmetadatabu',
		directly_open_url=False,
	)
	beta_agent = BetaAgent(
		task='Log run metadata parity.',
		llm=LLM(),
		task_id='runmetadatars',
		directly_open_url=False,
	)
	browser_use_logger.infos.clear()
	browser_use_logger.debugs.clear()
	beta_logger.infos.clear()
	beta_logger.debugs.clear()

	await browser_use_agent._log_agent_run()
	await beta_agent._log_agent_run()

	assert beta_logger.infos == browser_use_logger.infos
	assert beta_logger.debugs == browser_use_logger.debugs
	assert beta_logger.infos[0] == '\033[34m🎯 Task: Log run metadata parity.\033[0m'
	assert beta_logger.debugs[0].startswith('🤖 Browser-Use Library Version')
	assert beta_logger.infos[1].startswith('📦 Newer version available: 99.99.99')


async def test_beta_agent_exposes_step_finalization_helper_methods(tmp_path):
	import base64
	import time

	from browser_use.agent.views import ActionResult, AgentStepInfo
	from browser_use.beta import Agent

	class DomState:
		selector_map = {}

	class BrowserStateSummary:
		url = 'https://example.com/final'
		title = 'Final'
		tabs = []
		screenshot = base64.b64encode(b'png-bytes').decode('utf-8')
		dom_state = DomState()

	class EventBus:
		def __init__(self):
			self.dispatched = []

		def dispatch(self, event):
			self.dispatched.append(event)
			return event

	agent = Agent(task='Finalize helper parity.', file_system_path=str(tmp_path / 'agent-files'))
	agent.eventbus = EventBus()

	await agent._handle_step_error(ValueError('bad step'))
	assert agent.state.consecutive_failures == 1
	assert agent.state.last_result is not None
	assert agent.state.last_result[-1].error is not None
	assert agent.state.last_result[-1].error.startswith('bad step')

	await agent._post_process()
	assert agent.state.consecutive_failures == 2

	agent.state.last_result = [
		ActionResult(is_done=True, success=True, extracted_content='final answer', attachments=['file:///tmp/report.txt'])
	]
	await agent._post_process()
	assert agent.state.consecutive_failures == 0

	agent.state.last_model_output = agent.AgentOutput(
		evaluation_previous_goal='Need answer',
		memory='Have answer',
		next_goal='Finish',
		action=[agent.ActionModel(done={'text': 'final answer', 'success': True})],
	)
	agent.step_start_time = time.time() - 0.1
	await agent._finalize(BrowserStateSummary())

	assert agent.state.n_steps == 2
	assert agent.state.file_system_state is not None
	assert agent.history.final_result() == 'final answer'
	assert agent.history.urls() == ['https://example.com/final']
	assert Path(agent.history.history[0].state.screenshot_path).read_bytes() == b'png-bytes'
	assert [type(event).__name__ for event in agent.eventbus.dispatched] == ['CreateAgentStepEvent']
	assert agent.eventbus.dispatched[0].agent_task_id == str(agent.task_id)
	assert agent.eventbus.dispatched[0].actions == [{'done': {'text': 'final answer', 'success': True, 'files_to_display': []}}]
	assert agent.eventbus.dispatched[0].url == 'https://example.com/final'
	assert agent.eventbus.dispatched[0].screenshot_url.startswith('data:image/')
	assert ';base64,' in agent.eventbus.dispatched[0].screenshot_url

	await agent._force_done_after_last_step(AgentStepInfo(step_number=2, max_steps=3))
	assert agent.AgentOutput is agent.DoneAgentOutput

	agent.state.consecutive_failures = agent.settings.max_failures
	agent.AgentOutput = None
	await agent._force_done_after_failure()
	assert agent.AgentOutput is agent.DoneAgentOutput


async def test_beta_agent_finalize_logs_step_completion_without_browser_state(monkeypatch, tmp_path):
	import time

	from browser_use.agent.views import ActionResult
	from browser_use.beta import Agent

	class RecordingLogger:
		def __init__(self):
			self.debugs = []

		def debug(self, message, *args, **kwargs):
			self.debugs.append(message)

	class EventBus:
		def __init__(self):
			self.dispatched = []

		def dispatch(self, event):
			self.dispatched.append(event)
			return event

	logger = RecordingLogger()
	monkeypatch.setattr(Agent, 'logger', property(lambda self: logger))
	agent = Agent(task='Finalize without browser state.', file_system_path=str(tmp_path / 'agent-files'))
	agent.eventbus = EventBus()
	agent.state.last_result = [ActionResult(extracted_content='ok')]
	agent.step_start_time = time.time() - 0.1
	starting_steps = agent.state.n_steps

	await agent._finalize(None)

	assert agent.state.n_steps == starting_steps + 1
	assert agent.state.file_system_state is not None
	assert agent.history.history == []
	assert agent.eventbus.dispatched == []
	assert any('Ran 1 action' in message and 'success=1' in message for message in logger.debugs)


async def test_beta_agent_finalize_orders_summary_save_before_step_event(monkeypatch, tmp_path):
	import base64
	import time

	from browser_use.agent.views import ActionResult
	from browser_use.beta import Agent

	calls = []

	class RecordingLogger:
		def debug(self, message, *args, **kwargs):
			if 'Ran 1 action' in message:
				calls.append('summary')

	class DomState:
		selector_map = {}

	class BrowserStateSummary:
		url = 'https://example.com/finalize-order'
		title = 'Finalize Order'
		tabs = []
		screenshot = base64.b64encode(b'png-bytes').decode('utf-8')
		dom_state = DomState()

	class EventBus:
		def __init__(self):
			self.dispatched = []

		def dispatch(self, event):
			calls.append('dispatch')
			self.dispatched.append(event)
			return event

	logger = RecordingLogger()
	monkeypatch.setattr(Agent, 'logger', property(lambda self: logger))
	agent = Agent(task='Finalize order parity.', file_system_path=str(tmp_path / 'agent-files'))
	agent.eventbus = EventBus()
	agent.state.last_result = [ActionResult(is_done=True, success=True, extracted_content='final answer')]
	agent.state.last_model_output = agent.AgentOutput(
		evaluation_previous_goal='Need answer',
		memory='Have answer',
		next_goal='Finish',
		action=[agent.ActionModel(done={'text': 'final answer', 'success': True})],
	)
	agent.step_start_time = time.time() - 0.1
	monkeypatch.setattr(agent, 'save_file_system_state', lambda: calls.append('save'))
	starting_steps = agent.state.n_steps

	await agent._finalize(BrowserStateSummary())

	assert calls == ['summary', 'save', 'dispatch']
	assert agent.state.n_steps == starting_steps + 1
	assert [type(event).__name__ for event in agent.eventbus.dispatched] == ['CreateAgentStepEvent']


async def test_beta_agent_done_only_guidance_matches_browser_use(monkeypatch):
	from browser_use.agent.views import AgentStepInfo
	from browser_use.beta import Agent

	class RecordingLogger:
		def __init__(self):
			self.debugs = []

		def debug(self, message, *args, **kwargs):
			self.debugs.append(message)

	messages = []
	logger = RecordingLogger()
	monkeypatch.setattr(Agent, 'logger', property(lambda self: logger))
	agent = Agent(task='Done-only guidance parity.')
	monkeypatch.setattr(agent._message_manager, '_add_context_message', lambda message: messages.append(message.content))

	await agent._force_done_after_last_step(AgentStepInfo(step_number=2, max_steps=3))
	assert agent.AgentOutput is agent.DoneAgentOutput
	assert logger.debugs == ['Last step finishing up']
	assert len(messages) == 1
	assert 'All other tools which you see in history or examples are not available.' in messages[-1]
	assert 'set success in "done" to false! E.g. if not all steps are fully completed.' in messages[-1]

	agent.AgentOutput = None
	agent.state.consecutive_failures = agent.settings.max_failures
	await agent._force_done_after_failure()
	assert agent.AgentOutput is agent.DoneAgentOutput
	assert logger.debugs[-1] == 'Force done action, because we reached max_failures.'
	assert len(messages) == 2
	assert messages[-1].startswith(f'You failed {agent.settings.max_failures} times. Therefore we terminate the agent.')
	assert 'All other tools which you see in history or examples are not available.' in messages[-1]
	assert 'set success in "done" to false! E.g. if not all steps are fully completed.' in messages[-1]


async def test_beta_agent_post_process_logs_browser_use_result_messages(monkeypatch):
	from browser_use.agent.views import ActionResult
	from browser_use.beta import Agent

	class RecordingLogger:
		def __init__(self):
			self.debugs = []
			self.infos = []

		def debug(self, message, *args, **kwargs):
			self.debugs.append(message)

		def info(self, message, *args, **kwargs):
			self.infos.append(message)

	logger = RecordingLogger()
	monkeypatch.setattr(Agent, 'logger', property(lambda self: logger))
	agent = Agent(task='Post-process log parity.')
	download_checks = []

	async def fake_check_downloads(label):
		download_checks.append(label)

	agent._check_and_update_downloads = fake_check_downloads

	agent.state.last_result = [ActionResult(error='failed action')]
	await agent._post_process()
	assert agent.state.consecutive_failures == 1
	assert logger.debugs == [f'🔄 Step {agent.state.n_steps}: Consecutive failures: 1']

	agent.state.last_result = [
		ActionResult(
			is_done=True, success=True, extracted_content='final answer', attachments=['file:///tmp/a.txt', 'file:///tmp/b.txt']
		)
	]
	await agent._post_process()
	assert agent.state.consecutive_failures == 0
	assert logger.debugs[-1] == f'🔄 Step {agent.state.n_steps}: Consecutive failures reset to: 0'
	assert logger.infos[-3:] == [
		'\n📄 \033[32m Final Result:\033[0m \nfinal answer\n\n',
		'👉 Attachment 1: file:///tmp/a.txt',
		'👉 Attachment 2: file:///tmp/b.txt',
	]

	logger.infos.clear()
	agent.state.last_result = [ActionResult(is_done=True, success=False, extracted_content='not done')]
	await agent._post_process()
	assert logger.infos == ['\n📄 \033[31m Final Result:\033[0m \nnot done\n\n']
	assert download_checks == ['after executing actions', 'after executing actions', 'after executing actions']


async def test_beta_agent_handle_step_error_logs_browser_use_failure_prefix(monkeypatch):
	import browser_use.beta.service as beta_service
	from browser_use.beta import Agent

	class RecordingLogger:
		def __init__(self):
			self.errors = []

		def error(self, message, *args, **kwargs):
			self.errors.append(message)

		def debug(self, message, *args, **kwargs):
			pass

		def info(self, message, *args, **kwargs):
			pass

		def warning(self, message, *args, **kwargs):
			pass

		def isEnabledFor(self, level):
			return False

	class LLM:
		model = 'gpt-test'

	agent_logger = RecordingLogger()
	module_logger = RecordingLogger()
	monkeypatch.setattr(Agent, 'logger', property(lambda self: agent_logger))
	monkeypatch.setattr(beta_service, 'logger', module_logger)

	agent = Agent(task='Handle normal step error.', llm=LLM())
	await agent._handle_step_error(ValueError('bad step'))
	assert agent.state.consecutive_failures == 1
	assert agent.state.last_result is not None
	assert agent.state.last_result[-1].error is not None
	assert agent.state.last_result[-1].error.startswith('bad step')
	max_total_failures = agent.settings.max_failures + int(agent.settings.final_response_after_failure)
	assert len(agent_logger.errors) == 1
	assert agent_logger.errors[0].startswith(f'❌ Result failed 1/{max_total_failures} times:\n bad step')

	agent_logger.errors.clear()
	agent.state.last_result = None
	await agent._handle_step_error(InterruptedError('paused'))
	assert agent_logger.errors == ['The agent was interrupted mid-step - paused']
	assert agent.state.last_result is None

	parse_agent = Agent(task='Handle parse step error.', llm=LLM())
	agent_logger.errors.clear()
	module_logger.errors.clear()
	await parse_agent._handle_step_error(ValueError('Could not parse response: missing action'))
	assert parse_agent.state.consecutive_failures == 1
	assert parse_agent.state.last_result[-1].error is not None
	assert parse_agent.state.last_result[-1].error.startswith('Could not parse response: missing action')
	assert agent_logger.errors == []
	parse_max_total_failures = parse_agent.settings.max_failures + int(parse_agent.settings.final_response_after_failure)
	assert module_logger.errors[0] == 'Model: gpt-test failed'
	assert module_logger.errors[1].startswith(
		f'❌ Result failed 1/{parse_max_total_failures} times:\n Could not parse response: missing action'
	)


def test_beta_agent_initializes_message_manager_and_followup_state():
	from browser_use.agent.message_manager.service import MessageManager
	from browser_use.beta import Agent

	agent = Agent(
		task='Initial task.',
		task_id='task-with-hyphen',
		include_recent_events=True,
	)
	initial_eventbus_name = agent.eventbus.name

	agent.add_new_task('Follow up task.')

	assert isinstance(agent.message_manager, MessageManager)
	assert agent.message_manager is agent._message_manager
	assert agent.message_manager.include_recent_events is True
	assert '<initial_user_request>' in agent.message_manager.task
	assert '<follow_up_user_request> Follow up task. </follow_up_user_request>' in agent.message_manager.task
	assert agent.state.follow_up_task is True
	assert agent.state.stopped is False
	assert agent.state.paused is False
	assert agent.eventbus.name.startswith(initial_eventbus_name)
	assert agent.eventbus.name.isidentifier()


def test_beta_agent_initializes_browser_use_session_and_file_system(tmp_path):
	from browser_use.beta import Agent
	from browser_use.browser import BrowserProfile, BrowserSession

	file_system_path = tmp_path / 'agent-files'
	downloads_path = tmp_path / 'downloads'
	agent = Agent(
		task='Open example.com',
		task_id='task-1234',
		browser_profile=BrowserProfile(headless=True, downloads_path=downloads_path),
		file_system_path=str(file_system_path),
	)

	assert isinstance(agent.browser_session, BrowserSession)
	assert agent.browser_session.id.endswith('1234')
	assert agent.browser_profile is agent.browser_session.browser_profile
	assert agent.browser_profile.downloads_path == downloads_path
	assert agent.has_downloads_path is True
	assert agent.file_system_path == str(file_system_path)
	assert agent.file_system.base_dir == file_system_path
	assert agent.state.file_system_state is not None


def test_beta_agent_exposes_setup_helper_methods(tmp_path):
	from browser_use.beta import Agent
	from browser_use.screenshots.service import ScreenshotService

	class LLM:
		_verified_api_keys = True

	initial_file_system_path = tmp_path / 'initial-files'
	new_file_system_path = tmp_path / 'new-files'
	agent = Agent(
		task='Set up helpers.',
		llm=LLM(),
		file_system_path=str(initial_file_system_path),
		source='constructor-source',
	)

	agent.file_system = None
	agent.file_system_path = None
	agent._set_file_system()
	agent._set_screenshot_service()
	agent._set_browser_use_version_and_source('helper-source')

	assert agent.file_system_path == str(initial_file_system_path)
	assert agent.file_system.base_dir == initial_file_system_path
	assert isinstance(agent.screenshot_service, ScreenshotService)
	assert agent.screenshot_service.agent_directory == agent.agent_directory
	assert agent.source == 'helper-source'
	assert agent.version
	assert agent._verify_and_setup_llm() is True

	with pytest.raises(ValueError, match='Cannot provide both file_system_state'):
		agent._set_file_system(str(new_file_system_path))

	agent.state.file_system_state = None
	agent._set_file_system(str(new_file_system_path))

	assert agent.file_system_path == str(new_file_system_path)
	assert agent.file_system.base_dir == new_file_system_path


def test_beta_agent_constructor_invokes_llm_verification(monkeypatch):
	from browser_use.beta import Agent

	class LLM:
		model = 'gpt-test'
		provider = 'test-provider'
		_verified_api_keys = False

	monkeypatch.setenv('SKIP_LLM_API_KEY_VERIFICATION', 'true')

	llm = LLM()
	agent = Agent(task='Verify LLM during construction.', llm=llm, directly_open_url=False)

	assert agent.llm is llm
	assert llm._verified_api_keys is True


def test_beta_agent_browser_profile_property_tracks_session_profile():
	from browser_use.beta import Agent

	class FirstProfile:
		downloads_path = None

	class SecondProfile:
		downloads_path = '/tmp/changed-downloads'

	class BrowserSession:
		browser_profile = FirstProfile()

	session = BrowserSession()
	agent = Agent(task='Use the current browser profile.', browser_session=session)

	assert agent.browser_profile is session.browser_profile

	session.browser_profile = SecondProfile()

	assert agent.browser_profile is session.browser_profile
	assert agent.browser_profile.downloads_path == '/tmp/changed-downloads'


async def test_beta_agent_tracks_downloaded_files_and_saves_file_system_state(tmp_path):
	from browser_use.beta import Agent

	class BrowserProfile:
		downloads_path = tmp_path / 'downloads'

	class BrowserSession:
		browser_profile = BrowserProfile()
		downloaded_files = ['/tmp/report.csv', '/tmp/report.csv']

	agent = Agent(
		task='Use downloaded files.',
		browser_session=BrowserSession(),
		available_file_paths=['/tmp/input.txt'],
		file_system_path=str(tmp_path / 'agent-files'),
	)

	await agent._check_and_update_downloads('test')
	BrowserSession.downloaded_files = ['/tmp/report.csv', '/tmp/summary.pdf']
	await agent._check_and_update_downloads('test')

	agent.state.file_system_state = None
	agent.save_file_system_state()

	assert agent.available_file_paths == ['/tmp/input.txt', '/tmp/report.csv', '/tmp/summary.pdf']
	assert agent._last_known_downloads == ['/tmp/report.csv', '/tmp/summary.pdf']
	assert agent.state.file_system_state is not None
	assert agent.state.file_system_state.base_dir == str(tmp_path / 'agent-files')


async def test_beta_agent_initializes_screenshot_service(tmp_path):
	import base64

	from browser_use.beta import Agent
	from browser_use.screenshots.service import ScreenshotService

	agent = Agent(task='Capture a screenshot.', file_system_path=str(tmp_path / 'agent-files'))

	assert isinstance(agent.screenshot_service, ScreenshotService)
	assert agent.screenshot_service.agent_directory == agent.agent_directory
	assert agent.screenshot_service.screenshots_dir == agent.agent_directory / 'screenshots'
	assert agent.screenshot_service.screenshots_dir.exists()

	screenshot_b64 = base64.b64encode(b'png-bytes').decode('utf-8')
	screenshot_path = await agent.screenshot_service.store_screenshot(screenshot_b64, step_number=3)

	assert Path(screenshot_path).name == 'step_3.png'
	assert Path(screenshot_path).read_bytes() == b'png-bytes'
	assert await agent.screenshot_service.get_screenshot(screenshot_path) == screenshot_b64


def test_beta_agent_adds_available_files_to_task_context():
	from browser_use.beta import Agent

	agent = Agent(
		task='Summarize the provided report.',
		available_file_paths=['/tmp/report.txt', '~/notes.md'],
	)

	assert agent.available_file_paths == ['/tmp/report.txt', '~/notes.md']
	assert 'Available local files:' in agent.task
	assert '- /tmp/report.txt' in agent.task
	assert '- ' in agent.task and 'notes.md' in agent.task


def test_beta_agent_default_model_uses_browser_use_default_llm(monkeypatch):
	from browser_use.agent.service import _PythonAgent as BrowserUseAgent
	from browser_use.beta import Agent

	monkeypatch.setenv('BROWSER_USE_RUST_MODEL', 'legacy-codex-default')

	agent = Agent(task='report title')
	browser_use_agent = BrowserUseAgent(task='report title')

	assert agent.llm.provider == browser_use_agent.llm.provider == 'browser-use'
	assert agent.model == browser_use_agent.llm.model


async def test_beta_agent_log_completion_matches_browser_use(monkeypatch):
	import browser_use.beta.service as beta_service
	from browser_use.agent.service import _PythonAgent as BrowserUseAgent
	from browser_use.beta import Agent as BetaAgent

	class RecordingLogger:
		def __init__(self):
			self.infos = []

		def debug(self, message, *args, **kwargs):
			pass

		def info(self, message, *args, **kwargs):
			self.infos.append(message)

		def warning(self, message, *args, **kwargs):
			pass

		def error(self, message, *args, **kwargs):
			pass

	class LLM:
		model = 'gpt-test'
		provider = 'test'

		async def ainvoke(self, messages, output_format=None, **kwargs):
			return type('Result', (), {'usage': None})()

	def make_history(success: bool):
		events = [{'event_type': 'session.done', 'payload': {'result': 'done'}}] if success else []
		return beta_service._history_from_events(
			events,
			model='gpt-test',
			started=1.0,
			finished=2.0,
			output_model_schema=None,
			process_error=None if success else 'failed',
		)

	for index, success in enumerate((True, False)):
		browser_use_logger = RecordingLogger()
		beta_logger = RecordingLogger()
		monkeypatch.setattr(BrowserUseAgent, 'logger', property(lambda self, logger=browser_use_logger: logger))
		monkeypatch.setattr(BetaAgent, 'logger', property(lambda self, logger=beta_logger: logger))

		browser_use_agent = BrowserUseAgent(
			task='Log completion parity.',
			llm=LLM(),
			task_id=f'browsercompletionbu{index}',
			directly_open_url=False,
		)
		beta_agent = BetaAgent(
			task='Log completion parity.',
			llm=LLM(),
			task_id=f'rustcompletionrs{index}',
			directly_open_url=False,
		)
		browser_use_agent.history = make_history(success)
		beta_agent.history = make_history(success)

		await browser_use_agent.log_completion()
		await beta_agent.log_completion()

		assert beta_logger.infos == browser_use_logger.infos


def test_beta_agent_run_sync_delegates_to_async_run(monkeypatch):
	from browser_use.beta import Agent

	agent = Agent(task='start')

	async def fake_run(max_steps=100, on_step_start=None, on_step_end=None):
		agent.kwargs['seen_max_steps'] = max_steps
		return agent.history

	agent.run = fake_run

	assert agent.run_sync(max_steps=7) is agent.history
	assert agent.kwargs['seen_max_steps'] == 7


def test_beta_agent_lifecycle_state_and_save_history(tmp_path):
	from browser_use.beta import Agent
	from browser_use.beta.service import _history_from_events

	agent = Agent(task='start')
	agent.pause()
	assert agent.state.paused is True
	agent.resume()
	assert agent.state.paused is False
	agent.stop()
	assert agent.state.stopped is True

	agent.history = _history_from_events(
		[{'event_type': 'session.done', 'payload': {'result': 'saved answer'}}],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)
	history_file = tmp_path / 'history.json'
	agent.save_history(history_file)

	assert 'saved answer' in history_file.read_text(encoding='utf-8')


def test_beta_agent_control_methods_match_browser_use_user_feedback(monkeypatch, capsys):
	from browser_use.beta import Agent

	class RecordingLogger:
		def __init__(self):
			self.infos = []

		def info(self, message, *args, **kwargs):
			self.infos.append(message)

		def debug(self, message, *args, **kwargs):
			pass

		def warning(self, message, *args, **kwargs):
			pass

		def error(self, message, *args, **kwargs):
			pass

	logger = RecordingLogger()
	monkeypatch.setattr(Agent, 'logger', property(lambda self: logger))
	agent = Agent(task='Control lifecycle feedback.', directly_open_url=False)

	agent.pause()
	pause_output = capsys.readouterr().out

	assert agent.state.paused is True
	assert not agent._external_pause_event.is_set()
	assert 'Paused the agent and left the browser open.' in pause_output
	assert 'Press [Enter] to resume or [Ctrl+C] again to quit.' in pause_output

	agent.resume()
	resume_output = capsys.readouterr().out

	assert agent.state.paused is False
	assert agent._external_pause_event.is_set()
	assert '----------------------------------------------------------------------' in resume_output
	assert 'Resuming agent execution where it left off...' in resume_output

	agent.stop()

	assert agent.state.stopped is True
	assert agent._external_pause_event.is_set()
	assert logger.infos == ['⏹️ Agent stopping']


def test_beta_agent_sync_state_counts_terminal_histories_monotonically():
	from browser_use.beta import Agent
	from browser_use.beta.service import _history_from_events

	def history_from_result(result: str):
		return _history_from_events(
			[{'event_type': 'session.done', 'payload': {'result': result}}],
			model='gpt-test',
			started=1.0,
			finished=2.0,
			output_model_schema=None,
			process_error=None,
		)

	agent = Agent(task='Sync terminal history steps.', llm=type('LLM', (), {'model': 'gpt-test'})())
	starting_steps = agent.state.n_steps

	agent.history = history_from_result('first answer')
	agent._sync_state_from_history()

	assert agent.state.n_steps == starting_steps + 1
	assert agent.state.last_result is not None
	assert agent.state.last_result[-1].extracted_content == 'first answer'

	agent._sync_state_from_history()
	assert agent.state.n_steps == starting_steps + 1

	agent.history = history_from_result('follow-up answer')
	agent._sync_state_from_history()

	assert agent.state.n_steps == starting_steps + 2
	assert agent.state.last_result is not None
	assert agent.state.last_result[-1].extracted_content == 'follow-up answer'


async def test_beta_agent_close_kills_non_keep_alive_browser_session():
	from browser_use.beta import Agent

	class FakeSdk:
		def __init__(self):
			self.calls = []
			self.close_calls = 0

		async def call(self, method, params=None):
			self.calls.append((method, params or {}))
			return {'ok': True}

		async def close(self):
			self.close_calls += 1

	class BrowserProfile:
		keep_alive = False

	class BrowserSession:
		browser_profile = BrowserProfile()

		def __init__(self):
			self.kill_calls = 0

		async def kill(self):
			self.kill_calls += 1

	session = BrowserSession()
	agent = Agent(task='close session', browser_session=session, directly_open_url=False)
	fake_sdk = FakeSdk()
	agent._sdk_client = fake_sdk
	agent._sdk_agent_id = 'agent-1'
	agent._sdk_browser_id = 'browser-1'
	agent.terminal_session_id = 'session-1'

	await agent.close()

	assert fake_sdk.calls == [
		('agent.close', {'agent_id': 'agent-1'}),
		('browser.close', {'browser_id': 'browser-1'}),
	]
	assert fake_sdk.close_calls == 1
	assert agent._sdk_client is None
	assert agent._sdk_agent_id is None
	assert agent._sdk_browser_id is None
	assert agent.terminal_session_id is None
	assert session.kill_calls == 1

	class KeepAliveProfile:
		keep_alive = True

	keep_alive_session = BrowserSession()
	keep_alive_session.browser_profile = KeepAliveProfile()
	keep_alive_agent = Agent(task='keep session', browser_session=keep_alive_session, directly_open_url=False)
	keep_alive_sdk = FakeSdk()
	keep_alive_agent._sdk_client = keep_alive_sdk
	keep_alive_agent._sdk_agent_id = 'agent-keep'
	keep_alive_agent._sdk_browser_id = 'browser-keep'
	keep_alive_agent.terminal_session_id = 'session-keep'

	await keep_alive_agent.close()

	assert keep_alive_sdk.calls == []
	assert keep_alive_sdk.close_calls == 0
	assert keep_alive_agent._sdk_client is keep_alive_sdk
	assert keep_alive_agent._sdk_agent_id == 'agent-keep'
	assert keep_alive_agent._sdk_browser_id == 'browser-keep'
	assert keep_alive_agent.terminal_session_id == 'session-keep'
	assert keep_alive_session.kill_calls == 0


async def test_beta_agent_close_logs_cleanup_errors_without_raising(monkeypatch):
	from browser_use.beta import Agent

	class RecordingLogger:
		def __init__(self):
			self.errors = []

		def error(self, message, *args, **kwargs):
			self.errors.append(message)

	logger = RecordingLogger()
	monkeypatch.setattr(Agent, 'logger', property(lambda self: logger))

	class BrowserProfile:
		keep_alive = False

	class BrowserSession:
		browser_profile = BrowserProfile()

		async def kill(self):
			raise RuntimeError('cleanup failed')

	agent = Agent(task='close failed session', browser_session=BrowserSession(), directly_open_url=False)

	assert await agent.close() is None
	assert logger.errors == ['Error during cleanup: cleanup failed']


async def test_beta_agent_finalize_run_cleanup_closes_sdk_resources():
	from browser_use.beta import Agent

	class FakeSdk:
		def __init__(self):
			self.calls = []
			self.close_calls = 0

		async def call(self, method, params=None):
			self.calls.append((method, params or {}))
			return {'ok': True}

		async def close(self):
			self.close_calls += 1

	class BrowserProfile:
		keep_alive = False

	class BrowserSession:
		browser_profile = BrowserProfile()

		async def kill(self):
			return None

	agent = Agent(task='finalize session', browser_session=BrowserSession(), directly_open_url=False)
	fake_sdk = FakeSdk()
	agent._sdk_client = fake_sdk
	agent._sdk_agent_id = 'agent-finalize'
	agent._sdk_browser_id = 'browser-finalize'
	agent.terminal_session_id = 'session-finalize'

	await agent._finalize_run_cleanup()

	assert fake_sdk.calls == [
		('agent.close', {'agent_id': 'agent-finalize'}),
		('browser.close', {'browser_id': 'browser-finalize'}),
	]
	assert fake_sdk.close_calls == 1
	assert agent._sdk_client is None
	assert agent._sdk_agent_id is None
	assert agent._sdk_browser_id is None
	assert agent.terminal_session_id is None


async def test_beta_agent_check_stop_or_pause_matches_browser_use_lifecycle():
	from browser_use.beta import Agent

	seen = []

	async def should_stop():
		seen.append('should_stop')
		return True

	agent = Agent(task='check controls', register_should_stop_callback=should_stop)

	with pytest.raises(InterruptedError):
		await agent._check_stop_or_pause()

	assert seen == ['should_stop']
	assert agent.state.stopped is True

	paused_agent = Agent(task='check pause')
	paused_agent.pause()

	with pytest.raises(InterruptedError):
		await paused_agent._check_stop_or_pause()

	assert paused_agent.state.paused is True


async def test_beta_agent_rerun_history_delegates_to_rust_run():
	from browser_use.beta import Agent
	from browser_use.beta.service import _history_from_events

	agent = Agent(task='rerun start', max_steps=8)
	previous = _history_from_events(
		[{'event_type': 'session.done', 'payload': {'result': 'previous answer'}}],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)
	seen = []

	async def fake_run(max_steps=100, on_step_start=None, on_step_end=None):
		seen.append(max_steps)
		return _history_from_events(
			[{'event_type': 'session.done', 'payload': {'result': 'rerun answer'}}],
			model='gpt-test',
			started=3.0,
			finished=4.0,
			output_model_schema=None,
			process_error=None,
		)

	agent.run = fake_run

	results = await agent.rerun_history(previous)

	assert seen == [8]
	assert len(results) == 1
	assert results[0].extracted_content == 'rerun answer'


async def test_beta_agent_rerun_history_honors_retry_and_skip_controls(monkeypatch):
	import browser_use.beta.service as beta_service
	from browser_use.agent.views import ActionResult
	from browser_use.beta import Agent
	from browser_use.beta.service import _history_from_events

	previous = _history_from_events(
		[{'event_type': 'session.done', 'payload': {'result': 'previous answer'}}],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)
	success = _history_from_events(
		[{'event_type': 'session.done', 'payload': {'result': 'retry success'}}],
		model='gpt-test',
		started=3.0,
		finished=4.0,
		output_model_schema=None,
		process_error=None,
	)
	sleeps = []

	async def fake_sleep(delay):
		sleeps.append(delay)

	monkeypatch.setattr(beta_service.asyncio, 'sleep', fake_sleep)

	class ErrorHistory:
		def action_results(self):
			return [ActionResult(error='history failed')]

		def errors(self):
			return ['history failed']

	agent = Agent(task='rerun retry', max_steps=5)
	attempts = []

	async def fake_run(max_steps=100, on_step_start=None, on_step_end=None):
		attempts.append(max_steps)
		if len(attempts) == 1:
			raise RuntimeError('process failed')
		if len(attempts) == 2:
			return ErrorHistory()
		return success

	agent.run = fake_run

	results = await agent.rerun_history(previous, max_retries=3, delay_between_actions=0.1)

	assert attempts == [5, 5, 5]
	assert sleeps == [0.1, 0.1]
	assert results[0].extracted_content == 'retry success'

	failing_agent = Agent(task='rerun strict failure', max_steps=2)
	strict_attempts = []
	sleeps.clear()

	async def always_fail(max_steps=100, on_step_start=None, on_step_end=None):
		strict_attempts.append(max_steps)
		raise RuntimeError('still broken')

	failing_agent.run = always_fail

	with pytest.raises(RuntimeError, match='Rerun failed after 2 attempts: still broken'):
		await failing_agent.rerun_history(previous, max_retries=2, skip_failures=False, delay_between_actions=0.25)

	assert strict_attempts == [2, 2]
	assert sleeps == [0.25]

	skip_agent = Agent(task='rerun skipped failure')
	skip_agent.run = always_fail

	results = await skip_agent.rerun_history(previous, max_retries=1, skip_failures=True)

	assert results[-1].error == 'Rerun failed after 1 attempts: still broken'


async def test_beta_agent_load_and_rerun_loads_saved_rust_history(tmp_path):
	from browser_use.beta import Agent
	from browser_use.beta.service import _history_from_events

	agent = Agent(task='rerun saved')
	history = _history_from_events(
		[{'event_type': 'session.done', 'payload': {'result': 'loaded answer'}}],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)
	history_file = tmp_path / 'history.json'
	history.save_to_file(history_file)
	seen = []

	async def fake_rerun_history(loaded_history, **kwargs):
		seen.append((loaded_history.final_result(), kwargs))
		return loaded_history.action_results()

	agent.rerun_history = fake_rerun_history

	results = await agent.load_and_rerun(history_file, max_retries=2)

	assert seen == [('loaded answer', {'max_retries': 2})]
	assert results[0].extracted_content == 'loaded answer'


async def test_beta_agent_take_step_runs_one_terminal_turn():
	from browser_use.beta import Agent
	from browser_use.beta.service import _history_from_events

	agent = Agent(task='step once')
	seen = []

	async def fake_run(max_steps=100, on_step_start=None, on_step_end=None):
		seen.append(max_steps)
		return _history_from_events(
			[{'event_type': 'session.done', 'payload': {'result': 'single step answer'}}],
			model='gpt-test',
			started=1.0,
			finished=2.0,
			output_model_schema=None,
			process_error=None,
		)

	agent.run = fake_run

	is_done, is_valid = await agent.take_step()

	assert seen == [1]
	assert is_done is True
	assert is_valid is True


async def test_beta_agent_take_step_matches_browser_use_non_final_status():
	from browser_use.beta import Agent

	agent = Agent(task='step once without finishing')
	seen = []

	class NonFinalHistory:
		def is_done(self):
			return False

		def has_errors(self):
			return False

	async def fake_run(max_steps=100, on_step_start=None, on_step_end=None):
		seen.append(max_steps)
		return NonFinalHistory()

	agent.run = fake_run

	is_done, is_valid = await agent.take_step()

	assert seen == [1]
	assert is_done is False
	assert is_valid is False


async def test_beta_agent_take_step_executes_initial_actions_on_first_step():
	from browser_use.agent.views import AgentStepInfo
	from browser_use.beta import Agent

	agent = Agent(
		task='step once after initial action',
		initial_actions=[{'navigate': {'url': 'https://example.com', 'new_tab': False}}],
	)
	seen = []

	class DoneHistory:
		def is_done(self):
			return True

	async def fake_execute_initial_actions():
		seen.append('initial_actions')

	async def fake_run(max_steps=100, on_step_start=None, on_step_end=None):
		seen.append(('run', max_steps))
		return DoneHistory()

	agent._execute_initial_actions = fake_execute_initial_actions
	agent.run = fake_run

	is_done, is_valid = await agent.take_step(AgentStepInfo(step_number=0, max_steps=3))

	assert seen == ['initial_actions', ('run', 1)]
	assert is_done is True
	assert is_valid is True

	seen.clear()

	async def fake_interrupted_initial_actions():
		seen.append('interrupted_initial_actions')
		raise InterruptedError

	agent._execute_initial_actions = fake_interrupted_initial_actions

	is_done, is_valid = await agent.take_step(AgentStepInfo(step_number=0, max_steps=3))

	assert seen == ['interrupted_initial_actions', ('run', 1)]
	assert is_done is True
	assert is_valid is True


async def test_beta_agent_run_executes_initial_actions_before_sdk():
	from browser_use.beta import Agent
	from browser_use.beta.service import _history_from_events

	agent = Agent(
		task='start on example',
		initial_actions=[{'navigate': {'url': 'https://example.com', 'new_tab': False}}],
	)
	seen = []

	async def fake_execute_initial_actions(*, allow_terminal_run=True):
		seen.append(('initial_actions', allow_terminal_run))

	async def fake_run_sdk_agent(**kwargs):
		seen.append(('sdk', kwargs['max_steps']))
		return _history_from_events(
			[{'event_type': 'session.done', 'payload': {'result': 'done'}}],
			model='gpt-test',
			started=1.0,
			finished=2.0,
			output_model_schema=None,
			process_error=None,
		)

	agent._execute_initial_actions = fake_execute_initial_actions
	agent._run_sdk_agent = fake_run_sdk_agent
	agent._initialize_run_lifecycle_state = lambda: None

	history = await agent.run(max_steps=3)

	assert seen == [('initial_actions', False), ('sdk', 3)]
	assert history.final_result() == 'done'


async def test_beta_agent_run_pre_navigates_cdp_session_before_sdk_by_default():
	from types import SimpleNamespace

	from browser_use.beta import Agent
	from browser_use.beta.service import _history_from_events

	class FakeBrowserSession:
		id = 'browser-cdp'
		cdp_url = 'wss://cloud-browser.example/devtools/browser/session'
		browser_profile = SimpleNamespace(cdp_url=cdp_url)

		def __init__(self):
			self.calls = []

		async def navigate_to(self, url, new_tab=False):
			self.calls.append((url, new_tab))

		async def get_browser_state_summary(self, include_screenshot=False):
			assert include_screenshot is False
			return SimpleNamespace(url='https://example.com/start', title='Example Start', tabs=[])

	browser_session = FakeBrowserSession()
	agent = Agent(
		task='read the page',
		browser_session=browser_session,
		initial_actions=[{'navigate': {'url': 'https://example.com', 'new_tab': False}}],
	)
	seen = []

	async def fake_run_sdk_agent(**kwargs):
		seen.append(kwargs['task'])
		return _history_from_events(
			[{'event_type': 'session.done', 'payload': {'result': 'done'}}],
			model='gpt-test',
			started=1.0,
			finished=2.0,
			output_model_schema=None,
			process_error=None,
		)

	agent._run_sdk_agent = fake_run_sdk_agent
	agent._initialize_run_lifecycle_state = lambda: None

	history = await agent.run(max_steps=3)

	assert history.final_result() == 'done'
	assert browser_session.calls == [('https://example.com', False)]
	assert agent._completed_initial_navigation_urls == ['https://example.com']
	assert seen[0].startswith("The browser session is already open at 'https://example.com'")
	assert "current_url='https://example.com/start'" in seen[0]
	assert "title='Example Start'" in seen[0]
	assert 'first browser step should inspect or extract from the current page' in seen[0]
	assert "First navigate to 'https://example.com'" not in seen[0]


async def test_beta_agent_run_keeps_initial_navigation_when_direct_state_mismatches():
	from types import SimpleNamespace

	from browser_use.beta import Agent
	from browser_use.beta.service import _history_from_events

	class FakeBrowserSession:
		id = 'browser-cdp'
		cdp_url = 'wss://cloud-browser.example/devtools/browser/session'
		browser_profile = SimpleNamespace(cdp_url=cdp_url)

		def __init__(self):
			self.calls = []

		async def navigate_to(self, url, new_tab=False):
			self.calls.append((url, new_tab))

		async def get_browser_state_summary(self, include_screenshot=False):
			assert include_screenshot is False
			return SimpleNamespace(url='about:blank', title='', tabs=[])

	browser_session = FakeBrowserSession()
	agent = Agent(
		task='read the page',
		browser_session=browser_session,
		initial_actions=[{'navigate': {'url': 'https://example.com/start', 'new_tab': False}}],
	)
	seen = []

	async def fake_run_sdk_agent(**kwargs):
		seen.append(kwargs['task'])
		return _history_from_events(
			[{'event_type': 'session.done', 'payload': {'result': 'done'}}],
			model='gpt-test',
			started=1.0,
			finished=2.0,
			output_model_schema=None,
			process_error=None,
		)

	agent._run_sdk_agent = fake_run_sdk_agent
	agent._initialize_run_lifecycle_state = lambda: None

	history = await agent.run(max_steps=3)

	assert history.final_result() == 'done'
	assert browser_session.calls == [('https://example.com/start', False)]
	assert agent._completed_initial_navigation_urls == []
	assert seen[0].startswith("First navigate to 'https://example.com/start'")
	assert 'The browser session is already open at' not in seen[0]


def test_rust_history_uses_browser_script_lifecycle_outputs_as_result():
	from browser_use.beta.service import _history_from_events

	history = _history_from_events(
		[
			{'event_type': 'model.turn.request', 'payload': {}},
			{
				'event_type': 'tool.started',
				'payload': {
					'name': 'browser_script',
					'tool_call_id': 'call-browser',
					'arguments': {'code': 'emit_output(page_info(), label="page_info")'},
				},
			},
			{
				'event_type': 'browser_script.completed',
				'payload': {
					'name': 'browser_script',
					'ok': True,
					'status': 'finished',
					'run_id': 'bs-test',
					'outputs': [
						{
							'label': 'page_info',
							'value': {'url': 'https://example.com', 'title': 'Example'},
							'summary': {'kind': 'observed', 'output_label': 'page_info'},
						}
					],
				},
			},
			{'event_type': 'model.turn.request', 'payload': {}},
			{'event_type': 'session.done', 'payload': {'result': 'done'}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	result = history.history[0].result[0]
	assert result.extracted_content is not None
	assert json.loads(result.extracted_content) == [
		{
			'label': 'page_info',
			'value': {'url': 'https://example.com', 'title': 'Example'},
			'summary': {'kind': 'observed', 'output_label': 'page_info'},
		}
	]
	assert history.history[0].state.url == 'https://example.com'


def test_rust_history_uses_printed_browser_script_page_info_as_state():
	from browser_use.beta.service import _history_from_events

	history = _history_from_events(
		[
			{'event_type': 'model.turn.request', 'payload': {}},
			{
				'event_type': 'tool.started',
				'payload': {
					'name': 'browser_script',
					'tool_call_id': 'call-browser',
					'arguments': {'code': 'info = page_info()\nprint(info)'},
				},
			},
			{
				'event_type': 'browser_script.completed',
				'payload': {
					'name': 'browser_script',
					'tool_call_id': 'call-browser',
					'ok': True,
					'status': 'finished',
					'text': (
						"{'url': 'https://example.com/', 'title': 'Example Domain', "
						"'target': {'targetId': 'target-1', 'url': 'https://example.com/', 'title': 'Example Domain'}}"
					),
				},
			},
			{'event_type': 'model.turn.request', 'payload': {}},
			{'event_type': 'session.done', 'payload': {'result': 'done'}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	state = history.history[0].state
	assert state.url == 'https://example.com/'
	assert state.title == 'Example Domain'
	assert state.tabs[0].target_id == 'target-1'


async def test_beta_agent_multi_act_preserves_done_action():
	from browser_use.beta import Agent

	agent = Agent(task='finish manually')

	results = await agent.multi_act([{'done': {'text': 'manual answer', 'success': False, 'files_to_display': ['report.txt']}}])

	assert len(results) == 1
	assert results[0].is_done is True
	assert results[0].success is False
	assert results[0].extracted_content == 'manual answer'
	assert results[0].attachments == ['report.txt']


async def test_beta_agent_multi_act_routes_actions_to_followup():
	from browser_use.beta import Agent
	from browser_use.beta.service import _history_from_events

	agent = Agent(task='act on current page')
	agent.terminal_session_id = '12345678-1234-1234-1234-123456789abc'
	seen = []

	async def fake_follow_up(task, max_steps=None):
		seen.append((task, max_steps))
		return _history_from_events(
			[{'event_type': 'session.done', 'payload': {'result': 'actions applied'}}],
			model='gpt-test',
			started=1.0,
			finished=2.0,
			output_model_schema=None,
			process_error=None,
		)

	agent.follow_up = fake_follow_up

	results = await agent.multi_act(
		[
			{'click_element': {'index': 2}},
			{'input_text': {'index': 3, 'text': 'hello'}},
		]
	)

	assert seen[0][1] == 2
	assert 'Browser Use action models' in seen[0][0]
	assert '"click_element"' in seen[0][0]
	assert '"input_text"' in seen[0][0]
	assert results[0].extracted_content == 'actions applied'


async def test_beta_agent_multi_act_ignores_later_done_actions():
	from browser_use.beta import Agent
	from browser_use.beta.service import _history_from_events

	agent = Agent(task='act without premature done')
	agent.terminal_session_id = '12345678-1234-1234-1234-123456789abc'
	seen = []

	async def fake_follow_up(task, max_steps=None):
		seen.append((task, max_steps))
		return _history_from_events(
			[{'event_type': 'session.done', 'payload': {'result': 'clicked only'}}],
			model='gpt-test',
			started=1.0,
			finished=2.0,
			output_model_schema=None,
			process_error=None,
		)

	agent.follow_up = fake_follow_up

	results = await agent.multi_act(
		[
			{'click_element': {'index': 2}},
			{'done': {'text': 'should not execute', 'success': True}},
			{'input_text': {'index': 3, 'text': 'should not execute'}},
		]
	)

	assert seen[0][1] == 1
	assert '"click_element"' in seen[0][0]
	assert '"done"' not in seen[0][0]
	assert 'should not execute' not in seen[0][0]
	assert '"input_text"' not in seen[0][0]
	assert results[0].extracted_content == 'clicked only'


async def test_beta_agent_initial_actions_can_pre_navigate_existing_cdp_session(monkeypatch):
	from types import SimpleNamespace

	from browser_use.beta import Agent

	class FakeBrowserSession:
		id = 'browser-cdp'
		cdp_url = 'wss://cloud-browser.example/devtools/browser/session'
		browser_profile = SimpleNamespace(cdp_url=cdp_url)

		def __init__(self):
			self.calls = []

		async def navigate_to(self, url, new_tab=False):
			self.calls.append((url, new_tab))

		async def get_browser_state_summary(self, include_screenshot=False):
			assert include_screenshot is False
			return SimpleNamespace(url='https://example.com', title='Example Domain', tabs=[])

	browser_session = FakeBrowserSession()
	agent = Agent(
		task='read the page',
		browser_session=browser_session,
		initial_actions=[{'navigate': {'url': 'https://example.com', 'new_tab': False}}],
	)

	monkeypatch.setenv('BROWSER_USE_RUST_DIRECT_INITIAL_NAVIGATION', '1')
	await agent._execute_initial_actions(allow_terminal_run=False)

	assert browser_session.calls == [('https://example.com', False)]
	assert agent._initial_actions_executed is True
	assert agent._completed_initial_navigation_urls == ['https://example.com']
	assert (
		agent.state.last_result[0].extracted_content
		== 'Navigated to https://example.com. Current page: https://example.com (Example Domain)'
	)
	assert agent.history.history[0].metadata.step_number == 0
	assert agent.history.history[0].model_output.action == agent.initial_actions


async def test_beta_agent_direct_initial_navigation_defaults_on_for_cdp(monkeypatch):
	from types import SimpleNamespace

	from browser_use.beta import Agent

	class FakeBrowserSession:
		id = 'browser-cdp'
		cdp_url = 'wss://cloud-browser.example/devtools/browser/session'
		browser_profile = SimpleNamespace(cdp_url=cdp_url)

		def __init__(self):
			self.calls = []

		async def navigate_to(self, url, new_tab=False):
			self.calls.append((url, new_tab))

		async def get_browser_state_summary(self, include_screenshot=False):
			assert include_screenshot is False
			return SimpleNamespace(url='https://example.com', title='Example Domain', tabs=[])

	browser_session = FakeBrowserSession()
	agent = Agent(
		task='read the page',
		browser_session=browser_session,
		initial_actions=[{'navigate': {'url': 'https://example.com', 'new_tab': False}}],
	)

	monkeypatch.delenv('BROWSER_USE_RUST_DIRECT_INITIAL_NAVIGATION', raising=False)
	await agent._execute_initial_actions(allow_terminal_run=False)

	assert browser_session.calls == [('https://example.com', False)]
	assert agent._initial_actions_executed is True
	assert agent._completed_initial_navigation_urls == ['https://example.com']
	assert (
		agent.state.last_result[0].extracted_content
		== 'Navigated to https://example.com. Current page: https://example.com (Example Domain)'
	)


async def test_beta_agent_direct_initial_navigation_can_be_disabled(monkeypatch):
	from types import SimpleNamespace

	from browser_use.beta import Agent

	class FakeBrowserSession:
		id = 'browser-cdp'
		cdp_url = 'wss://cloud-browser.example/devtools/browser/session'
		browser_profile = SimpleNamespace(cdp_url=cdp_url)

		def __init__(self):
			self.calls = []

		async def navigate_to(self, url, new_tab=False):
			self.calls.append((url, new_tab))

	browser_session = FakeBrowserSession()
	agent = Agent(
		task='read the page',
		browser_session=browser_session,
		initial_actions=[{'navigate': {'url': 'https://example.com', 'new_tab': False}}],
	)

	monkeypatch.setenv('BROWSER_USE_RUST_DIRECT_INITIAL_NAVIGATION', '0')
	await agent._execute_initial_actions(allow_terminal_run=False)

	assert browser_session.calls == []
	assert agent._initial_actions_executed is False
	assert agent.history.history == []


async def test_beta_agent_records_initial_actions_in_history(monkeypatch):
	from browser_use.agent.views import ActionResult
	from browser_use.beta import Agent

	class RecordingLogger:
		def __init__(self):
			self.debugs = []

		def debug(self, message, *args, **kwargs):
			self.debugs.append(message)

		def info(self, message, *args, **kwargs):
			pass

	logger = RecordingLogger()
	monkeypatch.setattr(Agent, 'logger', property(lambda self: logger))

	class BrowserProfile:
		downloads_path = None

	class BrowserSession:
		browser_profile = BrowserProfile()

	agent = Agent(
		task='Replay actions.',
		browser_session=BrowserSession(),
		initial_actions=[{'navigate': {'url': 'https://example.com', 'new_tab': False}}],
	)
	agent.initial_url = 'https://example.com'
	initial_calls = []

	async def fake_initial_multi_act(actions):
		initial_calls.append(actions)
		return [ActionResult(long_term_memory='loaded')]

	agent.multi_act = fake_initial_multi_act
	await agent._execute_initial_actions()

	assert initial_calls == [agent.initial_actions]
	assert agent.state.last_result[0].long_term_memory == 'Found initial url and automatically loaded it. loaded'
	assert agent.history.history[0].metadata.step_number == 0
	assert agent.history.history[0].state.url == 'https://example.com'
	assert agent.history.history[0].model_output.action == agent.initial_actions
	assert logger.debugs == [
		'⚡ Executing 1 initial actions...',
		'📝 Saved initial actions to history as step 0',
		'Initial actions completed',
	]


async def test_beta_agent_exposes_model_output_helper_methods(monkeypatch, tmp_path):
	from types import SimpleNamespace

	from browser_use.agent.views import ActionResult
	from browser_use.beta import Agent
	from browser_use.llm.messages import UserMessage

	class RecordingLogger:
		def __init__(self):
			self.debugs = []
			self.warnings = []

		def debug(self, message, *args, **kwargs):
			self.debugs.append(message)

		def warning(self, message, *args, **kwargs):
			self.warnings.append(message)

		def info(self, message, *args, **kwargs):
			pass

		def isEnabledFor(self, level):
			return True

	logger = RecordingLogger()
	monkeypatch.setattr(Agent, 'logger', property(lambda self: logger))

	original_url = 'https://example.com/path?abcdefghijklmnopqrstuvwxyz#section'

	class LLM:
		model = 'gpt-test'
		provider = 'test-provider'

		def __init__(self):
			self.agent = None
			self.calls = []

		async def ainvoke(self, messages, output_format=None, **kwargs):
			self.calls.append((messages, output_format))
			shortened_text = messages[0].content
			return SimpleNamespace(
				usage=None,
				completion=self.agent.AgentOutput(
					evaluation_previous_goal='ok',
					memory='remember',
					next_goal='finish',
					action=[
						self.agent.ActionModel(done={'text': shortened_text, 'success': True}),
						self.agent.ActionModel(done={'text': 'extra action', 'success': True}),
					],
				),
			)

	seen_callbacks = []

	async def new_step_callback(browser_state, model_output, step_number):
		seen_callbacks.append((browser_state, model_output, step_number))

	llm = LLM()
	agent = Agent(
		task='Use LLM helpers.',
		llm=llm,
		max_actions_per_step=1,
		_url_shortening_limit=8,
		save_conversation_path=tmp_path / 'conversations',
		register_new_step_callback=new_step_callback,
	)
	llm.agent = agent
	input_messages = [UserMessage(content=f'Open {original_url} now.')]
	browser_state = SimpleNamespace(url='https://example.com')
	agent._message_manager.get_messages = lambda: input_messages

	await agent._get_next_action(browser_state)

	assert llm.calls[0][1] is agent.AgentOutput
	assert original_url not in llm.calls[0][0][0].content
	assert len(agent.state.last_model_output.action) == 1
	assert agent.state.last_model_output.action[0].model_dump(exclude_unset=True)['done']['text'] == f'Open {original_url} now.'
	assert seen_callbacks == [(browser_state, agent.state.last_model_output, agent.state.n_steps)]
	assert list((tmp_path / 'conversations').glob(f'conversation_{agent.id}_{agent.state.n_steps}.txt'))

	seen_actions = []

	async def fake_multi_act(actions):
		seen_actions.append(actions)
		return [ActionResult(extracted_content='executed')]

	agent.multi_act = fake_multi_act
	await agent._execute_actions()

	assert seen_actions == [agent.state.last_model_output.action]
	assert agent.state.last_result[0].extracted_content == 'executed'

	class RetryLLM(LLM):
		async def ainvoke(self, messages, output_format=None, **kwargs):
			self.calls.append((messages, output_format))
			if len(self.calls) == 1:
				return SimpleNamespace(
					usage=None,
					completion=self.agent.AgentOutput(
						evaluation_previous_goal='empty',
						memory='none',
						next_goal='retry',
						action=[],
					),
				)
			return SimpleNamespace(
				usage=None,
				completion=self.agent.AgentOutput(
					evaluation_previous_goal='ok',
					memory='remember',
					next_goal='finish',
					action=[self.agent.ActionModel(done={'text': 'retried action', 'success': True})],
				),
			)

	retry_llm = RetryLLM()
	retry_agent = Agent(task='Retry LLM helpers.', llm=retry_llm)
	retry_llm.agent = retry_agent
	logger.debugs.clear()
	logger.warnings.clear()
	retry_output = await retry_agent._get_model_output_with_retry([UserMessage(content='Retry with an action.')])

	assert len(retry_llm.calls) == 2
	assert retry_output.action
	assert logger.debugs[0] == '✅ Step 1: Got LLM response with 0 actions'
	assert any('Next actions: done' in message for message in logger.debugs)
	assert logger.warnings == ['Model returned empty action. Retrying...']

	class EmptyRetryLLM(LLM):
		async def ainvoke(self, messages, output_format=None, **kwargs):
			self.calls.append((messages, output_format))
			return SimpleNamespace(
				usage=None,
				completion=self.agent.AgentOutput(
					evaluation_previous_goal='empty',
					memory='none',
					next_goal='retry',
					action=[],
				),
			)

	empty_retry_llm = EmptyRetryLLM()
	empty_retry_agent = Agent(task='Retry empty LLM helpers.', llm=empty_retry_llm)
	empty_retry_llm.agent = empty_retry_agent
	logger.debugs.clear()
	logger.warnings.clear()
	empty_retry_output = await empty_retry_agent._get_model_output_with_retry([UserMessage(content='Retry empty action.')])

	assert len(empty_retry_llm.calls) == 2
	assert empty_retry_output.action[0].model_dump(exclude_unset=True)['done']['text'] == 'No next action returned by LLM!'
	assert logger.debugs == ['✅ Step 1: Got LLM response with 0 actions']
	assert logger.warnings == [
		'Model returned empty action. Retrying...',
		'Model still returned empty after retry. Inserting safe noop action.',
	]


async def test_beta_agent_get_model_output_logs_response_like_browser_use(monkeypatch):
	from browser_use.agent.service import _PythonAgent as BrowserUseAgent
	from browser_use.beta import Agent as BetaAgent
	from browser_use.llm.messages import UserMessage

	class RecordingLogger:
		def __init__(self):
			self.debugs = []
			self.infos = []

		def debug(self, message, *args, **kwargs):
			self.debugs.append(message)

		def info(self, message, *args, **kwargs):
			self.infos.append(message)

		def warning(self, message, *args, **kwargs):
			pass

		def isEnabledFor(self, level):
			return False

	class LLM:
		model = 'gpt-test'
		provider = 'test-provider'

		def __init__(self):
			self.agent = None

		async def ainvoke(self, messages, output_format=None, **kwargs):
			return type(
				'Result',
				(),
				{
					'usage': None,
					'completion': self.agent.AgentOutput(
						evaluation_previous_goal='neutral',
						memory='remember response logging',
						next_goal='finish response logging',
						action=[self.agent.ActionModel(done={'text': 'logged', 'success': True})],
					),
				},
			)()

	browser_use_logger = RecordingLogger()
	beta_logger = RecordingLogger()
	monkeypatch.setattr(BrowserUseAgent, 'logger', property(lambda self: browser_use_logger))
	monkeypatch.setattr(BetaAgent, 'logger', property(lambda self: beta_logger))

	browser_use_llm = LLM()
	browser_use_agent = BrowserUseAgent(task='Log the model output.', llm=browser_use_llm, directly_open_url=False)
	browser_use_llm.agent = browser_use_agent
	await browser_use_agent.get_model_output([UserMessage(content='log response')])

	beta_llm = LLM()
	beta_agent = BetaAgent(task='Log the model output.', llm=beta_llm, directly_open_url=False)
	beta_llm.agent = beta_agent
	await beta_agent.get_model_output([UserMessage(content='log response')])

	assert beta_logger.infos == browser_use_logger.infos
	assert any('Eval: neutral' in message for message in beta_logger.infos)
	assert any('Memory: remember response logging' in message for message in beta_logger.infos)
	assert any('Next goal: finish response logging' in message for message in beta_logger.infos)


async def test_beta_agent_exposes_prepare_context_helper_method(monkeypatch):
	from types import SimpleNamespace

	from browser_use.agent.views import AgentStepInfo
	from browser_use.beta import Agent

	state_requests = []
	browser_state = SimpleNamespace(
		url='https://example.com/settings',
		title='Settings',
		screenshot='base64-screen',
		dom_state=SimpleNamespace(selector_map={1: object(), 2: object()}),
	)

	class BrowserProfile:
		downloads_path = None

	class BrowserSession:
		browser_profile = BrowserProfile()

		async def get_browser_state_summary(self, include_screenshot=False, include_recent_events=False):
			state_requests.append((include_screenshot, include_recent_events))
			return browser_state

	agent = Agent(
		task='Prepare context.',
		browser_session=BrowserSession(),
		include_recent_events=True,
		use_vision=False,
		available_file_paths=['/tmp/input.txt'],
		sensitive_data={'api_key': 'secret-value'},
	)
	download_contexts = []
	updated_pages = []
	prompt_urls = []
	created_messages = []

	async def fake_check_downloads(context=''):
		download_contexts.append(context)

	async def fake_update_action_models(page_url):
		updated_pages.append(page_url)

	def fake_prompt_description(page_url):
		prompt_urls.append(page_url)
		return 'filtered action prompt'

	def fake_create_state_messages(**kwargs):
		created_messages.append(kwargs)

	monkeypatch.setattr(agent, '_check_and_update_downloads', fake_check_downloads)
	monkeypatch.setattr(agent, '_update_action_models_for_page', fake_update_action_models)
	monkeypatch.setattr(agent.tools.registry, 'get_prompt_description', fake_prompt_description)
	monkeypatch.setattr(agent._message_manager, 'create_state_messages', fake_create_state_messages)

	step_info = AgentStepInfo(step_number=2, max_steps=3)
	result = await agent._prepare_context(step_info)

	assert result is browser_state
	assert state_requests == [(True, True)]
	assert download_contexts == ['Step 1: after getting browser state']
	assert updated_pages == ['https://example.com/settings']
	assert prompt_urls == ['https://example.com/settings']
	assert created_messages == [
		{
			'browser_state_summary': browser_state,
			'model_output': agent.state.last_model_output,
			'result': agent.state.last_result,
			'step_info': step_info,
			'use_vision': True,
			'page_filtered_actions': 'filtered action prompt',
			'sensitive_data': {'api_key': 'secret-value'},
			'available_file_paths': ['/tmp/input.txt'],
		}
	]
	assert agent.AgentOutput is agent.DoneAgentOutput


async def test_beta_agent_trace_and_cloud_auth_helpers():
	from browser_use.beta import Agent
	from browser_use.beta.service import _history_from_events

	agent = Agent(task='Open example.com', llm=type('LLM', (), {'model': 'gpt-test'})(), task_id='task-1')
	agent.history = _history_from_events(
		[
			{'event_type': 'browser.state', 'payload': {'url': 'https://example.com', 'title': 'Example'}},
			{'event_type': 'session.done', 'payload': {'result': 'trace answer'}},
		],
		model='gpt-test',
		started=1.0,
		finished=3.0,
		output_model_schema=None,
		process_error=None,
	)

	trace_object = agent.get_trace_object()

	assert await agent.authenticate_cloud_sync() is False
	assert set(trace_object) == {'trace', 'trace_details'}
	assert trace_object['trace']['model'] == 'gpt-test'
	assert trace_object['trace']['task_id'] == 'task-1'
	assert trace_object['trace']['final_result_response_truncated'] == 'trace answer'
	assert trace_object['trace']['self_report_completed'] == 1
	assert trace_object['trace_details']['final_result_response'] == 'trace answer'
	assert 'trace answer' in trace_object['trace_details']['complete_history']


async def test_beta_agent_run_exposes_laminar_trace_id_for_eval_links(monkeypatch):
	import browser_use.beta.service as beta_service
	from browser_use.beta import Agent

	class FakeLaminar:
		@staticmethod
		def is_initialized():
			return True

		@staticmethod
		def get_trace_id():
			return '01234567-89ab-cdef-0123-456789abcdef'

	async def fake_run_terminal(self, max_steps, on_step_start, on_step_end):
		return self.history

	monkeypatch.setattr(beta_service, 'Laminar', FakeLaminar)
	monkeypatch.setattr(beta_service.Agent, '_run_terminal', fake_run_terminal)

	agent = Agent(task='Trace link task.', llm=type('LLM', (), {'model': 'claude-sonnet-4-6'})())

	await agent.run(max_steps=3)

	assert agent.laminar_trace_id == '01234567-89ab-cdef-0123-456789abcdef'


def test_rust_laminar_replay_flush_avoids_context_reset(monkeypatch):
	import browser_use.beta.service as beta_service

	class FakeLaminar:
		flushes = 0
		force_flushes = 0

		@staticmethod
		def is_initialized():
			return True

		@classmethod
		def flush(cls):
			cls.flushes += 1

		@classmethod
		def force_flush(cls):
			cls.force_flushes += 1

	monkeypatch.setattr(beta_service, 'Laminar', FakeLaminar)

	beta_service._laminar_force_flush()

	assert FakeLaminar.flushes == 1
	assert FakeLaminar.force_flushes == 0


def test_beta_agent_laminar_run_summary_populates_current_span(monkeypatch):
	import browser_use.beta.service as beta_service
	from browser_use.beta import Agent
	from browser_use.beta.service import _history_from_events

	class FakeLaminar:
		attributes = []
		outputs = []
		events = []
		spans = []
		flushes = 0
		current_span = None

		@staticmethod
		def is_initialized():
			return True

		@classmethod
		def set_span_attributes(cls, attributes):
			if cls.current_span is not None:
				cls.current_span['attributes'].append(attributes)
			else:
				cls.attributes.append(attributes)

		@classmethod
		def set_span_output(cls, output):
			if cls.current_span is not None:
				cls.current_span['outputs'].append(output)
			else:
				cls.outputs.append(output)

		@classmethod
		def event(cls, name, attributes=None):
			cls.events.append((name, attributes))

		@classmethod
		def flush(cls):
			cls.flushes += 1

		@classmethod
		def start_as_current_span(cls, name, input=None, span_type='DEFAULT'):
			record = {'name': name, 'input': input, 'span_type': span_type, 'attributes': [], 'outputs': []}

			class Span:
				def __enter__(self):
					cls.current_span = record
					cls.spans.append(record)
					return self

				def __exit__(self, exc_type, exc, tb):
					cls.current_span = None
					return False

			return Span()

	monkeypatch.setattr(beta_service, 'Laminar', FakeLaminar)

	agent = Agent(task='Trace terminal observability.', llm=type('LLM', (), {'model': 'claude-sonnet-4-6'})())
	agent.terminal_session_id = 'terminal-session-1'
	agent.last_events = [
		{
			'event_type': 'model.turn.request',
			'ts_ms': 1000,
			'payload': {
				'model': 'claude-sonnet-4-6',
				'provider': 'test-provider',
				'turn_idx': 0,
				'composition': {
					'system_prompt_tokens': 100,
					'tools': [{'name': 'browser'}, {'name': 'done'}],
				},
				'llm_input': {
					'system': [{'text': 'System prompt'}],
					'tools': [
						{
							'name': 'browser_script',
							'description': 'Run browser Python. Use click_at_xy(x, y) to click visible page coordinates.',
							'input_schema': {
								'type': 'object',
								'properties': {'code': {'type': 'string'}},
								'required': ['code'],
							},
						}
					],
					'messages': [
						{
							'role': 'user',
							'content': [
								{'type': 'text', 'text': 'Find the title on example.com'},
								{
									'type': 'media',
									'mime_type': 'image/png',
									'data': 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB',
									'detail': 'low',
								},
							],
						}
					],
					'message_count': 1,
					'omitted_earlier_messages': 0,
				},
			},
		},
		{
			'event_type': 'tool.started',
			'ts_ms': 1200,
			'payload': {
				'name': 'browser_script',
				'tool_call_id': 'call-browser',
				'arguments': {'code': 'emit_output(page_info(), label="page_info")'},
			},
		},
		{
			'event_type': 'tool.output',
			'ts_ms': 1400,
			'payload': {
				'name': 'browser_script',
				'tool_call_id': 'call-browser',
				'ok': True,
				'text': '',
				'summary': [{'kind': 'page', 'title': 'Example Domain', 'url': 'https://example.com'}],
				'outputs': [{'label': 'page_info', 'value': {'title': 'Example Domain'}}],
				'content': [
					{'type': 'input_text', 'text': 'Example Domain page info'},
					{'type': 'input_image', 'image_url': 'data:image/png;base64,iVBORw0KGgo=', 'detail': 'low'},
				],
			},
		},
		{'event_type': 'model.stream_delta', 'ts_ms': 1500, 'payload': {'text': 'laminar answer'}},
		{
			'event_type': 'token_count',
			'ts_ms': 2000,
			'payload': {
				'info': {
					'last_token_usage': {
						'cached_input_tokens': 5,
						'input_cache_creation_tokens': 13,
						'input_tokens': 100,
						'output_tokens': 20,
						'total_tokens': 133,
					},
					'total_token_usage': {
						'cached_input_tokens': 5,
						'input_cache_creation_tokens': 13,
						'input_tokens': 100,
						'output_tokens': 20,
						'total_tokens': 133,
					},
				},
			},
		},
		{'event_type': 'session.done', 'payload': {'result': 'laminar answer'}},
	]
	agent.history = _history_from_events(
		agent.last_events,
		model='claude-sonnet-4-6',
		started=1.0,
		finished=4.0,
		output_model_schema=None,
		process_error=None,
	)

	agent._record_laminar_run_observability(max_steps=7, duration_seconds=3.0)

	assert FakeLaminar.attributes[-1]['runtime'] == 'browser_use.beta'
	assert FakeLaminar.attributes[-1]['terminal_session_id'] == 'terminal-session-1'
	assert FakeLaminar.outputs[-1]['final_result_preview'] == 'laminar answer'
	assert FakeLaminar.outputs[-1]['steps'] == agent.history.number_of_steps()
	assert FakeLaminar.outputs[-1]['terminal_events_count'] == 6
	assert FakeLaminar.events[-1][0] == 'agent.run.terminal_summary'
	assert FakeLaminar.spans[0]['name'] == 'rust_core.llm'
	assert FakeLaminar.spans[0]['span_type'] == 'LLM'
	llm_input = FakeLaminar.spans[0]['input']
	assert isinstance(llm_input, list)
	assert llm_input[0]['role'] == 'system'
	assert llm_input[0]['content'][0]['text'] == 'System prompt'
	assert llm_input[1]['content'][0]['text'] == 'Find the title on example.com'
	assert llm_input[1]['content'][1] == {
		'type': 'image_url',
		'image_url': {
			'url': 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB',
			'detail': 'low',
		},
	}
	span_attrs = {}
	for attributes in FakeLaminar.spans[0]['attributes']:
		span_attrs.update(attributes)
	assert span_attrs['tools_count'] == 1
	assert 'browser_script' in span_attrs['tool_names']
	assert span_attrs['input_tokens'] == 100
	assert span_attrs['cached_input_tokens'] == 5
	assert span_attrs['cache_creation_input_tokens'] == 13
	assert span_attrs['output_tokens'] == 20
	assert span_attrs['total_tokens'] == 133
	assert span_attrs['input_cached_cost_usd'] == 5 * (0.30 / 1_000_000)
	assert span_attrs['input_cache_creation_cost_usd'] == 13 * (3.75 / 1_000_000)
	assert span_attrs['gen_ai.operation.name'] == 'chat'
	assert span_attrs['gen_ai.request.model'] == 'claude-sonnet-4-6'
	assert span_attrs['gen_ai.prompt.0.role'] == 'system'
	assert span_attrs['gen_ai.prompt.0.content'] == 'System prompt'
	assert span_attrs['gen_ai.prompt.1.role'] == 'user'
	assert span_attrs['gen_ai.prompt.1.content'] == 'Find the title on example.com\n[image]'
	assert span_attrs['gen_ai.completion.0.role'] == 'assistant'
	assert span_attrs['gen_ai.completion.0.content'] == 'laminar answer'
	assert span_attrs['gen_ai.usage.input_tokens'] == 100
	assert span_attrs['gen_ai.usage.input_cached_tokens'] == 5
	assert span_attrs['gen_ai.usage.cache_creation_input_tokens'] == 13
	assert span_attrs['gen_ai.usage.output_tokens'] == 20
	assert span_attrs['gen_ai.usage.total_tokens'] == 133
	assert span_attrs['llm.request.functions.0.name'] == 'browser_script'
	assert 'click_at_xy' in span_attrs['llm.request.functions.0.description']
	assert '"code"' in span_attrs['llm.request.functions.0.input_schema']
	assert span_attrs['gen_ai.request.tools.0.name'] == 'browser_script'
	assert 'click_at_xy' in span_attrs['gen_ai.request.tools.0.description']
	assert '"browser_script"' in span_attrs['gen_ai.tool.definitions']
	assert 'click_at_xy' in span_attrs['gen_ai.tool.definitions']
	assert '"browser_script"' in span_attrs['gen_ai.request.tools']
	assert '"System prompt"' in span_attrs['gen_ai.input.messages']
	assert '[image in span input]' in span_attrs['gen_ai.input.messages']
	assert 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB' not in span_attrs['gen_ai.input.messages']
	assert '"laminar answer"' in span_attrs['gen_ai.output.messages']
	assert span_attrs['assistant_output_preview'] == 'laminar answer'
	assert FakeLaminar.spans[0]['outputs'][-1][0]['content'][0]['text'] == 'laminar answer'
	assert FakeLaminar.spans[1]['name'] == 'rust_core.tool.browser_script'
	assert FakeLaminar.spans[1]['span_type'] == 'TOOL'
	tool_attrs = {}
	for attributes in FakeLaminar.spans[1]['attributes']:
		tool_attrs.update(attributes)
	assert tool_attrs['tool_index'] == 1
	assert FakeLaminar.spans[1]['input'][0]['tool_calls'][0]['arguments']['code'] == 'emit_output(page_info(), label="page_info")'
	assert FakeLaminar.spans[1]['outputs'][-1][0]['content'][0] == {'type': 'text', 'text': 'Example Domain page info'}
	assert FakeLaminar.spans[1]['outputs'][-1][0]['content'][1] == {
		'type': 'image_url',
		'image_url': {'url': 'data:image/png;base64,iVBORw0KGgo=', 'detail': 'low'},
	}
	assert FakeLaminar.flushes == 2


def test_beta_agent_laminar_tool_span_preserves_image_only_outputs(tmp_path):
	import browser_use.beta.service as beta_service

	image_path = tmp_path / 'tool.png'
	image_path.write_bytes(b'\x89PNG\r\n\x1a\n')

	events = [
		{
			'event_type': 'tool.started',
			'payload': {'name': 'browser_script', 'tool_call_id': 'call-1', 'arguments': {'code': 'observe()'}},
		},
		{
			'event_type': 'tool.output',
			'payload': {
				'name': 'browser_script',
				'tool_call_id': 'call-1',
				'ok': True,
				'text': '',
				'images': [{'path': str(image_path), 'mime_type': 'image/png'}],
			},
		},
	]

	class FakeLaminar:
		spans = []
		flushes = 0
		current_span = None

		@staticmethod
		def is_initialized():
			return True

		@classmethod
		def set_span_attributes(cls, attributes):
			if cls.current_span is not None:
				cls.current_span['attributes'].append(attributes)

		@classmethod
		def set_span_output(cls, output):
			if cls.current_span is not None:
				cls.current_span['outputs'].append(output)

		@classmethod
		def event(cls, name, attributes=None):
			return None

		@classmethod
		def flush(cls):
			cls.flushes += 1

		@classmethod
		def start_as_current_span(cls, name, input=None, span_type='DEFAULT'):
			record = {'name': name, 'input': input, 'span_type': span_type, 'attributes': [], 'outputs': []}

			class Span:
				def __enter__(self):
					cls.current_span = record
					cls.spans.append(record)
					return self

				def __exit__(self, exc_type, exc, tb):
					cls.current_span = None
					return False

			return Span()

	original = beta_service.Laminar
	try:
		beta_service.Laminar = FakeLaminar
		beta_service._record_laminar_terminal_tool_spans(events, max_spans=10)
	finally:
		beta_service.Laminar = original

	output = FakeLaminar.spans[0]['outputs'][-1]
	assert output[0]['content'] == [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,iVBORw0KGgo='}}]
	assert FakeLaminar.flushes == 1


async def test_beta_agent_authenticate_cloud_sync_logs_browser_use_warning(monkeypatch):
	from browser_use.agent.service import _PythonAgent as BrowserUseAgent
	from browser_use.beta import Agent as BetaAgent

	class LLM:
		model = 'gpt-test'
		provider = 'test'

		async def ainvoke(self, messages, output_format=None, **kwargs):
			return type('Result', (), {'usage': None})()

	class RecordingLogger:
		def __init__(self):
			self.warnings = []

		def debug(self, message, *args, **kwargs):
			pass

		def info(self, message, *args, **kwargs):
			pass

		def warning(self, message, *args, **kwargs):
			self.warnings.append(message)

		def error(self, message, *args, **kwargs):
			pass

	browser_use_logger = RecordingLogger()
	beta_logger = RecordingLogger()
	monkeypatch.setattr(BrowserUseAgent, 'logger', property(lambda self: browser_use_logger))
	monkeypatch.setattr(BetaAgent, 'logger', property(lambda self: beta_logger))

	browser_use_agent = BrowserUseAgent(task='Cloud sync warning parity.', llm=LLM(), directly_open_url=False)
	beta_agent = BetaAgent(task='Cloud sync warning parity.', llm=LLM(), directly_open_url=False)

	assert await browser_use_agent.authenticate_cloud_sync(show_instructions=False) is False
	assert await beta_agent.authenticate_cloud_sync(show_instructions=False) is False
	assert beta_logger.warnings == browser_use_logger.warnings
	assert beta_logger.warnings == ['Cloud sync has been removed and is no longer available']


def test_beta_agent_trace_metadata_matches_browser_use_helpers(monkeypatch):
	import browser_use.beta.service as beta_service
	from browser_use.beta import Agent
	from browser_use.beta.service import _history_from_events

	monkeypatch.setattr(beta_service, 'get_browser_use_version', lambda: '9.9.9-test')
	monkeypatch.setattr(beta_service, 'get_git_info', lambda: {'branch': 'trace-branch', 'commit_hash': 'abc123'})

	agent = Agent(task='Trace metadata.', llm=type('LLM', (), {'model': 'gpt-test'})())
	agent.history = _history_from_events(
		[{'event_type': 'session.done', 'payload': {'result': 'trace metadata answer'}}],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	trace = agent.get_trace_object()['trace']

	assert trace['browser_use_version'] == '9.9.9-test'
	assert json.loads(trace['git_info']) == {'branch': 'trace-branch', 'commit_hash': 'abc123'}


def test_beta_agent_initializes_action_models_without_conversation_path():
	from browser_use.beta import Agent

	agent = Agent(
		task='Initialize action models without saving conversations.',
		llm=type('LLM', (), {'model': 'gpt-test'})(),
		directly_open_url=False,
	)

	assert agent.settings.save_conversation_path is None
	assert agent.AgentOutput is not None
	assert agent.DoneAgentOutput is not None


def test_rust_history_marks_process_failure_not_done():
	from browser_use.beta.service import _history_from_events

	history = _history_from_events(
		[],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error='terminal failed',
	)

	assert history.final_result() is None
	assert history.is_done() is False
	assert history.is_successful() is None
	assert history.errors() == ['terminal failed']


def test_rust_history_process_failure_ignores_empty_stream_text():
	from browser_use.beta.service import _history_from_events

	history = _history_from_events(
		[
			{'event_type': 'model.turn.request', 'payload': {'model': 'gpt-test'}},
			{'event_type': 'model.stream_delta', 'payload': {'text': None}},
			{'event_type': 'token_count', 'payload': {'info': {'last_token_usage': {'input_tokens': 1}}}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error='terminal failed after empty stream delta',
	)

	assert history.final_result() is None
	assert history.is_done() is False
	assert history.errors() == ['terminal failed after empty stream delta']


def test_rust_history_marks_missing_terminal_result_as_error():
	from browser_use.beta.service import _history_from_events

	history = _history_from_events(
		[{'event_type': 'model.turn.request', 'payload': {'model': 'gpt-test'}}],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	assert history.final_result() is None
	assert history.is_done() is False
	assert history.errors() == ['Rust terminal session did not produce a final result.']


def test_rust_history_surfaces_terminal_stream_error_message():
	from browser_use.beta.service import _history_from_events

	history = _history_from_events(
		[
			{'event_type': 'model.turn.request', 'payload': {'model': 'gpt-test'}},
			{'event_type': 'stream_error', 'payload': {'message': 'provider error'}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	assert history.final_result() is None
	assert history.is_done() is False
	assert history.errors() == ['provider error']


def test_rust_history_surfaces_terminal_operational_failure_events():
	from browser_use.beta.service import _history_from_events

	failed = _history_from_events(
		[
			{'event_type': 'model.turn.request', 'payload': {'model': 'gpt-test'}},
			{'event_type': 'browser.cloud_shutdown_failed', 'payload': {'error': 'cloud browser shutdown failed'}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	final_not_ready = _history_from_events(
		[
			{'event_type': 'model.turn.request', 'payload': {'model': 'gpt-test'}},
			{'event_type': 'session.final_answer_not_ready_at_max_turns', 'payload': {}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	successful_with_cleanup_warning = _history_from_events(
		[
			{'event_type': 'session.done', 'payload': {'result': 'final answer'}},
			{'event_type': 'browser.cleanup_failed', 'payload': {'error': 'cleanup panicked'}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	assert failed.final_result() is None
	assert failed.is_done() is False
	assert failed.errors() == ['browser cloud shutdown failed: cloud browser shutdown failed']
	assert failed.action_results()[-1].error == 'browser cloud shutdown failed: cloud browser shutdown failed'

	assert final_not_ready.final_result() is None
	assert final_not_ready.is_done() is False
	assert final_not_ready.errors() == ['final answer artifact is not ready']

	assert successful_with_cleanup_warning.final_result() == 'final answer'
	assert successful_with_cleanup_warning.is_done() is True
	assert successful_with_cleanup_warning.errors() == [None]


def test_rust_history_surfaces_terminal_subagent_failure_events():
	from browser_use.beta.service import _history_from_events

	failed = _history_from_events(
		[
			{
				'event_type': 'agent.failed',
				'payload': {
					'child_session_id': 'child-1',
					'status': 'failed',
					'payload': {
						'child_session_id': 'child-1',
						'status': 'failed',
						'failure': 'child task failed',
					},
				},
			}
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	cancelled = _history_from_events(
		[
			{
				'event_type': 'agent.cancelled',
				'payload': {
					'child_session_id': 'child-2',
					'status': 'cancelled',
					'payload': {
						'child_session_id': 'child-2',
						'status': 'cancelled',
					},
				},
			}
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	assert failed.final_result() is None
	assert failed.is_done() is False
	assert failed.errors() == ['child task failed']
	assert failed.action_results()[-1].error == 'child task failed'

	assert cancelled.final_result() is None
	assert cancelled.is_done() is False
	assert cancelled.errors() == ['Subagent was cancelled.']
	assert cancelled.action_results()[-1].error == 'Subagent was cancelled.'


def test_rust_history_surfaces_terminal_tool_failure_message():
	from browser_use.beta.service import _history_from_events

	history = _history_from_events(
		[
			{'event_type': 'model.turn.request', 'payload': {'model': 'gpt-test'}},
			{
				'type': 'tool.started',
				'payload': {
					'name': 'browser_script',
					'tool_call_id': 'call-browser',
					'arguments': {'code': "goto_url('https://example.invalid')"},
				},
			},
			{
				'type': 'tool.failed',
				'payload': {
					'name': 'browser_script',
					'tool_call_id': 'call-browser',
					'error': 'RuntimeError: navigation failed',
				},
			},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	assert history.final_result() is None
	assert history.is_done() is False
	assert history.errors() == ['browser_script failed: RuntimeError: navigation failed']
	assert history.action_results()[-1].error == 'browser_script failed: RuntimeError: navigation failed'


def test_rust_history_surfaces_running_browser_script_observe_instruction():
	from browser_use.beta.service import _history_from_events

	history = _history_from_events(
		[
			{'event_type': 'model.turn.request', 'payload': {'model': 'gpt-test'}},
			{
				'event_type': 'tool.started',
				'payload': {
					'name': 'browser_script',
					'tool_call_id': 'call-browser',
					'arguments': {'code': "goto_url('https://example.com')\nwait_for_load(30)"},
				},
			},
			{
				'event_type': 'tool.output',
				'payload': {
					'name': 'browser_script',
					'tool_call_id': 'call-browser',
					'ok': True,
					'status': 'running',
					'run_id': 'bs-123',
					'next_observe_ms': 7000,
					'text': '',
				},
			},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	tool_result = history.action_results()[0]
	assert tool_result.error is None
	assert tool_result.extracted_content is not None
	assert 'browser_script is still running.' in tool_result.extracted_content
	assert 'run_id: bs-123' in tool_result.extracted_content
	assert 'action="observe"' in tool_result.extracted_content
	assert 'observe_timeout_ms=7000' in tool_result.extracted_content


def test_rust_history_surfaces_terminal_cancellation_and_tool_abort_messages():
	from browser_use.beta.service import _history_from_events

	cancelled = _history_from_events(
		[
			{'event_type': 'model.turn.request', 'payload': {'model': 'gpt-test'}},
			{'event_type': 'session.cancelled', 'payload': {'reason': 'user requested stop'}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	aborted = _history_from_events(
		[
			{'event_type': 'model.turn.request', 'payload': {'model': 'gpt-test'}},
			{
				'type': 'tool.started',
				'payload': {
					'name': 'browser',
					'tool_call_id': 'call-browser',
					'arguments': {'cmd': 'connect managed --headless'},
				},
			},
			{
				'type': 'tool.aborted',
				'payload': {
					'name': 'browser',
					'tool_call_id': 'call-browser',
					'error': 'aborted by user',
				},
			},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	assert cancelled.final_result() is None
	assert cancelled.is_done() is False
	assert cancelled.errors() == ['Rust terminal session was cancelled: user requested stop']
	assert cancelled.action_results()[-1].error == 'Rust terminal session was cancelled: user requested stop'

	assert aborted.final_result() is None
	assert aborted.is_done() is False
	assert aborted.errors() == ['browser aborted: aborted by user']
	assert aborted.action_results()[0].error == 'browser aborted: aborted by user'
	assert aborted.action_results()[-1].error == 'browser aborted: aborted by user'


def test_rust_history_preserves_terminal_tool_abort_when_failed_event_follows():
	from browser_use.beta.service import _history_from_events

	history = _history_from_events(
		[
			{'event_type': 'model.turn.request', 'payload': {'model': 'gpt-test'}},
			{
				'type': 'tool.started',
				'payload': {
					'name': 'exec_command',
					'tool_call_id': 'call-exec',
					'arguments': {'cmd': 'sleep 60'},
				},
			},
			{
				'type': 'tool.aborted',
				'payload': {
					'name': 'exec_command',
					'tool_call_id': 'call-exec',
					'error': 'aborted by user after 1.0s',
				},
			},
			{
				'type': 'tool.failed',
				'payload': {
					'name': 'exec_command',
					'tool_call_id': 'call-exec',
					'error': 'aborted by user after 1.0s',
				},
			},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	assert history.final_result() is None
	assert history.is_done() is False
	assert history.errors() == ['exec_command aborted: aborted by user after 1.0s']
	assert history.action_results()[0].error == 'exec_command aborted: aborted by user after 1.0s'
	assert history.action_results()[-1].error == 'exec_command aborted: aborted by user after 1.0s'


def test_rust_history_surfaces_terminal_session_interrupted_message():
	from browser_use.beta.service import _history_from_events

	history = _history_from_events(
		[
			{'event_type': 'model.turn.request', 'payload': {'model': 'gpt-test'}},
			{'event_type': 'session.interrupted', 'payload': {'reason': 'interrupted by send_input'}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	assert history.final_result() is None
	assert history.is_done() is False
	assert history.errors() == ['Rust terminal session was interrupted: interrupted by send_input']
	assert history.action_results()[-1].error == 'Rust terminal session was interrupted: interrupted by send_input'
