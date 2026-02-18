"""Agent task command handler."""

import logging
import os
from typing import Any

from browser_use.skill_cli.api_key import APIKeyRequired, require_api_key
from browser_use.skill_cli.sessions import SessionInfo

logger = logging.getLogger(__name__)

# Cloud-only flags that only work in remote mode
CLOUD_ONLY_FLAGS = [
	'session_id',
	'proxy_country',
	'wait',
	'stream',
	'flash',
	'keep_alive',
	'thinking',
	'start_url',
	'metadata',
	'secret',
	'allowed_domain',
	'skill_id',
	'structured_output',
	'judge',
	'judge_ground_truth',
]


async def handle(session: SessionInfo, params: dict[str, Any]) -> Any:
	"""Handle agent run command.

	Routes based on browser mode:
	- Remote mode (--browser remote): Uses Cloud API with US proxy by default
	- Local mode (default): Uses local browser-use agent
	"""
	task = params.get('task')
	if not task:
		return {'success': False, 'error': 'No task provided'}

	# Route based on browser mode
	if session.browser_mode == 'remote':
		# Remote mode requires Browser-Use API key
		try:
			require_api_key('Cloud agent tasks')
		except APIKeyRequired as e:
			return {'success': False, 'error': str(e)}
		return await _handle_cloud_task(params)
	else:
		# Check if user tried to use cloud-only flags in local mode
		used_cloud_flags = [f for f in CLOUD_ONLY_FLAGS if params.get(f)]
		if used_cloud_flags:
			from browser_use.skill_cli.install_config import is_mode_available

			flags_str = ', '.join(f'--{f.replace("_", "-")}' for f in used_cloud_flags)

			if is_mode_available('remote'):
				# Remote is available, user just needs to use it
				return {
					'success': False,
					'error': f'Cloud-only flags used in local mode: {flags_str}\nUse --browser remote to enable cloud features.',
				}
			else:
				# Remote not installed (--local-only install)
				return {
					'success': False,
					'error': f'Cloud-only flags require remote mode: {flags_str}\n'
					f'Remote mode is not installed. Reinstall to enable:\n'
					f'  curl -fsSL https://browser-use.com/cli/install.sh | bash -s -- --remote-only\n'
					f'  curl -fsSL https://browser-use.com/cli/install.sh | bash -s -- --full',
				}
		return await _handle_local_task(session, params)


async def _handle_cloud_task(params: dict[str, Any]) -> Any:
	"""Handle task execution via Cloud API.

	By default uses US proxy for all cloud tasks.
	"""
	from browser_use.skill_cli.commands import cloud_session, cloud_task

	task = params['task']

	# Handle vision flag (--vision vs --no-vision)
	vision: bool | None = None
	if params.get('vision'):
		vision = True
	elif params.get('no_vision'):
		vision = False

	# Parse key=value list params
	metadata = _parse_key_value_list(params.get('metadata'))
	secrets = _parse_key_value_list(params.get('secret'))

	# Build session params - only include what user explicitly set
	session_id = params.get('session_id')
	profile_id = params.get('profile')
	proxy_country = params.get('proxy_country')

	try:
		logger.info(f'Creating cloud task: {task}')

		# Create session first if profile or proxy specified and no session_id
		if (profile_id or proxy_country) and not session_id:
			session = cloud_session.create_session(
				profile_id=profile_id,
				proxy_country=proxy_country,
				keep_alive=params.get('keep_alive'),
			)
			session_id = session.id
			logger.info(f'Created cloud session: {session_id}')

		# Create cloud task - only pass what user explicitly set
		task_response = cloud_task.create_task(
			task=task,
			llm=params.get('llm'),
			session_id=session_id,
			max_steps=params.get('max_steps'),
			flash_mode=params.get('flash'),
			thinking=params.get('thinking'),
			vision=vision,
			start_url=params.get('start_url'),
			metadata=metadata,
			secrets=secrets,
			allowed_domains=params.get('allowed_domain'),
			skill_ids=params.get('skill_id'),
			structured_output=params.get('structured_output'),
			judge=params.get('judge'),
			judge_ground_truth=params.get('judge_ground_truth'),
		)

		task_id = task_response.id
		response_session_id = task_response.session_id

		if not task_id:
			return {
				'success': False,
				'error': 'Cloud API did not return a task ID',
				'task': task,
			}

		logger.info(f'Cloud task created: {task_id}')

		# Return immediately unless --wait is specified
		if not params.get('wait'):
			return {
				'success': True,
				'task_id': task_id,
				'session_id': response_session_id,
				'message': 'Task started. Use "browser-use task status <task_id>" to check progress.',
			}

		# Poll until complete
		logger.info('Waiting for task completion...')
		result = await cloud_task.poll_until_complete(task_id, stream=params.get('stream', False))

		return {
			'success': True,
			'task': task,
			'task_id': task_id,
			'session_id': response_session_id,
			'status': result.status,
			'output': result.output,
			'cost': result.cost,
			'done': result.status == 'finished',
		}

	except Exception as e:
		logger.exception(f'Cloud task failed: {e}')
		return {
			'success': False,
			'error': str(e),
			'task': task,
		}


