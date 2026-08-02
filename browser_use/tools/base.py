"""BaseToolset — abstract interface for tool collections.

Defines the contract that all tool collections (browser built-in, custom user, test mocks) must satisfy.
Agent depends on this interface, not on concrete implementations.
"""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Any, Generic, TypeVar

try:
	from lmnr import Laminar  # type: ignore
except ImportError:
	Laminar = None  # type: ignore

from pydantic import BaseModel

from browser_use.agent.views import ActionResult
from browser_use.browser.views import BrowserError
from browser_use.observability import observe_debug
from browser_use.tools.registry.service import Registry
from browser_use.tools.registry.views import ActionModel
from browser_use.utils import time_execution_async

Context = TypeVar('Context')

T = TypeVar('T', bound=BaseModel)

logger = logging.getLogger(__name__)

_ACTION_TIMEOUT_FALLBACK_S = 180.0


def _coerce_valid_action_timeout(value: float | None, default_timeout: float | None = None) -> float:
	"""Normalize action_timeout to a finite positive value.

	If value is None, falls back to default_timeout or the hardcoded fallback.
	Rejects nan/inf/<=0 with a warning.  The fallback itself is also validated
	so that invalid :class:`BaseToolset` subclass config cannot bypass the guard.
	"""
	if value is not None:
		if math.isfinite(value) and value > 0:
			return float(value)
		logger.warning(
			'action_timeout=%r is not a finite positive number; falling back to %.0fs',
			value,
			default_timeout or _ACTION_TIMEOUT_FALLBACK_S,
		)

	# Validate the fallback too — a BaseToolset subclass could pass nan/inf/<=0
	fallback = default_timeout if default_timeout is not None else _ACTION_TIMEOUT_FALLBACK_S
	if math.isfinite(fallback) and fallback > 0:
		return float(fallback)

	logger.warning(
		'default_timeout=%r is not a finite positive number; using hardcoded fallback %.0fs',
		fallback,
		_ACTION_TIMEOUT_FALLBACK_S,
	)
	return _ACTION_TIMEOUT_FALLBACK_S


def handle_browser_error(e: BrowserError) -> ActionResult:
	"""Handle BrowserError with structured long_term_memory/short_term_memory fields.

	If the error has long_term_memory set, that message is propagated directly
	to the LLM. Otherwise the error is re-raised because it lacks the context
	needed for the agent to recover.
	"""
	if e.long_term_memory is not None:
		if e.short_term_memory is not None:
			return ActionResult(
				extracted_content=e.short_term_memory,
				error=e.long_term_memory,
				include_extracted_content_only_once=True,
			)
		return ActionResult(error=e.long_term_memory)
	logger.warning(
		'⚠️ A BrowserError was raised without long_term_memory - '
		'always set long_term_memory when raising BrowserError to propagate right messages to LLM.'
	)
	raise e


class BaseToolset(Generic[Context]):
	"""Abstract tool collection.

	Subclasses must populate *registry* with actions.
	"""

	def __init__(self, exclude_actions: list[str] | None = None, default_action_timeout: float | None = None) -> None:
		self.registry: Registry[Context] = Registry[Context](exclude_actions or [])
		self._output_model: type[BaseModel] | None = None
		self._default_action_timeout: float | None = default_action_timeout

	# ── Action model ──────────────────────────────────────────────

	def get_action_model(self) -> type[ActionModel]:
		"""Return a Pydantic model that unions every registered action's param model."""
		return self.registry.create_action_model()

	def get_output_model(self) -> type[BaseModel] | None:
		"""Return the structured output model, if one was configured."""
		return self._output_model

	# ── Registration ──────────────────────────────────────────────

	def action(self, description: str, **kwargs: Any) -> Any:
		"""Decorator: register a callable as an action."""
		return self.registry.action(description, **kwargs)

	def exclude_action(self, action_name: str) -> None:
		"""Remove an action from the toolset."""
		self.registry.exclude_action(action_name)

	# ── Execution ─────────────────────────────────────────────────

	@observe_debug(ignore_input=True, ignore_output=True, name='act')
	@time_execution_async('--act')
	async def act(
		self,
		action: ActionModel,
		browser_session: Any | None = None,
		page_extraction_llm: Any | None = None,
		file_system: Any | None = None,
		available_file_paths: list[str] | None = None,
		sensitive_data: dict[str, str | dict[str, str]] | None = None,
		extraction_schema: dict | None = None,
		action_timeout: float | None = None,
	) -> ActionResult:
		"""Execute a single action through the registry."""
		timeout_s = _coerce_valid_action_timeout(action_timeout, self._default_action_timeout)

		for action_name, params in action.model_dump(exclude_unset=True).items():
			if params is not None:
				if Laminar is not None:
					span_context = Laminar.start_as_current_span(
						name=action_name,
						input={'action': action_name, 'params': params},
						span_type='TOOL',
					)
				else:
					from contextlib import nullcontext

					span_context = nullcontext()

				with span_context:
					try:
						result = await asyncio.wait_for(
							self.registry.execute_action(
								action_name=action_name,
								params=params,
								browser_session=browser_session,
								page_extraction_llm=page_extraction_llm,
								file_system=file_system,
								sensitive_data=sensitive_data,
								available_file_paths=available_file_paths,
								extraction_schema=extraction_schema,
							),
							timeout=timeout_s,
						)
					except BrowserError as e:
						logger.error(f'❌ Action {action_name} failed with BrowserError: {str(e)}')
						result = handle_browser_error(e)
					except TimeoutError:
						logger.error(f'❌ Action {action_name} hit the per-action timeout ({timeout_s:.0f}s)')
						result = ActionResult(
							error=(
								f'Action {action_name} timed out after {timeout_s:.0f}s. '
								f'The browser may be unresponsive (dead CDP WebSocket). '
								f'Try again or a different approach.'
							)
						)
					except Exception as e:
						logger.error(f"Action '{action_name}' failed with error: {str(e)}")
						result = ActionResult(error=str(e))

					if Laminar is not None:
						Laminar.set_span_output(result)

				if isinstance(result, str):
					return ActionResult(extracted_content=result)
				elif isinstance(result, ActionResult):
					return result
				elif result is None:
					return ActionResult()
				else:
					raise ValueError(f'Invalid action result type: {type(result)} of {result}')
		return ActionResult()

	# ── Prompt description ────────────────────────────────────────

	def get_prompt_description(self, page_url: str | None = None) -> str:
		"""Describe available actions for the LLM prompt."""
		return self.registry.registry.get_prompt_description(page_url)
