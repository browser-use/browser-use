"""Agent action execution with page-change guards."""

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from browser_use.agent.llm_debug_trace import append_tool_debug_trace
from browser_use.agent.runtime.tools import NativeToolCall, NativeToolResult, NativeToolRouter
from browser_use.agent.runtime.views import BrowserAgentSession, ToolContext
from browser_use.agent.views import ActionResult, AgentSettings, AgentState
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm.messages import ToolCall
from browser_use.observability import observe_debug
from browser_use.tools.registry.views import ActionModel
from browser_use.tools.service import Tools
from browser_use.utils import time_execution_async


class AgentActionExecutionMixin:
	agent_directory: Any
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
	runtime_session: BrowserAgentSession
	session_id: str
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
			tool_call_id = f'legacy-{self.state.n_steps}-{i + 1}'
			action_arguments = action_data.get(action_name, {}) if isinstance(action_data, dict) else {}

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
				tool_start_time = time.perf_counter()
				await append_tool_debug_trace(
					agent_directory=self.agent_directory,
					logger=self.logger,
					event='tool_call_start',
					step=self.state.n_steps,
					session_id=self.session_id,
					tool_name=action_name,
					tool_call_id=tool_call_id,
					arguments=action_arguments,
					browser_session=self.browser_session,
				)

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
				await append_tool_debug_trace(
					agent_directory=self.agent_directory,
					logger=self.logger,
					event='tool_call_result',
					step=self.state.n_steps,
					session_id=self.session_id,
					tool_name=action_name,
					tool_call_id=tool_call_id,
					arguments=action_arguments,
					action_result=result,
					duration_ms=(time.perf_counter() - tool_start_time) * 1000,
					browser_session=self.browser_session,
				)

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
				await append_tool_debug_trace(
					agent_directory=self.agent_directory,
					logger=self.logger,
					event='tool_call_error',
					step=self.state.n_steps,
					session_id=self.session_id,
					tool_name=action_name,
					tool_call_id=tool_call_id,
					arguments=action_arguments,
					error=e,
					browser_session=self.browser_session,
				)
				results.append(ActionResult(error=f'{type(e).__name__}: {e}'))
				return results

		return results

	@observe_debug(ignore_input=True, ignore_output=True)
	@time_execution_async('--multi_act_native')
	async def multi_act_native(self, tool_calls: list[ToolCall]) -> tuple[list[ActionResult], list[NativeToolResult]]:
		"""Execute provider-native tool calls as the primary action path."""
		results: list[ActionResult] = []
		native_results: list[NativeToolResult] = []
		router = NativeToolRouter.from_tools(self.tools, include_experimental=True)
		total_actions = len(tool_calls)

		for i, provider_tool_call in enumerate(tool_calls):
			call: NativeToolCall | None = None
			definition_name = getattr(getattr(provider_tool_call, 'function', None), 'name', 'unknown')
			try:
				await self._check_stop_or_pause()
				call = self._native_tool_call_from_provider(provider_tool_call)
				definition = router.resolve(call.tool_name)
				definition_name = definition.name
				await self._log_native_tool_call(definition.name, call, i + 1, total_actions)
				tool_start_time = time.perf_counter()
				await append_tool_debug_trace(
					agent_directory=self.agent_directory,
					logger=self.logger,
					event='tool_call_start',
					step=self.state.n_steps,
					session_id=self.session_id,
					tool_name=definition.name,
					tool_call_id=call.call_id,
					arguments=call.arguments,
					provider_tool_call=provider_tool_call,
					browser_session=self.browser_session,
				)

				pre_action_url = None
				pre_action_focus = None
				if self.browser_session is not None and definition.name != 'browser.done':
					pre_action_url = await self.browser_session.get_current_page_url()
					pre_action_focus = self.browser_session.agent_focus_target_id

				native_result = await router.execute(call, self._build_native_tool_context())
				native_results.append(native_result)
				action_result = self._action_result_from_native_tool_result(native_result)
				results.append(action_result)
				await append_tool_debug_trace(
					agent_directory=self.agent_directory,
					logger=self.logger,
					event='tool_call_result',
					step=self.state.n_steps,
					session_id=self.session_id,
					tool_name=definition.name,
					tool_call_id=call.call_id,
					arguments=call.arguments,
					provider_tool_call=provider_tool_call,
					result=native_result,
					action_result=action_result,
					duration_ms=(time.perf_counter() - tool_start_time) * 1000,
					browser_session=self.browser_session,
				)

				if action_result.error:
					await self._demo_mode_log(
						f'Action "{definition.name}" failed: {action_result.error}',
						'error',
						{'action': definition.name, 'step': self.state.n_steps},
					)
				elif action_result.is_done:
					completion_text = action_result.long_term_memory or action_result.extracted_content or 'Task marked as done.'
					level = 'success' if action_result.success is not False else 'warning'
					await self._demo_mode_log(
						completion_text,
						level,
						{'action': definition.name, 'step': self.state.n_steps},
					)

				if action_result.is_done or action_result.error or definition.terminates_sequence or i == total_actions - 1:
					break

				if self.browser_session is not None and pre_action_url is not None:
					post_action_url = await self.browser_session.get_current_page_url()
					post_action_focus = self.browser_session.agent_focus_target_id
					if post_action_url != pre_action_url or post_action_focus != pre_action_focus:
						self.logger.info(
							f'Page changed after "{definition.name}" — skipping {total_actions - i - 1} remaining action(s)'
						)
						break

				if i < total_actions - 1:
					self.logger.debug(f'Waiting {self.browser_profile.wait_between_actions} seconds between actions')
					await asyncio.sleep(self.browser_profile.wait_between_actions)
			except Exception as e:
				if isinstance(e, InterruptedError):
					raise
				if self._is_connection_like_error(e):
					raise
				self.logger.error(f'❌ Executing native tool call {i + 1} failed -> {type(e).__name__}: {e}')
				await append_tool_debug_trace(
					agent_directory=self.agent_directory,
					logger=self.logger,
					event='tool_call_error',
					step=self.state.n_steps,
					session_id=self.session_id,
					tool_name=definition_name,
					tool_call_id=call.call_id if call is not None else getattr(provider_tool_call, 'id', None),
					arguments=call.arguments if call is not None else {},
					provider_tool_call=provider_tool_call,
					error=e,
					browser_session=self.browser_session,
				)
				results.append(ActionResult(error=f'{type(e).__name__}: {e}'))
				return results, native_results

		return results, native_results

	def _build_native_tool_context(self) -> ToolContext:
		return ToolContext(
			run_id=self.runtime_session.run_id,
			turn_id=f'step-{self.state.n_steps}',
			browser_session=self.browser_session,
			tools=self.tools,
			llm=getattr(self, 'llm', None),
			page_extraction_llm=self.settings.page_extraction_llm,
			file_system=self.file_system,
			sensitive_data=self.sensitive_data,
			available_file_paths=self.available_file_paths,
			extraction_schema=self.extraction_schema,
			action_timeout=self.settings.step_timeout,
			artifact_store=self.runtime_session.artifact_store,
			event_stream=self.runtime_session.event_stream,
		)

	def _native_tool_call_from_provider(self, provider_tool_call: ToolCall) -> NativeToolCall:
		try:
			arguments = json.loads(provider_tool_call.function.arguments or '{}')
		except json.JSONDecodeError as exc:
			raise ValueError(f'Invalid JSON arguments for native tool {provider_tool_call.function.name}: {exc}') from exc
		if not isinstance(arguments, dict):
			raise ValueError(f'Native tool {provider_tool_call.function.name} arguments must be a JSON object.')
		return NativeToolCall(
			tool_name=provider_tool_call.function.name,
			arguments=arguments,
			call_id=provider_tool_call.id,
		)

	def _action_result_from_native_tool_result(self, native_result: NativeToolResult) -> ActionResult:
		if native_result.action_result is not None:
			return native_result.action_result

		metadata = {
			'native_tool_result': native_result.model_dump(
				mode='json',
				exclude={'action_result'},
				exclude_none=True,
			)
		}
		if native_result.is_error:
			return ActionResult(
				error=native_result.content or f'Native tool {native_result.tool_name} failed.', metadata=metadata
			)
		return ActionResult(extracted_content=native_result.content, metadata=metadata)

	async def _log_native_tool_call(
		self,
		tool_name: str,
		call: NativeToolCall,
		action_num: int,
		total_actions: int,
	) -> None:
		blue = '\033[34m'
		magenta = '\033[35m'
		reset = '\033[0m'
		action_header = (
			f'▶️  [{action_num}/{total_actions}] {blue}{tool_name}{reset}:'
			if total_actions > 1
			else f'▶️   {blue}{tool_name}{reset}:'
		)

		param_parts = []
		for param_name, value in call.arguments.items():
			if isinstance(value, str) and len(value) > 150:
				display_value = value[:150] + '...'
			elif isinstance(value, list) and len(str(value)) > 200:
				display_value = str(value)[:200] + '...'
			else:
				display_value = value
			param_parts.append(f'{magenta}{param_name}{reset}: {display_value}')

		params_string = ', '.join(param_parts)
		self.logger.info(f'  {action_header} {params_string}' if params_string else f'  {action_header}')

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