def _parse_key_value_list(items: list[str] | None) -> dict[str, str | None] | None:
	"""Parse a list of 'key=value' strings into a dict."""
	if not items:
		return None
	result: dict[str, str | None] = {}
	for item in items:
		if '=' in item:
			key, value = item.split('=', 1)
			result[key] = value
	return result if result else None


async def _handle_local_task(session: SessionInfo, params: dict[str, Any]) -> Any:
	"""Handle task execution locally with browser-use agent."""
	task = params['task']
	max_steps = params.get('max_steps')
	model = params.get('llm')  # Optional model override

	try:
		# Import agent and LLM
		from browser_use.agent.service import Agent

		# Try to get LLM from environment (with optional model override)
		llm = await get_llm(model=model)
		if llm is None:
			if model:
				return {
					'success': False,
					'error': f'Could not initialize model "{model}". '
					f'Make sure the appropriate API key is set (OPENAI_API_KEY, ANTHROPIC_API_KEY, or GOOGLE_API_KEY).',
				}
			return {
				'success': False,
				'error': 'No LLM configured. Set BROWSER_USE_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY, or GOOGLE_API_KEY',
			}

		# Create and run agent
		agent = Agent(
			task=task,
			llm=llm,
			browser_session=session.browser_session,
		)

		logger.info(f'Running local agent task: {task}')
		run_kwargs = {}
		if max_steps is not None:
			run_kwargs['max_steps'] = max_steps
		result = await agent.run(**run_kwargs)

		# Extract result info
		final_result = result.final_result() if result else None

		return {
			'success': True,
			'task': task,
			'steps': len(result) if result else 0,
			'result': str(final_result) if final_result else None,
			'done': result.is_done() if result else False,
		}

	except Exception as e:
		logger.exception(f'Local agent task failed: {e}')
		return {
			'success': False,
			'error': str(e),
			'task': task,
		}


def _get_verified_models() -> dict[str, set[str]]:
	"""Extract verified model names from SDK sources of truth."""
	import typing

	from anthropic.types.model_param import ModelParam
	from openai.types.shared.chat_model import ChatModel

	from browser_use.llm.google.chat import VerifiedGeminiModels

	# OpenAI: ChatModel is a Literal type
	openai_models = set(typing.get_args(ChatModel))

	# Anthropic: ModelParam is Union[Literal[...], str] - extract the Literal
	anthropic_literal = typing.get_args(ModelParam)[0]
	anthropic_models = set(typing.get_args(anthropic_literal))

	# Google: VerifiedGeminiModels Literal
	google_models = set(typing.get_args(VerifiedGeminiModels))

	# Browser-Use: cloud models
	browser_use_models = {'bu-latest', 'bu-1-0', 'bu-2-0'}

	return {
		'openai': openai_models,
		'anthropic': anthropic_models,
		'google': google_models,
		'browser-use': browser_use_models,
	}


_VERIFIED_MODELS: dict[str, set[str]] | None = None


def _get_provider_for_model(model: str) -> str | None:
	"""Determine the provider by checking SDK verified model lists."""
	global _VERIFIED_MODELS
	if _VERIFIED_MODELS is None:
		_VERIFIED_MODELS = _get_verified_models()

	for provider, models in _VERIFIED_MODELS.items():
		if model in models:
			return provider

	return None


def get_llm(model: str | None = None) -> Any:
	"""Get LLM instance from environment configuration.

	Args:
		model: Optional model name to use. If provided, will instantiate
		       the appropriate provider for that model. If not provided,
		       auto-detects from available API keys.

	Supported providers: OpenAI, Anthropic, Google, Browser-Use.
	Model names are validated against each SDK's verified model list.
	"""
	from browser_use.llm import ChatAnthropic, ChatBrowserUse, ChatGoogle, ChatOpenAI

	if model:
		provider = _get_provider_for_model(model)

		if provider == 'openai':
			return ChatOpenAI(model=model)
		elif provider == 'anthropic':
			return ChatAnthropic(model=model)
		elif provider == 'google':
			return ChatGoogle(model=model)
		elif provider == 'browser-use':
			return ChatBrowserUse(model=model)
		else:
			logger.warning(f'Unknown model: {model}. Not in any verified model list.')
			return None

	# No model specified - auto-detect from available API keys
	if os.environ.get('BROWSER_USE_API_KEY'):
		return ChatBrowserUse()

	if os.environ.get('OPENAI_API_KEY'):
		return ChatOpenAI(model='o3')

	if os.environ.get('ANTHROPIC_API_KEY'):
		return ChatAnthropic(model='claude-sonnet-4-0')

	if os.environ.get('GOOGLE_API_KEY'):
		return ChatGoogle(model='gemini-flash-latest')

	return None
