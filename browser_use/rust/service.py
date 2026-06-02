from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import shutil
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Generic, Literal

from pydantic import BaseModel, ValidationError
from typing_extensions import TypeVar
from uuid_extensions import uuid7str

from browser_use.agent.views import ActionResult, AgentHistory, AgentHistoryList, AgentSettings, AgentState, StepMetadata
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.browser.profile import CHROME_DETERMINISTIC_RENDERING_ARGS, CHROME_DISABLE_SECURITY_ARGS, CHROME_DOCKER_ARGS
from browser_use.browser.views import BrowserStateHistory, TabInfo
from browser_use.tokens.views import ModelUsageStats, UsageSummary


AgentStructuredOutput = TypeVar('AgentStructuredOutput', bound=BaseModel)
AgentHookFunc = Callable[[Any], Awaitable[None] | None]
AgentDoneCallback = Callable[[AgentHistoryList], Awaitable[None] | None]


class RustAgentError(RuntimeError):
	"""Raised when the Rust terminal core cannot run a task."""


def find_browser_use_terminal_binary() -> str:
	"""Find the terminal binary used by the Rust-backed Browser Use Agent."""
	env_path = os.environ.get('BROWSER_USE_TERMINAL_BINARY')
	if env_path:
		return env_path
	path_binary = shutil.which('browser-use-terminal')
	if path_binary:
		return path_binary
	candidates = [
		Path.cwd() / 'target' / 'debug' / 'browser-use-terminal',
		Path.cwd().parent / 'terminal' / 'target' / 'debug' / 'browser-use-terminal',
		Path('/home/exedev/Developer/terminal/target/debug/browser-use-terminal'),
	]
	for candidate in candidates:
		if candidate.exists():
			return str(candidate)
	raise RustAgentError(
		'Could not find browser-use-terminal. Set BROWSER_USE_TERMINAL_BINARY or build the terminal CLI.'
	)


def _model_name(llm: Any | None) -> str:
	for attr in ('model', 'model_name', 'name'):
		value = getattr(llm, attr, None)
		if isinstance(value, str) and value:
			return value
	return os.environ.get('BROWSER_USE_RUST_MODEL', 'gpt-5.3-codex-spark')


def _extract_cdp_url(browser_session: BrowserSession | None) -> str | None:
	if browser_session is None:
		return None
	for attr in ('cdp_url',):
		value = getattr(browser_session, attr, None)
		if isinstance(value, str) and value:
			return value
	profile = getattr(browser_session, 'browser_profile', None)
	value = getattr(profile, 'cdp_url', None)
	if isinstance(value, str) and value:
		return value
	return None


def _extract_profile_cdp_url(browser_profile: BrowserProfile | None) -> str | None:
	if browser_profile is None:
		return None
	value = getattr(browser_profile, 'cdp_url', None)
	if isinstance(value, str) and value:
		return value
	return None


def _extract_headless_preference(browser_session: BrowserSession | None, browser_profile: BrowserProfile | None) -> bool | None:
	session_profile = getattr(browser_session, 'browser_profile', None)
	for profile in (session_profile, browser_profile):
		value = getattr(profile, 'headless', None)
		if isinstance(value, bool):
			return value
	value = getattr(browser_session, 'headless', None)
	if isinstance(value, bool):
		return value
	return None


def _extract_cloud_preference(browser_session: BrowserSession | None, browser_profile: BrowserProfile | None) -> bool:
	session_profile = getattr(browser_session, 'browser_profile', None)
	for profile in (session_profile, browser_profile, browser_session):
		for attr in ('use_cloud', 'cloud_browser'):
			value = getattr(profile, attr, None)
			if isinstance(value, bool) and value:
				return True
	return False


def _value_from_object(value: Any, key: str) -> Any:
	if value is None:
		return None
	if isinstance(value, dict):
		return value.get(key)
	return getattr(value, key, None)


def _append_unique(items: list[str], seen: set[str], value: Any) -> None:
	if not isinstance(value, str) or not value:
		return
	if value in seen:
		return
	items.append(value)
	seen.add(value)


def _window_size_arg(window_size: Any) -> str | None:
	if window_size is None:
		return None
	if isinstance(window_size, (list, tuple)) and len(window_size) >= 2:
		width, height = window_size[0], window_size[1]
	else:
		width = _value_from_object(window_size, 'width')
		height = _value_from_object(window_size, 'height')
	if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
		return None
	return f'--window-size={width},{height}'


def _window_position_arg(window_position: Any) -> str | None:
	if window_position is None:
		return None
	if isinstance(window_position, (list, tuple)) and len(window_position) >= 2:
		x, y = window_position[0], window_position[1]
	else:
		x = _value_from_object(window_position, 'width')
		y = _value_from_object(window_position, 'height')
	if not isinstance(x, int) or not isinstance(y, int):
		return None
	return f'--window-position={x},{y}'


