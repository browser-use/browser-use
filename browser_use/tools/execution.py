import asyncio
import logging
import math
import os
from typing import Any

try:
	from lmnr import Laminar  # type: ignore
except ImportError:
	Laminar = None  # type: ignore

from browser_use.agent.views import ActionModel, ActionResult
from browser_use.browser import BrowserSession
from browser_use.browser.views import BrowserError
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm.base import BaseChatModel
from browser_use.observability import observe_debug
from browser_use.tools.error_handling import handle_browser_error
from browser_use.utils import time_execution_sync

logger = logging.getLogger(__name__)


# Global per-action timeout: last-resort guard against hung event handlers.
# Individual CDP calls (Page.navigate etc.) have their own shorter timeouts,
# but event-bus `await event` and `event_result()` calls have none — if a
# watchdog handler blocks on a dead CDP WebSocket, the action can hang past
# any agent-level watchdog. This cap ensures every action returns within a
# bounded window with an ActionResult(error=...) instead of hanging silently.
#
# The default (180s) sits above the longest built-in inner timeout — the extract
# action's page_extraction_llm.ainvoke at 120s — plus comfortable grace, so
# slow-but-valid LLM-backed actions aren't truncated. Override per-call via
# BROWSER_USE_ACTION_TIMEOUT_S env var or tools.act(action_timeout=...).
_ACTION_TIMEOUT_FALLBACK_S = 180.0


def _parse_env_action_timeout(raw: str | None) -> float:
	"""Parse BROWSER_USE_ACTION_TIMEOUT_S defensively.

	Accepts only finite positive values. Empty, non-numeric, inf, nan, or
	non-positive values fall back to the hardcoded default with a warning
	— these would otherwise make every action time out immediately (nan)
	or disable the hang guard entirely (inf / negative / zero).
	"""
	if raw is None or raw == '':
		return _ACTION_TIMEOUT_FALLBACK_S
	try:
		parsed = float(raw)
	except ValueError:
		logging.getLogger(__name__).warning(
			'Invalid BROWSER_USE_ACTION_TIMEOUT_S=%r; falling back to %.0fs',
			raw,
			_ACTION_TIMEOUT_FALLBACK_S,
		)
		return _ACTION_TIMEOUT_FALLBACK_S
	if not math.isfinite(parsed) or parsed <= 0:
		logging.getLogger(__name__).warning(
			'BROWSER_USE_ACTION_TIMEOUT_S=%r is not a finite positive number; falling back to %.0fs',
			raw,
			_ACTION_TIMEOUT_FALLBACK_S,
		)
		return _ACTION_TIMEOUT_FALLBACK_S
	return parsed


_DEFAULT_ACTION_TIMEOUT_S = _parse_env_action_timeout(os.getenv('BROWSER_USE_ACTION_TIMEOUT_S'))


def _coerce_valid_action_timeout(value: float | None) -> float:
	"""Normalize a caller-supplied action_timeout to a finite positive value.

	Mirrors the env-var guard so the public `tools.act(action_timeout=...)`
	override path has the same defenses: nan / inf / <=0 make actions either
	time out immediately or never, which would silently defeat the hang
	guard this module exists to provide. Fall back to the env-derived
	default with a warning instead.
	"""
	if value is None:
		return _DEFAULT_ACTION_TIMEOUT_S
	if not math.isfinite(value) or value <= 0:
		logging.getLogger(__name__).warning(
			'action_timeout=%r is not a finite positive number; falling back to %.0fs',
			value,
			_DEFAULT_ACTION_TIMEOUT_S,
		)
		return _DEFAULT_ACTION_TIMEOUT_S
	return float(value)


class ToolsExecutionMixin:
	registry: Any

	async def _execute_registered_action_result(
		self,
		*,
		action_name: str,
		params: dict,
		browser_session: BrowserSession | None,
		page_extraction_llm: BaseChatModel | None = None,
		sensitive_data: dict[str, str | dict[str, str]] | None = None,
		available_file_paths: list[str] | None = None,
		file_system: FileSystem | None = None,
		extraction_schema: dict | None = None,
		action_timeout: float | None = None,
	) -> ActionResult:
		timeout_s = _coerce_valid_action_timeout(action_timeout)

		if Laminar is not None:
			span_context = Laminar.start_as_current_span(
				name=action_name,
				input={
					'action': action_name,
					'params': params,
				},
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
				logger.error(
					f'❌ Action {action_name} hit the per-action timeout ({timeout_s:.0f}s) '
					f'— likely an unresponsive CDP connection. Returning error so the agent can recover.'
				)
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
		if isinstance(result, ActionResult):
			return result
		if result is None:
			return ActionResult()
		raise ValueError(f'Invalid action result type: {type(result)} of {result}')

	@observe_debug(ignore_input=True, ignore_output=True, name='act')
	@time_execution_sync('--act')
	async def act(
		self,
		action: ActionModel,
		browser_session: BrowserSession,
		page_extraction_llm: BaseChatModel | None = None,
		sensitive_data: dict[str, str | dict[str, str]] | None = None,
		available_file_paths: list[str] | None = None,
		file_system: FileSystem | None = None,
		extraction_schema: dict | None = None,
		action_timeout: float | None = None,
	) -> ActionResult:
		"""Execute an action.

		action_timeout: per-action wall-clock cap (seconds). Prevents actions from hanging
		indefinitely when a CDP WebSocket goes silent — a common failure mode with remote
		browsers where internal CDP calls (tab switches, lifecycle waits) have no timeouts.
		Defaults to BROWSER_USE_ACTION_TIMEOUT_S env var or 180s (above the 120s
		page_extraction_llm cap used by the `extract` action).
		"""

		for action_name, params in action.model_dump(exclude_unset=True).items():
			if params is not None:
				return await self._execute_registered_action_result(
					action_name=action_name,
					params=params,
					browser_session=browser_session,
					page_extraction_llm=page_extraction_llm,
					file_system=file_system,
					sensitive_data=sensitive_data,
					available_file_paths=available_file_paths,
					extraction_schema=extraction_schema,
					action_timeout=action_timeout,
				)
		return ActionResult()

	def __getattr__(self, name: str):
		"""
		Enable direct action calls like tools.navigate(url=..., browser_session=...).
		This provides a simpler API for tests and direct usage while maintaining backward compatibility.
		"""
		if name in self.registry.registry.actions:
			action = self.registry.registry.actions[name]

			async def action_wrapper(**kwargs):
				browser_session = kwargs.get('browser_session')

				special_param_names = {
					'browser_session',
					'page_extraction_llm',
					'file_system',
					'available_file_paths',
					'sensitive_data',
					'extraction_schema',
					'action_timeout',
				}

				action_params = {k: v for k, v in kwargs.items() if k not in special_param_names}
				special_kwargs = {k: v for k, v in kwargs.items() if k in special_param_names}

				validated_params = action.param_model(**action_params)

				return await self._execute_registered_action_result(
					action_name=name,
					params=validated_params.model_dump(),
					browser_session=browser_session,
					page_extraction_llm=special_kwargs.get('page_extraction_llm'),
					file_system=special_kwargs.get('file_system'),
					sensitive_data=special_kwargs.get('sensitive_data'),
					available_file_paths=special_kwargs.get('available_file_paths'),
					extraction_schema=special_kwargs.get('extraction_schema'),
					action_timeout=special_kwargs.get('action_timeout'),
				)

			return action_wrapper

		raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
