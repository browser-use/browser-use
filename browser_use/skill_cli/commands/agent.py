"""Agent task command handler."""

import logging
import os
from typing import Any

from browser_use.skill_cli.api_key import APIKeyRequired, require_api_key
from browser_use.skill_cli.sessions import SessionInfo

logger = logging.getLogger(__name__)


async def handle(session: SessionInfo, params: dict[str, Any]) -> Any:
	"""Handle agent run command.

	Requires API key for LLM access.
	Runs a browser-use agent with the given task.
	"""
	task = params.get('task')
	max_steps = params.get('max_steps', 100)

	if not task:
		return {'success': False, 'error': 'No task provided'}

	# Check API key for LLM access
	try:
		api_key = require_api_key('Agent tasks')
	except APIKeyRequired as e:
		return {'success': False, 'error': str(e)}

	try:
		# Import agent and LLM
		from browser_use.agent.service import Agent

		# Try to get LLM from environment
		llm = await get_llm()
		if llm is None:
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

		logger.info(f'Running agent task: {task}')
		result = await agent.run(max_steps=max_steps)

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
		logger.exception(f'Agent task failed: {e}')
		return {
			'success': False,
			'error': str(e),
			'task': task,
		}


async def get_llm() -> Any:
	"""Get LLM instance from environment configuration."""
	# Try ChatBrowserUse first (optimized for browser automation)
	if os.environ.get('BROWSER_USE_API_KEY'):
		try:
			from browser_use.llm import ChatBrowserUse

			return ChatBrowserUse()  # type: ignore[return-value]
		except ImportError:
			pass

	# Try OpenAI
	if os.environ.get('OPENAI_API_KEY'):
		try:
			from langchain_openai import ChatOpenAI  # type: ignore[import-not-found]

			return ChatOpenAI(model='gpt-4o')  # type: ignore[return-value]
		except ImportError:
			pass

	# Try Anthropic
	if os.environ.get('ANTHROPIC_API_KEY'):
		try:
			from langchain_anthropic import ChatAnthropic  # type: ignore[import-not-found]

			return ChatAnthropic(model='claude-sonnet-4-20250514')  # type: ignore[return-value]
		except ImportError:
			pass

	# Try Google
	if os.environ.get('GOOGLE_API_KEY'):
		try:
			from langchain_google_genai import ChatGoogleGenerativeAI  # type: ignore[import-not-found]

			return ChatGoogleGenerativeAI(model='gemini-2.0-flash')  # type: ignore[return-value]
		except ImportError:
			pass

	# Try to use browser-use's default LLM setup
	try:
		from browser_use.llm import get_default_llm

		return get_default_llm()  # type: ignore[return-value]
	except Exception:
		pass

	return None