def _managed_browser_launch_args(browser_session: BrowserSession | None, browser_profile: BrowserProfile | None) -> list[str]:
	args: list[str] = []
	seen: set[str] = set()
	session_profile = getattr(browser_session, 'browser_profile', None)
	for profile in (session_profile, browser_profile):
		raw_args = getattr(profile, 'args', None)
		if isinstance(raw_args, set):
			raw_args = sorted(raw_args)
		if isinstance(raw_args, (list, tuple)):
			for arg in raw_args:
				_append_unique(args, seen, arg)
		if getattr(profile, 'disable_security', False) is True:
			for arg in CHROME_DISABLE_SECURITY_ARGS:
				_append_unique(args, seen, arg)
		if getattr(profile, 'deterministic_rendering', False) is True:
			for arg in CHROME_DETERMINISTIC_RENDERING_ARGS:
				_append_unique(args, seen, arg)
		if getattr(profile, 'chromium_sandbox', None) is False:
			for arg in CHROME_DOCKER_ARGS:
				_append_unique(args, seen, arg)
		_append_unique(args, seen, _window_size_arg(getattr(profile, 'window_size', None)))
		_append_unique(args, seen, _window_position_arg(getattr(profile, 'window_position', None)))
		proxy = getattr(profile, 'proxy', None)
		proxy_server = _value_from_object(proxy, 'server')
		if isinstance(proxy_server, str) and proxy_server:
			_append_unique(args, seen, f'--proxy-server={proxy_server}')
			proxy_bypass = _value_from_object(proxy, 'bypass')
			if isinstance(proxy_bypass, str) and proxy_bypass:
				_append_unique(args, seen, f'--proxy-bypass-list={proxy_bypass}')
		user_agent = getattr(profile, 'user_agent', None)
		if isinstance(user_agent, str) and user_agent:
			_append_unique(args, seen, f'--user-agent={user_agent}')
	return args


def _managed_browser_profile_dir(browser_session: BrowserSession | None, browser_profile: BrowserProfile | None) -> str | None:
	session_profile = getattr(browser_session, 'browser_profile', None)
	for profile in (session_profile, browser_profile, browser_session):
		value = getattr(profile, 'user_data_dir', None)
		if isinstance(value, (str, os.PathLike)) and str(value):
			return str(Path(value).expanduser())
	return None


def _managed_browser_executable_path(browser_session: BrowserSession | None, browser_profile: BrowserProfile | None) -> str | None:
	session_profile = getattr(browser_session, 'browser_profile', None)
	for profile in (session_profile, browser_profile, browser_session):
		value = getattr(profile, 'executable_path', None)
		if isinstance(value, (str, os.PathLike)) and str(value):
			return str(Path(value).expanduser())
	return None


def _env_value_to_str(value: Any) -> str | None:
	if isinstance(value, bool):
		return 'true' if value else 'false'
	if isinstance(value, (str, int, float, os.PathLike)):
		return str(value)
	return None


def _managed_browser_env(browser_session: BrowserSession | None, browser_profile: BrowserProfile | None) -> dict[str, str]:
	env: dict[str, str] = {}
	session_profile = getattr(browser_session, 'browser_profile', None)
	for profile in (session_profile, browser_profile, browser_session):
		raw_env = getattr(profile, 'env', None)
		if not isinstance(raw_env, dict):
			continue
		for key, value in raw_env.items():
			env_value = _env_value_to_str(value)
			if isinstance(key, str) and key and env_value is not None:
				env[key] = env_value
	return env


def _is_managed_browser_mode(mode: str) -> bool:
	normalized = mode.strip().lower().replace('_', '-').replace(' ', '-')
	return normalized in {'managed-headless', 'headless', 'headless-chromium', 'managed-headed', 'managed', 'headed'}


def _domain_list(value: Any) -> list[str]:
	if value is None or isinstance(value, str):
		return []
	if isinstance(value, set):
		items = sorted(value)
	elif isinstance(value, list):
		items = value
	else:
		return []
	return [item for item in items if isinstance(item, str) and item]


def _extract_profile_domains(
	browser_session: BrowserSession | None,
	browser_profile: BrowserProfile | None,
	attr: str,
) -> list[str]:
	values: list[str] = []
	seen: set[str] = set()
	session_profile = getattr(browser_session, 'browser_profile', None)
	for profile in (session_profile, browser_profile):
		for domain in _domain_list(getattr(profile, attr, None)):
			if domain in seen:
				continue
			values.append(domain)
			seen.add(domain)
	return values


def _sensitive_data_context(sensitive_data: dict[str, str | dict[str, str]] | None) -> dict[str, Any]:
	if not sensitive_data:
		return {'global_placeholders': [], 'domain_placeholders': {}}
	global_placeholders: list[str] = []
	domain_placeholders: dict[str, list[str]] = {}
	for key, value in sensitive_data.items():
		if isinstance(value, dict):
			placeholders = sorted(name for name, secret in value.items() if isinstance(name, str) and name and secret)
			if placeholders:
				domain_placeholders[key] = placeholders
		elif isinstance(value, str) and value:
			global_placeholders.append(key)
	return {
		'global_placeholders': sorted(global_placeholders),
		'domain_placeholders': domain_placeholders,
	}


def _navigation_url_from_action(action: Any) -> str | None:
	if not isinstance(action, dict):
		return None
	for name, payload in action.items():
		if name in ('open_tab', 'go_to_url', 'navigate') and isinstance(payload, dict):
			url = payload.get('url')
			if isinstance(url, str) and url:
				return url
	return None


def _initial_navigation_url(initial_actions: Any) -> str | None:
	if not isinstance(initial_actions, list):
		return None
	for action in initial_actions:
		url = _navigation_url_from_action(action)
		if url:
			return url
	return None


def _task_with_initial_actions(task: str, initial_actions: Any) -> str:
	if not isinstance(initial_actions, list) or not initial_actions:
		return task
	if len(initial_actions) == 1:
		url = _navigation_url_from_action(initial_actions[0])
		if url:
			return f'First navigate to {url!r}, then complete the task.\n\n{task}'
	actions = json.dumps(initial_actions, indent=2, default=str)
	return f'Before the task, perform these Browser Use initial actions in order:\n{actions}\n\nThen complete the task.\n\n{task}'


