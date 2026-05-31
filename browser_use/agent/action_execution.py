"""Agent action execution with page-change guards."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from browser_use.agent.views import ActionResult, AgentSettings, AgentState
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.filesystem.file_system import FileSystem
from browser_use.observability import observe_debug
from browser_use.tools.registry.views import ActionModel
from browser_use.tools.service import Tools
from browser_use.utils import time_execution_async


class AgentActionExecutionMixin:
	available_file_paths: list[str] | None
	browser_profile: BrowserProfile
	browser_session: BrowserSession | None
	extraction_schema: dict | None
	file_system: FileSystem
	logger: logging.Logger
	sensitive_data: dict[str, str | dict[str, str]] | None
	settings: AgentSettings
	state: AgentState
	tools: Tools[Any]
	_demo_mode_enabled: bool
	_check_stop_or_pause: Callable[[], Awaitable[None]]
	_demo_mode_log: Callable[[str, str, dict[str, Any]], Awaitable[None]]
	_is_connection_like_error: Callable[[Exception], bool]

	@observe_debug(ignore_input=True, ignore_output=True)
	@time_execution_async('--multi_act')
	async def multi_act(self, actions: list[ActionModel]) -> list[ActionResult]:
		"""Execute multiple actions with page-change guards."""
		results: list[ActionResult] = []
		total_actions = len(actions)

		assert self.browser_session is not None, 'BrowserSession is not set up'
		try:
			if (
				self.browser_session._cached_browser_state_summary is not None
				and self.browser_session._cached_browser_state_summary.dom_state is not None
			):
				cached_selector_map = dict(self.browser_session._cached_browser_state_summary.dom_state.selector_map)
			else:
				cached_selector_map = {}
		except Exception as e:
			self.logger.error(f'Error getting cached selector map: {e}')
			cached_selector_map = {}

		for i, action in enumerate(actions):
			action_data = action.model_dump(exclude_unset=True)
			action_name = next(iter(action_data.keys())) if action_data else 'unknown'

			if i > 0 and action_data.get('done') is not None:
				msg = f'Done action is allowed only as a single action - stopped after action {i} / {total_actions}.'
				self.logger.debug(msg)
				break

			if i > 0:
				self.logger.debug(f'Waiting {self.browser_profile.wait_between_actions} seconds between actions')
				await asyncio.sleep(self.browser_profile.wait_between_actions)

			try:
				await self._check_stop_or_pause()
				await self._log_action(action, action_name, i + 1, total_actions)

				pre_action_url = await self.browser_session.get_current_page_url()
				pre_action_focus = self.browser_session.agent_focus_target_id

				result = await self.tools.act(
					action=action,
					browser_session=self.browser_session,
					file_system=self.file_system,
					page_extraction_llm=self.settings.page_extraction_llm,
					sensitive_data=self.sensitive_data,
					available_file_paths=self.available_file_paths,
					extraction_schema=self.extraction_schema,
				)

				if result.error:
					await self._demo_mode_log(
						f'Action "{action_name}" failed: {result.error}',
						'error',
						{'action': action_name, 'step': self.state.n_steps},
					)
				elif result.is_done:
					completion_text = result.long_term_memory or result.extracted_content or 'Task marked as done.'
					level = 'success' if result.success is not False else 'warning'
					await self._demo_mode_log(
						completion_text,
						level,
						{'action': action_name, 'step': self.state.n_steps},
					)

				results.append(result)

				if results[-1].is_done or results[-1].error or i == total_actions - 1:
					break

				registered_action = self.tools.registry.registry.actions.get(action_name)
				if registered_action and registered_action.terminates_sequence:
					self.logger.info(
						f'Action "{action_name}" terminates sequence — skipping {total_actions - i - 1} remaining action(s)'
					)
					break

				post_action_url = await self.browser_session.get_current_page_url()
				post_action_focus = self.browser_session.agent_focus_target_id

				if post_action_url != pre_action_url or post_action_focus != pre_action_focus:
					self.logger.info(f'Page changed after "{action_name}" — skipping {total_actions - i - 1} remaining action(s)')
					break

			except Exception as e:
				if isinstance(e, InterruptedError):
					raise
				if self._is_connection_like_error(e):
					raise
				self.logger.error(f'❌ Executing action {i + 1} failed -> {type(e).__name__}: {e}')
				await self._demo_mode_log(
					f'Action "{action_name}" raised {type(e).__name__}: {e}',
					'error',
					{'action': action_name, 'step': self.state.n_steps},
				)
				results.append(ActionResult(error=f'{type(e).__name__}: {e}'))
				return results

		return results

	async def _log_action(self, action: ActionModel, action_name: str, action_num: int, total_actions: int) -> None:
		"""Log the action before execution with colored formatting."""
		blue = '\033[34m'
		magenta = '\033[35m'
		reset = '\033[0m'

		if total_actions > 1:
			action_header = f'▶️  [{action_num}/{total_actions}] {blue}{action_name}{reset}:'
			plain_header = f'▶️  [{action_num}/{total_actions}] {action_name}:'
		else:
			action_header = f'▶️   {blue}{action_name}{reset}:'
			plain_header = f'▶️  {action_name}:'

		action_data = action.model_dump(exclude_unset=True)
		params = action_data.get(action_name, {})

		param_parts = []
		plain_param_parts = []

		if params and isinstance(params, dict):
			for param_name, value in params.items():
				if isinstance(value, str) and len(value) > 150:
					display_value = value[:150] + '...'
				elif isinstance(value, list) and len(str(value)) > 200:
					display_value = str(value)[:200] + '...'
				else:
					display_value = value

				param_parts.append(f'{magenta}{param_name}{reset}: {display_value}')
				plain_param_parts.append(f'{param_name}: {display_value}')

		if param_parts:
			params_string = ', '.join(param_parts)
			self.logger.info(f'  {action_header} {params_string}')
		else:
			self.logger.info(f'  {action_header}')

		if self._demo_mode_enabled:
			panel_message = plain_header
			if plain_param_parts:
				panel_message = f'{panel_message} {", ".join(plain_param_parts)}'
			await self._demo_mode_log(panel_message.strip(), 'action', {'action': action_name, 'step': self.state.n_steps})