def _task_with_schema(task: str, output_model_schema: type[BaseModel] | None) -> str:
	if output_model_schema is None:
		return task
	schema = json.dumps(output_model_schema.model_json_schema(), indent=2)
	return f'{task}\n\nExpected output JSON schema for the final answer:\n{schema}'


def _task_with_available_files(task: str, available_file_paths: list[str] | None) -> str:
	if not available_file_paths:
		return task
	files = '\n'.join(f'- {Path(path).expanduser()}' for path in available_file_paths)
	return f'{task}\n\nAvailable local files:\n{files}'


def _task_with_domain_constraints(task: str, allowed_domains: list[str], prohibited_domains: list[str]) -> str:
	if not allowed_domains and not prohibited_domains:
		return task
	sections = ['Browser profile navigation constraints:']
	if allowed_domains:
		sections.append('Allowed domains:')
		sections.extend(f'- {domain}' for domain in allowed_domains)
	if prohibited_domains:
		sections.append('Prohibited domains:')
		sections.extend(f'- {domain}' for domain in prohibited_domains)
	sections.append('Respect these BrowserProfile domain constraints when navigating.')
	return f'{task}\n\n' + '\n'.join(sections)


def _task_with_sensitive_data_context(task: str, sensitive_context: dict[str, Any]) -> str:
	global_placeholders = sensitive_context.get('global_placeholders') or []
	domain_placeholders = sensitive_context.get('domain_placeholders') or {}
	if not global_placeholders and not domain_placeholders:
		return task
	sections = ['Sensitive data placeholders are available. Use <secret>placeholder</secret> when a matching secret is needed.']
	if global_placeholders:
		sections.append('Global placeholders:')
		sections.extend(f'- {placeholder}' for placeholder in global_placeholders)
	if domain_placeholders:
		sections.append('Domain-scoped placeholders:')
		for domain, placeholders in domain_placeholders.items():
			sections.append(f'- {domain}: {", ".join(placeholders)}')
	sections.append('Do not reveal placeholder values in the final answer.')
	return f'{task}\n\n' + '\n'.join(sections)


def _extract_start_url(task: str) -> str | None:
	task_without_emails = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '', task)
	patterns = [
		r'https?://[^\s<>"\']+',
		r'(?:www\.)?[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*\.[a-zA-Z]{2,}(?:/[^\s<>"\']*)?',
	]
	excluded_extensions = {
		'pdf',
		'doc',
		'docx',
		'xls',
		'xlsx',
		'ppt',
		'pptx',
		'odt',
		'ods',
		'odp',
		'txt',
		'md',
		'csv',
		'json',
		'xml',
		'yaml',
		'yml',
		'zip',
		'rar',
		'7z',
		'tar',
		'gz',
		'bz2',
		'xz',
		'jpg',
		'jpeg',
		'png',
		'gif',
		'bmp',
		'svg',
		'webp',
		'ico',
		'mp3',
		'mp4',
		'avi',
		'mkv',
		'mov',
		'wav',
		'flac',
		'ogg',
		'py',
		'js',
		'css',
		'java',
		'cpp',
		'bib',
		'bibtex',
		'tex',
		'latex',
		'cls',
		'sty',
		'exe',
		'msi',
		'dmg',
		'pkg',
		'deb',
		'rpm',
		'iso',
	}
	excluded_words = {'never', 'dont', 'not', "don't"}

	found_urls = []
	for pattern in patterns:
		for match in re.finditer(pattern, task_without_emails):
			url = re.sub(r'[.,;:!?()\[\]]+$', '', match.group(0))
			url_lower = url.lower()
			if any(f'.{ext}' in url_lower for ext in excluded_extensions):
				continue
			context_start = max(0, match.start() - 20)
			context_text = task_without_emails[context_start : match.start()]
			if any(word in context_text.lower() for word in excluded_words):
				continue
			if not url.startswith(('http://', 'https://')):
				url = 'https://' + url
			found_urls.append(url)

	unique_urls = list(set(found_urls))
	return unique_urls[0] if len(unique_urls) == 1 else None


def _event_type(event: dict[str, Any]) -> str:
	return str(event.get('event_type') or event.get('type') or '')


def _event_payload(event: dict[str, Any]) -> dict[str, Any]:
	payload = event.get('payload')
	return payload if isinstance(payload, dict) else {}


def _result_file_pointer(payload: dict[str, Any]) -> str | None:
	result_file = payload.get('result_file')
	if isinstance(result_file, dict):
		for key in ('url', 'path'):
			value = result_file.get(key)
			if isinstance(value, str) and value:
				return value
	if isinstance(result_file, str) and result_file:
		return result_file
	for key in ('result_file_url', 'result_file_path', 'result_file'):
		value = payload.get(key)
		if isinstance(value, str) and value:
			return value
	return None


def _result_from_events(events: list[dict[str, Any]]) -> str | None:
	for event in reversed(events):
		if _event_type(event) != 'session.done':
			continue
		payload = _event_payload(event)
		result = payload.get('result')
		if isinstance(result, str) and result.strip():
			return result.strip()
		result_file = _result_file_pointer(payload)
		if result_file:
			return f'Saved result file.\n\nFile:\n{result_file}'
	return None


def _attachments_from_events(events: list[dict[str, Any]]) -> list[str] | None:
	attachments: list[str] = []
	for event in events:
		if _event_type(event) != 'session.done':
			continue
		result_file = _result_file_pointer(_event_payload(event))
		if result_file and result_file not in attachments:
			attachments.append(result_file)
	return attachments or None


def _json_result_candidates(text: str) -> list[str]:
	candidates = [text.strip()]
	candidates.extend(match.group(1).strip() for match in re.finditer(r'```(?:json)?\s*(.*?)```', text, re.IGNORECASE | re.DOTALL))
	decoder = json.JSONDecoder()
	for index, char in enumerate(text):
		if char not in '{[':
			continue
		try:
			parsed, _end = decoder.raw_decode(text[index:])
		except json.JSONDecodeError:
			continue
		candidates.append(json.dumps(parsed))
	seen = set()
	unique = []
	for candidate in candidates:
		if not candidate or candidate in seen:
			continue
		seen.add(candidate)
		unique.append(candidate)
	return unique


def _structured_result_text(
	result: str | None,
	output_model_schema: type[BaseModel] | None,
) -> str | None:
	if result is None or output_model_schema is None:
		return result
	for candidate in _json_result_candidates(result):
		try:
			output_model_schema.model_validate_json(candidate)
		except (ValidationError, ValueError):
			continue
		return candidate
	return result


def _failure_from_events(events: list[dict[str, Any]]) -> str | None:
	for event in reversed(events):
		if _event_type(event) == 'session.failed':
			error = _event_payload(event).get('error')
			if isinstance(error, str) and error:
				return error
	return None


def _browser_state_from_events(events: list[dict[str, Any]]) -> BrowserStateHistory:
	url = ''
	title = ''
	tabs: list[TabInfo] = []
	for event in events:
		if _event_type(event) not in ('browser.connected', 'browser.reconnected', 'browser.target_changed', 'browser.page', 'browser.state'):
			continue
		payload = _event_payload(event)
		url = str(payload.get('url') or url)
		title = str(payload.get('title') or title)
		raw_tabs = payload.get('tabs')
		if isinstance(raw_tabs, list):
			next_tabs = []
			for idx, raw in enumerate(raw_tabs):
				if isinstance(raw, dict):
					next_tabs.append(
						TabInfo(
							url=str(raw.get('url') or ''),
							title=str(raw.get('title') or ''),
							target_id=str(raw.get('target_id') or raw.get('tab_id') or f'tab-{idx}'),
						)
					)
			if next_tabs:
				tabs = next_tabs
	if not tabs and (url or title):
		tabs = [TabInfo(url=url, title=title, target_id='tab-0')]
	return BrowserStateHistory(url=url, title=title, tabs=tabs, interacted_element=[])


def _usage_from_events(events: list[dict[str, Any]], model: str) -> UsageSummary:
	input_tokens = 0
	cached_input_tokens = 0
	output_tokens = 0
	cost = 0.0
	invocations = 0

	for event in events:
		if _event_type(event) != 'model.usage':
			continue
		payload = _event_payload(event)
		input_tokens += int(payload.get('input_tokens') or 0)
		cached_input_tokens += int(payload.get('input_cached_tokens') or payload.get('cached_input_tokens') or 0)
		output_tokens += int(payload.get('output_tokens') or 0)
		cost += float(payload.get('cost_usd') or payload.get('cost') or 0.0)
		invocations += 1

	total_tokens = input_tokens + output_tokens
	by_model = {
		model: ModelUsageStats(
			model=model,
			prompt_tokens=input_tokens,
			completion_tokens=output_tokens,
			total_tokens=total_tokens,
			cost=cost,
			invocations=invocations,
		)
	}
	return UsageSummary(
		total_prompt_tokens=input_tokens,
		total_prompt_cost=0.0,
		total_prompt_cached_tokens=cached_input_tokens,
		total_prompt_cached_cost=0.0,
		total_completion_tokens=output_tokens,
		total_completion_cost=0.0,
		total_tokens=total_tokens,
		total_cost=cost,
		entry_count=invocations,
		by_model=by_model,
	)


def _history_from_events(
	events: list[dict[str, Any]],
	*,
	model: str,
	started: float,
	finished: float,
	output_model_schema: type[AgentStructuredOutput] | None,
	process_error: str | None,
) -> AgentHistoryList[AgentStructuredOutput]:
	final_result = _structured_result_text(_result_from_events(events), output_model_schema)
	failure = process_error or _failure_from_events(events)
	if final_result is None and failure is None:
		failure = 'Rust terminal session did not produce a final result.'
	is_done = final_result is not None and failure is None
	result = ActionResult(
		is_done=is_done,
		success=True if is_done else None,
		error=failure,
		attachments=_attachments_from_events(events),
		extracted_content=final_result,
	)
	history = AgentHistory(
		model_output=None,
		result=[result],
		state=_browser_state_from_events(events),
		metadata=StepMetadata(step_start_time=started, step_end_time=finished, step_number=max(1, len(events))),
	)
	history_list: AgentHistoryList[AgentStructuredOutput] = AgentHistoryList(
		history=[history],
		usage=_usage_from_events(events, model),
	)
	history_list._output_model_schema = output_model_schema
	return history_list


def _load_rust_history(file_path: str | Path) -> AgentHistoryList:
	with open(file_path, encoding='utf-8') as history_file:
		data = json.load(history_file)
	if not isinstance(data, dict):
		raise RustAgentError(f'Invalid Browser Use history file: {file_path}')
	for item in data.get('history', []):
		if isinstance(item, dict):
			item['model_output'] = None
			state = item.get('state')
			if isinstance(state, dict) and 'interacted_element' not in state:
				state['interacted_element'] = None
	return AgentHistoryList.model_validate(data)


class Agent(Generic[AgentStructuredOutput]):
	"""Browser Use-style Agent backed by the Rust browser-use-terminal core."""

	def __init__(
		self,
		task: str,
		llm: Any | None = None,
		browser_profile: BrowserProfile | None = None,
		browser_session: BrowserSession | None = None,
		browser: BrowserSession | None = None,
		tools: Any | None = None,
		controller: Any | None = None,
		sensitive_data: dict[str, str | dict[str, str]] | None = None,
		initial_actions: list[dict[str, dict[str, Any]]] | None = None,
		register_new_step_callback: Callable[..., Awaitable[None] | None] | None = None,
		register_done_callback: AgentDoneCallback | None = None,
		register_external_agent_status_raise_error_callback: Callable[[], Awaitable[bool]] | None = None,
		register_should_stop_callback: Callable[[], Awaitable[bool]] | None = None,
		output_model_schema: type[AgentStructuredOutput] | None = None,
		use_vision: bool | Literal['auto'] = 'auto',
		save_conversation_path: str | Path | None = None,
		save_conversation_path_encoding: str | None = 'utf-8',
		max_failures: int = 3,
		override_system_message: str | None = None,
		extend_system_message: str | None = None,
		generate_gif: bool | str = False,
		available_file_paths: list[str] | None = None,
		include_attributes: list[str] | None = None,
		max_actions_per_step: int = 10,
		use_thinking: bool = True,
		flash_mode: bool = False,
		max_history_items: int | None = None,
		page_extraction_llm: Any | None = None,
		injected_agent_state: AgentState | None = None,
		task_id: str | None = None,
		calculate_cost: bool = False,
		display_files_in_done_text: bool = True,
		include_tool_call_examples: bool = False,
		vision_detail_level: Literal['auto', 'low', 'high'] = 'auto',
		llm_timeout: int | None = None,
		step_timeout: int = 120,
		directly_open_url: bool = True,
		include_recent_events: bool = False,
		sample_images: list[Any] | None = None,
		final_response_after_failure: bool = True,
		file_system_path: str | None = None,
		source: str | None = None,
		_url_shortening_limit: int = 25,
		**kwargs: Any,
	) -> None:
		if browser and browser_session:
			raise ValueError('Cannot specify both "browser" and "browser_session".')
		if tools is not None and controller is not None:
			raise ValueError('Cannot specify both "tools" and "controller".')
		self.id = task_id or uuid7str()
		self.task_id = self.id
		self.llm = llm
		self.browser_profile = browser_profile
		self.browser_session = browser or browser_session
		self.tools = controller or tools
		self.sensitive_data = sensitive_data
		self.register_new_step_callback = register_new_step_callback
		self.register_done_callback = register_done_callback
		self.register_external_agent_status_raise_error_callback = register_external_agent_status_raise_error_callback
		self.register_should_stop_callback = register_should_stop_callback
		self.output_model_schema = output_model_schema
		self.source = source
		self.kwargs = kwargs
		self.model = _model_name(llm)
		self.state = injected_agent_state or AgentState(agent_id=self.id)
		self.settings = AgentSettings(
			use_vision=use_vision,
			vision_detail_level=vision_detail_level,
			save_conversation_path=save_conversation_path,
			save_conversation_path_encoding=save_conversation_path_encoding,
			max_failures=max_failures,
			override_system_message=override_system_message,
			extend_system_message=extend_system_message,
			generate_gif=generate_gif,
			include_attributes=include_attributes,
			max_actions_per_step=max_actions_per_step,
			use_thinking=use_thinking,
			flash_mode=flash_mode,
			max_history_items=max_history_items,
			page_extraction_llm=page_extraction_llm,
			calculate_cost=calculate_cost,
			include_tool_call_examples=include_tool_call_examples,
			llm_timeout=llm_timeout or 60,
			step_timeout=step_timeout,
			final_response_after_failure=final_response_after_failure,
		)
		self.available_file_paths = available_file_paths or []
		self.allowed_domains = _extract_profile_domains(self.browser_session, self.browser_profile, 'allowed_domains')
		self.prohibited_domains = _extract_profile_domains(self.browser_session, self.browser_profile, 'prohibited_domains')
		self.managed_browser_args = _managed_browser_launch_args(self.browser_session, self.browser_profile)
		self.managed_browser_profile_dir = _managed_browser_profile_dir(self.browser_session, self.browser_profile)
		self.managed_browser_executable_path = _managed_browser_executable_path(self.browser_session, self.browser_profile)
		self.managed_browser_env = _managed_browser_env(self.browser_session, self.browser_profile)
		self.sensitive_data_context = _sensitive_data_context(sensitive_data)
		self.display_files_in_done_text = display_files_in_done_text
		self.file_system_path = file_system_path
		self.directly_open_url = directly_open_url
		self.include_recent_events = include_recent_events
		self.sample_images = sample_images
		self._url_shortening_limit = _url_shortening_limit
		self.initial_url = None
		if self.directly_open_url and not self.state.follow_up_task and not initial_actions:
			self.initial_url = _extract_start_url(task)
			if self.initial_url:
				initial_actions = [{'navigate': {'url': self.initial_url, 'new_tab': False}}]
		self.initial_actions = initial_actions
		self.task = _task_with_schema(
			_task_with_available_files(
				_task_with_sensitive_data_context(
					_task_with_domain_constraints(
						_task_with_initial_actions(task, initial_actions),
						self.allowed_domains,
						self.prohibited_domains,
					),
					self.sensitive_data_context,
				),
				self.available_file_paths,
			),
			output_model_schema,
		)
		self.session_id: str | None = None
		self.history: AgentHistoryList[AgentStructuredOutput] = AgentHistoryList(history=[], usage=None)
		self.result: AgentHistoryList[AgentStructuredOutput] | None = None
		self.last_events: list[dict[str, Any]] = []
		self.last_stdout = ''
		self.last_stderr = ''
		self._external_pause_event = asyncio.Event()
		self._external_pause_event.set()

	async def run(
		self,
		max_steps: int = 100,
		on_step_start: AgentHookFunc | None = None,
		on_step_end: AgentHookFunc | None = None,
	) -> AgentHistoryList[AgentStructuredOutput]:
		await self._call_callback(on_step_start, self)
		started = time.time()
		if await self._should_stop_before_run():
			finished = time.time()
			self.result = _history_from_events(
				[],
				model=self.model,
				started=started,
				finished=finished,
				output_model_schema=self.output_model_schema,
				process_error='Rust agent stopped before terminal run.',
			)
			self.history = self.result
			await self._call_callback(on_step_end, self)
			return self.history
		if self.state.paused:
			finished = time.time()
			self.result = _history_from_events(
				[],
				model=self.model,
				started=started,
				finished=finished,
				output_model_schema=self.output_model_schema,
				process_error='Rust agent is paused before terminal run.',
			)
			self.history = self.result
			await self._call_callback(on_step_end, self)
			return self.history
		if self.state.follow_up_task and self.session_id:
			self.state.follow_up_task = False
			return await self.follow_up(self.task, max_steps=max_steps)

		returncode, stdout_text, stderr_text = await self._run_process(self._run_argv(max_steps), timeout_seconds=self.settings.step_timeout)
		finished = time.time()
		self.last_stdout = stdout_text
		self.last_stderr = stderr_text
		self.session_id = self._session_id_from_stdout(stdout_text)
		events = await self._load_events()
		process_error = None
		if returncode:
			process_error = stderr_text.strip() or f'browser-use-terminal exited with code {returncode}'
		elif not self.session_id:
			process_error = 'browser-use-terminal did not print a session id.'
		self.last_events = events
		self.result = _history_from_events(
			events,
			model=self.model,
			started=started,
			finished=finished,
			output_model_schema=self.output_model_schema,
			process_error=process_error,
		)
		self.history = self.result
		self._sync_state_from_history()
		await self._save_conversation_if_requested()
		await self._call_new_step_callback()
		await self._call_callback(on_step_end, self)
		await self._call_done_callback()
		return self.history

	async def follow_up(self, task: str, max_steps: int | None = None) -> AgentHistoryList[AgentStructuredOutput]:
		if not self.session_id:
			raise RustAgentError('No active Rust session. Call run() before follow_up().')
		started = time.time()
		binary = find_browser_use_terminal_binary()
		returncode, stdout_text, stderr_text = await self._run_process(
			[binary, *self._state_dir_args(), 'followup', self.session_id, task],
			timeout_seconds=self.settings.step_timeout,
		)
		if returncode:
			raise RustAgentError(stderr_text or stdout_text)
		returncode, _stdout_text, stderr_text = await self._run_process(
			self._run_existing_argv(max_steps if max_steps is not None else self.kwargs.get('max_steps', 100)),
			timeout_seconds=self.settings.step_timeout,
		)
		finished = time.time()
		process_error = None
		if returncode:
			process_error = stderr_text.strip() or f'browser-use-terminal exited with code {returncode}'
		self.last_events = await self._load_events()
		self.result = _history_from_events(
			self.last_events,
			model=self.model,
			started=started,
			finished=finished,
			output_model_schema=self.output_model_schema,
			process_error=process_error,
		)
		self.history = self.result
		self._sync_state_from_history()
		await self._save_conversation_if_requested()
		await self._call_new_step_callback()
		await self._call_done_callback()
		return self.history

	follow_up_task = follow_up

	@property
	def usage(self) -> UsageSummary | None:
		return self.history.usage

	def add_new_task(self, new_task: str) -> None:
		"""Add a follow-up task while keeping the same Browser Use-style agent object."""
		self.task = _task_with_schema(new_task, self.output_model_schema)
		self.state.follow_up_task = True
		self.state.stopped = False
		self.state.paused = False
		self._external_pause_event.set()

	def save_history(self, file_path: str | Path | None = None) -> None:
		"""Save the current Browser Use history to disk."""
		if not file_path:
			file_path = 'AgentHistory.json'
		self.history.save_to_file(file_path, sensitive_data=self.sensitive_data)

	async def rerun_history(
		self,
		history: AgentHistoryList,
		max_retries: int = 3,
		skip_failures: bool = True,
		delay_between_actions: float = 2.0,
	) -> list[ActionResult]:
		"""Rerun through the Rust core and return Browser Use-style action results.

		The Python Agent replays serialized Python action models. Rust terminal
		histories do not expose those action models, so this compatibility path
		reruns the current task through the Rust core and returns reconstructed
		action results.
		"""
		_ = (history, max_retries, skip_failures, delay_between_actions)
		result = await self.run(max_steps=self.kwargs.get('max_steps', 100))
		return result.action_results()

	async def load_and_rerun(self, history_file: str | Path | None = None, **kwargs: Any) -> list[ActionResult]:
		"""Load a saved Rust-backed Browser Use history and rerun the task."""
		if not history_file:
			history_file = 'AgentHistory.json'
		history = _load_rust_history(history_file)
		return await self.rerun_history(history, **kwargs)

	def pause(self) -> None:
		"""Pause the Rust-backed agent before the next terminal run."""
		self.state.paused = True
		self._external_pause_event.clear()

	def resume(self) -> None:
		"""Resume a paused Rust-backed agent."""
		self.state.paused = False
		self._external_pause_event.set()

	def stop(self) -> None:
		"""Stop the Rust-backed agent before the next terminal run."""
		self.state.stopped = True
		self._external_pause_event.set()

	async def close(self) -> None:
		"""Browser Use-compatible close hook.

		The Rust terminal owns browser lifecycle for managed modes, and remote CDP
		browsers are owned by the caller, so the Python wrapper has nothing to close.
		"""
		return None

	def run_sync(
		self,
		max_steps: int = 100,
		on_step_start: AgentHookFunc | None = None,
		on_step_end: AgentHookFunc | None = None,
	) -> AgentHistoryList[AgentStructuredOutput]:
		"""Synchronous wrapper around the async run method."""
		return asyncio.run(self.run(max_steps=max_steps, on_step_start=on_step_start, on_step_end=on_step_end))

	async def authenticate_cloud_sync(self, show_instructions: bool = True) -> bool:
		"""Browser Use-compatible cloud-sync hook.

		The upstream Python Agent currently reports cloud sync as unavailable.
		The Rust wrapper mirrors that contract.
		"""
		_ = show_instructions
		return False

	def get_trace_object(self) -> dict[str, Any]:
		"""Get Browser Use-style trace and trace_details data for the Rust-backed run."""

		def extract_task_website(task_text: str) -> str | None:
			match = re.search(r'https?://[^\s<>"\']+|www\.[^\s<>"\']+|[^\s<>"\']+\.[a-z]{2,}(?:/[^\s<>"\']*)?', task_text, re.IGNORECASE)
			return match.group(0) if match else None

		def json_default(value: Any) -> str:
			return str(value)

		def complete_history_without_screenshots() -> str:
			history_data = self.history.model_dump(sensitive_data=self.sensitive_data)
			for item in history_data.get('history', []):
				state = item.get('state')
				if isinstance(state, dict) and 'screenshot' in state:
					state['screenshot'] = None
			return json.dumps(history_data, default=json_default)

		trace_id = uuid7str()
		timestamp = datetime.now().isoformat()
		structured_output = self.history.structured_output
		structured_output_json = json.dumps(structured_output.model_dump(), default=json_default) if structured_output else None
		final_result = self.history.final_result()
		action_history = self.history.action_history()
		action_errors = self.history.errors()
		urls = self.history.urls()
		usage = self.history.usage

		return {
			'trace': {
				'trace_id': trace_id,
				'timestamp': timestamp,
				'browser_use_version': None,
				'git_info': None,
				'model': self.model,
				'settings': json.dumps(self.settings.model_dump(), default=json_default) if self.settings else None,
				'task_id': self.task_id,
				'task_truncated': self.task[:20000] if len(self.task) > 20000 else self.task,
				'task_website': extract_task_website(self.task),
				'structured_output_truncated': (
					structured_output_json[:20000]
					if structured_output_json and len(structured_output_json) > 20000
					else structured_output_json
				),
				'action_history_truncated': json.dumps(action_history, default=json_default) if action_history else None,
				'action_errors': json.dumps(action_errors, default=json_default) if action_errors else None,
				'urls': json.dumps(urls, default=json_default) if urls else None,
				'final_result_response_truncated': final_result[:20000] if final_result and len(final_result) > 20000 else final_result,
				'self_report_completed': 1 if self.history.is_done() else 0,
				'self_report_success': 1 if self.history.is_successful() else 0,
				'duration': self.history.total_duration_seconds(),
				'steps_taken': self.history.number_of_steps(),
				'usage': json.dumps(usage.model_dump(), default=json_default) if usage else None,
			},
			'trace_details': {
				'trace_id': trace_id,
				'timestamp': timestamp,
				'task': self.task,
				'structured_output': structured_output_json,
				'final_result_response': final_result,
				'complete_history': complete_history_without_screenshots(),
			},
		}

	def _run_argv(self, max_steps: int) -> list[str]:
		binary = find_browser_use_terminal_binary()
		return [
			binary,
			*self._state_dir_args(),
			'-c',
			f'max_turns={int(max_steps)}',
			'-c',
			f'browser_mode="{self._browser_mode()}"',
			'run-codex',
			self.task,
			'--model',
			self.model,
		]

	async def _run_process(self, argv: list[str], timeout_seconds: int | None = None) -> tuple[int, str, str]:
		proc = await asyncio.create_subprocess_exec(
			*argv,
			stdout=asyncio.subprocess.PIPE,
			stderr=asyncio.subprocess.PIPE,
			env=self._run_env(),
		)
		try:
			stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
		except TimeoutError:
			proc.kill()
			stdout, stderr = await proc.communicate()
			stdout_text = stdout.decode(errors='replace')
			stderr_text = stderr.decode(errors='replace')
			timeout_error = f'browser-use-terminal timed out after {timeout_seconds} seconds'
			return 124, stdout_text, '\n'.join(part for part in (stderr_text.strip(), timeout_error) if part)
		return proc.returncode or 0, stdout.decode(errors='replace'), stderr.decode(errors='replace')

	async def _call_callback(self, callback: AgentHookFunc | None, *args: Any) -> None:
		if callback is None:
			return
		result = callback(*args)
		if inspect.isawaitable(result):
			await result

	async def _call_done_callback(self) -> None:
		if self.register_done_callback is None or not self.history.is_done():
			return
		result = self.register_done_callback(self.history)
		if inspect.isawaitable(result):
			await result

	async def _call_new_step_callback(self) -> None:
		if self.register_new_step_callback is None or not self.history.history:
			return
		history_item = self.history.history[-1]
		step_number = history_item.metadata.step_number if history_item.metadata else len(self.history.history)
		result = self.register_new_step_callback(history_item.state, None, step_number)
		if inspect.isawaitable(result):
			await result

	def _sync_state_from_history(self) -> None:
		if not self.history.history:
			return
		metadata = self.history.history[-1].metadata
		if metadata is not None:
			self.state.n_steps = metadata.step_number

	async def _save_conversation_if_requested(self) -> None:
		if not self.settings.save_conversation_path:
			return
		conversation_dir = Path(self.settings.save_conversation_path).expanduser()
		conversation_dir.mkdir(parents=True, exist_ok=True)
		target = conversation_dir / f'conversation_{self.id}_{self.state.n_steps}.json'
		target.write_text(
			json.dumps(self._conversation_snapshot(), indent=2, default=str),
			encoding=self.settings.save_conversation_path_encoding or 'utf-8',
		)

	def _conversation_snapshot(self) -> dict[str, Any]:
		return {
			'agent': 'browser_use.rust.Agent',
			'task_id': self.task_id,
			'session_id': self.session_id,
			'model': self.model,
			'browser_mode': self._browser_mode(),
			'task': self.task,
			'final_result': self.history.final_result(),
			'is_done': self.history.is_done(),
			'is_successful': self.history.is_successful(),
			'errors': self.history.errors(),
			'urls': self.history.urls(),
			'usage': self.history.usage.model_dump() if self.history.usage else None,
			'events': self.last_events,
			'stdout': self.last_stdout,
			'stderr': self.last_stderr,
		}

	async def _should_stop_before_run(self) -> bool:
		if self.state.stopped:
			return True
		if self.register_should_stop_callback is not None:
			should_stop = self.register_should_stop_callback()
			if inspect.isawaitable(should_stop):
				should_stop = await should_stop
			if should_stop:
				self.state.stopped = True
				return True
		if self.register_external_agent_status_raise_error_callback is not None:
			should_stop = self.register_external_agent_status_raise_error_callback()
			if inspect.isawaitable(should_stop):
				should_stop = await should_stop
			if should_stop:
				self.state.stopped = True
				return True
		return False

	def _run_existing_argv(self, max_steps: int) -> list[str]:
		if not self.session_id:
			raise RustAgentError('No active Rust session. Call run() before rerunning an existing session.')
		binary = find_browser_use_terminal_binary()
		return [
			binary,
			*self._state_dir_args(),
			'-c',
			f'max_turns={int(max_steps)}',
			'-c',
			f'browser_mode="{self._browser_mode()}"',
			'run-codex-session',
			self.session_id,
			'--model',
			self.model,
		]

	def _state_dir_args(self) -> list[str]:
		state_dir = os.environ.get('BROWSER_USE_RUST_STATE_DIR')
		return ['--state-dir', state_dir] if state_dir else []

	def _browser_mode(self) -> str:
		if _extract_cdp_url(self.browser_session) or _extract_profile_cdp_url(self.browser_profile):
			return 'remote-cdp'
		value = os.environ.get('BROWSER_USE_RUST_BROWSER_MODE')
		if value:
			return value
		value = os.environ.get('BROWSER_USE_BROWSER_MODE')
		if value:
			return value
		if _extract_cloud_preference(self.browser_session, self.browser_profile):
			return 'cloud'
		headless = _extract_headless_preference(self.browser_session, self.browser_profile)
		if headless is False:
			return 'managed-headed'
		if headless is True:
			return 'managed-headless'
		return 'managed-headless'

	def _run_env(self) -> dict[str, str]:
		env = os.environ.copy()
		browser_mode = self._browser_mode()
		env['LLM_BROWSER_BROWSER_MODE'] = browser_mode
		cdp_url = _extract_cdp_url(self.browser_session) or _extract_profile_cdp_url(self.browser_profile)
		if cdp_url:
			env['BU_CDP_URL'] = cdp_url
		if self.managed_browser_env and _is_managed_browser_mode(browser_mode):
			env.update(self.managed_browser_env)
		if self.managed_browser_args and _is_managed_browser_mode(browser_mode):
			env['BU_MANAGED_BROWSER_ARGS'] = json.dumps(self.managed_browser_args)
		if self.managed_browser_profile_dir and _is_managed_browser_mode(browser_mode):
			env['BU_MANAGED_BROWSER_PROFILE'] = self.managed_browser_profile_dir
		if self.managed_browser_executable_path and _is_managed_browser_mode(browser_mode):
			env['CHROME_PATH'] = self.managed_browser_executable_path
		return env

	def _session_id_from_stdout(self, stdout: str) -> str | None:
		for line in reversed(stdout.splitlines()):
			token = line.strip().split()[-1:] or ['']
			candidate = token[0]
			if len(candidate) >= 8 and all(ch in '0123456789abcdef-' for ch in candidate.lower()):
				return candidate
		return None

	async def _load_events(self) -> list[dict[str, Any]]:
		if not self.session_id:
			return []
		binary = find_browser_use_terminal_binary()
		proc = await asyncio.create_subprocess_exec(
			binary,
			*self._state_dir_args(),
			'events',
			self.session_id,
			stdout=asyncio.subprocess.PIPE,
			stderr=asyncio.subprocess.PIPE,
			env=self._run_env(),
		)
		stdout, _stderr = await proc.communicate()
		events = []
		for line in stdout.decode(errors='replace').splitlines():
			try:
				parsed = json.loads(line)
			except json.JSONDecodeError:
				continue
			if isinstance(parsed, dict):
				events.append(parsed)
		return events
