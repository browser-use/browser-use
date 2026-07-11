from __future__ import annotations

import asyncio
import inspect
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from browser_use.agent.service import Agent

from browser_use.agent.cloud_events import CreateAgentStepEvent
from browser_use.agent.message_manager.utils import save_conversation
from browser_use.agent.views import (
	ActionResult,
	AgentError,
	AgentHistory,
	AgentOutput,
	AgentStepInfo,
	BrowserStateHistory,
	PlanItem,
	StepMetadata,
)
from browser_use.browser.views import BrowserStateSummary
from browser_use.llm.messages import BaseMessage, UserMessage
from browser_use.observability import observe, observe_debug
from browser_use.utils import time_execution_async

logger = logging.getLogger(__name__)


def _prepare_demo_message(message: str, limit: int = 600) -> str:
	"""Strip and prepare a demo mode message."""
	return message.strip()


# ═══════════════════════════════════════════════════════════════════
# Phase 1: Context preparation
# ═══════════════════════════════════════════════════════════════════


class ContextPreparer:
	"""Prepares browser state, messages, and nudges for the LLM call."""

	def __init__(self, agent: Agent, pipeline: StepPipeline) -> None:
		self._agent = agent
		self._pipeline = pipeline

	async def prepare(self, step_info: AgentStepInfo | None = None) -> BrowserStateSummary:
		"""Run Phase 1: gather browser state, build messages, inject nudges."""

		self._agent.logger.debug(f'\U0001f310 Step {self._agent.state.n_steps}: Getting browser state...')
		browser_state_summary = await self._agent.browser_session.get_browser_state_summary(
			include_screenshot=True,
			include_recent_events=self._agent.include_recent_events,
		)

		if browser_state_summary.screenshot:
			self._agent.logger.debug(
				f'\U0001f4f8 Got browser state WITH screenshot, length: {len(browser_state_summary.screenshot)}'
			)
		else:
			self._agent.logger.debug('\U0001f4f8 Got browser state WITHOUT screenshot')

		await self._pipeline._check_and_update_downloads(f'Step {self._agent.state.n_steps}: after getting browser state')
		self._log_step_context(browser_state_summary)
		await self._check_stop_or_pause()

		self._agent.logger.debug(f'\U0001f4dd Step {self._agent.state.n_steps}: Updating action models...')
		await self._agent._update_action_models_for_page(browser_state_summary.url)

		page_filtered_actions = self._agent.tools.registry.get_prompt_description(browser_state_summary.url)
		self._agent.logger.debug(f'\U0001f4ac Step {self._agent.state.n_steps}: Creating state messages for context...')

		unavailable_skills_info = None
		if self._agent.skill_service is not None:
			unavailable_skills_info = await self._agent._get_unavailable_skills_info()

		plan_description = self._render_plan_description()

		self._agent.message_manager.prepare_step_state(
			browser_state_summary=browser_state_summary,
			model_output=self._agent.state.last_model_output,
			result=self._agent.state.last_result,
			step_info=step_info,
			sensitive_data=self._agent.sensitive_data,
		)

		await self._maybe_compact_messages(step_info)

		self._agent.message_manager.create_state_messages(
			browser_state_summary=browser_state_summary,
			model_output=self._agent.state.last_model_output,
			result=self._agent.state.last_result,
			step_info=step_info,
			use_vision=self._agent.settings.use_vision,
			page_filtered_actions=page_filtered_actions if page_filtered_actions else None,
			sensitive_data=self._agent.sensitive_data,
			available_file_paths=self._agent.available_file_paths,
			unavailable_skills_info=unavailable_skills_info,
			plan_description=plan_description,
			skip_state_update=True,
		)

		await self._inject_budget_warning(step_info)
		self._inject_replan_nudge()
		self._inject_exploration_nudge()
		self._update_loop_detector_page_state(browser_state_summary)
		self._inject_loop_detection_nudge()
		await self._force_done_after_last_step(step_info)
		await self._force_done_after_failure()

		return browser_state_summary

	def _log_step_context(self, browser_state_summary: BrowserStateSummary) -> None:
		url = browser_state_summary.url if browser_state_summary else ''
		url_short = url[:50] + '...' if len(url) > 50 else url
		interactive_count = len(browser_state_summary.dom_state.selector_map) if browser_state_summary else 0
		self._agent.logger.info('\n')
		self._agent.logger.info(f'\U0001f4cd Step {self._agent.state.n_steps}:')
		self._agent.logger.debug(f'Evaluating page with {interactive_count} interactive elements on: {url_short}')

	async def _check_stop_or_pause(self) -> None:
		if self._agent.register_should_stop_callback:
			if await self._agent.register_should_stop_callback():
				self._agent.logger.info('External callback requested stop')
				self._agent.state.stopped = True
				raise InterruptedError
		if self._agent.register_external_agent_status_raise_error_callback:
			if await self._agent.register_external_agent_status_raise_error_callback():
				raise InterruptedError
		if self._agent.state.stopped:
			raise InterruptedError
		if self._agent.state.paused:
			raise InterruptedError

	async def _maybe_compact_messages(self, step_info: AgentStepInfo | None = None) -> None:
		settings = self._agent.settings.message_compaction
		if not settings or not settings.enabled:
			return
		compaction_llm = settings.compaction_llm or self._agent.settings.page_extraction_llm or self._agent.llm
		await self._agent.message_manager.maybe_compact_messages(llm=compaction_llm, settings=settings, step_info=step_info)

	def _render_plan_description(self) -> str | None:
		if not self._agent.settings.enable_planning or self._agent.state.plan is None:
			return None
		markers = {'done': '[x]', 'current': '[>]', 'pending': '[ ]', 'skipped': '[-]'}
		lines = [f'{markers.get(s.status, "[ ]")} {i}: {s.text}' for i, s in enumerate(self._agent.state.plan)]
		return '\n'.join(lines)

	def _inject_replan_nudge(self) -> None:
		if not self._agent.settings.enable_planning or self._agent.state.plan is None:
			return
		if self._agent.settings.planning_replan_on_stall <= 0:
			return
		if self._agent.state.consecutive_failures >= self._agent.settings.planning_replan_on_stall:
			msg = (
				'REPLAN SUGGESTED: You have failed '
				f'{self._agent.state.consecutive_failures} consecutive times. '
				'Your current plan may need revision. Output a new `plan_update` with revised steps to recover.'
			)
			self._agent.logger.info(
				f'\U0001f4cb Replan nudge injected after {self._agent.state.consecutive_failures} consecutive failures'
			)
			self._agent.message_manager._add_context_message(UserMessage(content=msg))

	def _inject_exploration_nudge(self) -> None:
		if not self._agent.settings.enable_planning or self._agent.state.plan is not None:
			return
		if self._agent.settings.planning_exploration_limit <= 0:
			return
		if self._agent.state.n_steps >= self._agent.settings.planning_exploration_limit:
			msg = (
				'PLANNING NUDGE: You have taken '
				f'{self._agent.state.n_steps} steps without creating a plan. '
				'If the task is complex, output a `plan_update` now. '
				'If done, call `done` instead.'
			)
			self._agent.logger.info(
				f'\U0001f4cb Exploration nudge injected after {self._agent.state.n_steps} steps without a plan'
			)
			self._agent.message_manager._add_context_message(UserMessage(content=msg))

	def _inject_loop_detection_nudge(self) -> None:
		if not self._agent.settings.loop_detection_enabled:
			return
		nudge = self._agent.state.loop_detector.get_nudge_message()
		if nudge:
			self._agent.logger.info(
				f'\U0001f501 Loop nudge injected (repetition={self._agent.state.loop_detector.max_repetition_count}, '
				f'stagnation={self._agent.state.loop_detector.consecutive_stagnant_pages})'
			)
			self._agent.message_manager._add_context_message(UserMessage(content=nudge))

	def _update_loop_detector_page_state(self, browser_state_summary: BrowserStateSummary) -> None:
		if not self._agent.settings.loop_detection_enabled:
			return
		url = browser_state_summary.url or ''
		element_count = len(browser_state_summary.dom_state.selector_map) if browser_state_summary.dom_state else 0
		dom_text = ''
		if browser_state_summary.dom_state:
			try:
				dom_text = browser_state_summary.dom_state.llm_representation()
			except Exception:
				dom_text = ''
		self._agent.state.loop_detector.record_page_state(url, dom_text, element_count)

	async def _inject_budget_warning(self, step_info: AgentStepInfo | None = None) -> None:
		if step_info is None:
			return
		steps_used = step_info.step_number + 1
		budget_ratio = steps_used / step_info.max_steps
		if budget_ratio >= 0.75 and not step_info.is_last_step():
			remaining = step_info.max_steps - steps_used
			pct = int(budget_ratio * 100)
			msg = (
				f'BUDGET WARNING: {steps_used}/{step_info.max_steps} steps ({pct}%). {remaining} remaining. '
				f'Prioritize: save results, call done with what you have.'
			)
			self._agent.logger.info(f'Step budget warning: {steps_used}/{step_info.max_steps} ({pct}%)')
			self._agent.message_manager._add_context_message(UserMessage(content=msg))

	async def _force_done_after_last_step(self, step_info: AgentStepInfo | None = None) -> None:
		if step_info and step_info.is_last_step():
			msg = (
				'You reached max_steps - this is your last step. '
				'Your only tool available is the "done" tool. '
				'If the task is not fully completed, set success in "done" to false.'
			)
			self._agent.logger.debug('Last step finishing up')
			self._agent.message_manager._add_context_message(UserMessage(content=msg))
			self._agent.AgentOutput = self._agent.DoneAgentOutput

	async def _force_done_after_failure(self) -> None:
		if (
			self._agent.state.consecutive_failures >= self._agent.settings.max_failures
			and self._agent.settings.final_response_after_failure
		):
			msg = f'You failed {self._agent.settings.max_failures} times. We terminate the agent. Your only tool is "done".'
			self._agent.logger.debug('Force done after max_failures')
			self._agent.message_manager._add_context_message(UserMessage(content=msg))
			self._agent.AgentOutput = self._agent.DoneAgentOutput


# ═══════════════════════════════════════════════════════════════════
# Phase 2: LLM interaction + action execution
# ═══════════════════════════════════════════════════════════════════


class ActionPhase:
	"""Phase 2: Gets model output and executes actions."""

	def __init__(self, agent: Agent, pipeline: StepPipeline) -> None:
		self._agent = agent
		self._pipeline = pipeline

	async def execute(self, browser_state_summary: BrowserStateSummary) -> None:
		"""Run Phase 2: LLM call then action execution."""
		await self._get_next_action(browser_state_summary)
		await self._execute_actions()

	@observe_debug(ignore_input=True, name='get_next_action')
	async def _get_next_action(self, browser_state_summary: BrowserStateSummary) -> None:
		input_messages = self._agent.message_manager.get_messages()
		self._agent.logger.debug(
			f'\U0001f916 Step {self._agent.state.n_steps}: Calling LLM with {len(input_messages)} messages (model: {self._agent.llm.model})...'
		)

		try:
			model_output = await asyncio.wait_for(
				self._agent._get_model_output_with_retry(input_messages), timeout=self._agent.settings.llm_timeout
			)
		except TimeoutError:
			raise TimeoutError(f'LLM call timed out after {self._agent.settings.llm_timeout} seconds. Keep your output short.')

		self._agent.state.last_model_output = model_output
		await self._pipeline._check_stop_or_pause()
		await self._handle_post_llm_processing(browser_state_summary, input_messages)
		await self._pipeline._check_stop_or_pause()

	async def _execute_actions(self) -> None:
		if self._agent.state.last_model_output is None:
			raise ValueError('No model output to execute actions from')
		self._agent.state.last_result = await self._agent.multi_act(self._agent.state.last_model_output.action)

	async def _handle_post_llm_processing(
		self, browser_state_summary: BrowserStateSummary, input_messages: list[BaseMessage]
	) -> None:
		if self._agent.register_new_step_callback and self._agent.state.last_model_output:
			if inspect.iscoroutinefunction(self._agent.register_new_step_callback):
				await self._agent.register_new_step_callback(
					browser_state_summary, self._agent.state.last_model_output, self._agent.state.n_steps
				)
			else:
				self._agent.register_new_step_callback(
					browser_state_summary, self._agent.state.last_model_output, self._agent.state.n_steps
				)
		if self._agent.settings.save_conversation_path and self._agent.state.last_model_output:
			conversation_dir = Path(self._agent.settings.save_conversation_path)
			target = conversation_dir / f'conversation_{self._agent.id}_{self._agent.state.n_steps}.txt'
			await save_conversation(
				input_messages, self._agent.state.last_model_output, target, self._agent.settings.save_conversation_path_encoding
			)


# ═══════════════════════════════════════════════════════════════════
# Phase 3: Post-processing
# ═══════════════════════════════════════════════════════════════════


class PostProcessor:
	"""Phase 3: Handles plan updates, loop detection, and result logging."""

	def __init__(self, agent: Agent, pipeline: StepPipeline) -> None:
		self._agent = agent
		self._pipeline = pipeline

	async def execute(self) -> None:
		"""Run Phase 3: post-action processing."""
		await self._pipeline._check_and_update_downloads('after executing actions')
		if self._agent.state.last_model_output is not None:
			self._update_plan_from_model_output(self._agent.state.last_model_output)
		self._update_loop_detector_actions()
		self._update_consecutive_failures()
		self._log_completion_if_done()

	def _update_consecutive_failures(self) -> None:
		if self._agent.state.last_result and len(self._agent.state.last_result) == 1 and self._agent.state.last_result[-1].error:
			self._agent.state.consecutive_failures += 1
			self._agent.logger.debug(
				f'\U0001f504 Step {self._agent.state.n_steps}: Consecutive failures: {self._agent.state.consecutive_failures}'
			)
		elif self._agent.state.consecutive_failures > 0:
			self._agent.state.consecutive_failures = 0
			self._agent.logger.debug(f'\U0001f504 Step {self._agent.state.n_steps}: Consecutive failures reset')

	def _log_completion_if_done(self) -> None:
		if self._agent.state.last_result and len(self._agent.state.last_result) > 0 and self._agent.state.last_result[-1].is_done:
			success = self._agent.state.last_result[-1].success
			content = self._agent.state.last_result[-1].extracted_content or ''
			if success:
				self._agent.logger.info(f'\n\U0001f4c4 \033[32m Final Result:\033[0m \n{content}\n\n')
			else:
				self._agent.logger.info(f'\n\U0001f4c4 \033[31m Final Result:\033[0m \n{content}\n\n')
			if self._agent.state.last_result[-1].attachments:
				for i, fp in enumerate(self._agent.state.last_result[-1].attachments):
					self._agent.logger.info(
						f'\U0001f449 Attachment {i + 1 if len(self._agent.state.last_result[-1].attachments) > 1 else ""}: {fp}'
					)

	def _update_plan_from_model_output(self, model_output: AgentOutput) -> None:
		if not self._agent.settings.enable_planning:
			return
		if model_output.plan_update is not None:
			self._agent.state.plan = [PlanItem(text=t) for t in model_output.plan_update]
			self._agent.state.current_plan_item_index = 0
			self._agent.state.plan_generation_step = self._agent.state.n_steps
			if self._agent.state.plan:
				self._agent.state.plan[0].status = 'current'
			self._agent.logger.info(f'\U0001f4cb Plan updated with {len(self._agent.state.plan)} steps')
			return
		if model_output.current_plan_item is not None and self._agent.state.plan is not None:
			new_idx = max(0, min(model_output.current_plan_item, len(self._agent.state.plan) - 1))
			for i in range(self._agent.state.current_plan_item_index, new_idx):
				if i < len(self._agent.state.plan) and self._agent.state.plan[i].status in ('current', 'pending'):
					self._agent.state.plan[i].status = 'done'
			if new_idx < len(self._agent.state.plan):
				self._agent.state.plan[new_idx].status = 'current'
			self._agent.state.current_plan_item_index = new_idx

	def _update_loop_detector_actions(self) -> None:
		if not self._agent.settings.loop_detection_enabled or self._agent.state.last_model_output is None:
			return
		exempt = {'wait', 'done', 'go_back'}
		for action in self._agent.state.last_model_output.action:
			ad = action.model_dump(exclude_unset=True)
			name = next(iter(ad.keys()), 'unknown')
			if name in exempt:
				continue
			params = ad.get(name, {})
			self._agent.state.loop_detector.record_action(name, params if isinstance(params, dict) else {})


# ═══════════════════════════════════════════════════════════════════
# Step pipeline
# ═══════════════════════════════════════════════════════════════════


class StepPipeline:
	"""Orchestrates a single step of the agent execution loop.

	Phases:
	  0. CAPTCHA handling
	  1. Context preparation (ContextPreparer)
	  2. LLM + actions (ActionPhase)
	  3. Post-processing (PostProcessor)
	"""

	def __init__(self, agent: Agent) -> None:
		self._agent = agent
		self._step_start_time: float = 0.0
		self._step_end_time: float = 0.0
		self._context_prep = ContextPreparer(agent, self)
		self._action_phase = ActionPhase(agent, self)
		self._post_phase = PostProcessor(agent, self)

	# ── Main entry point ──────────────────────────────────────────

	@observe(name='agent.step', ignore_output=True, ignore_input=True)
	@time_execution_async('--step')
	async def execute(self, step_info: AgentStepInfo | None = None) -> None:
		"""Execute one step of the task."""
		self._step_start_time = time.time()
		browser_state_summary = None

		try:
			if self._agent.browser_session:
				await self._handle_captcha_if_needed(step_info)

			browser_state_summary = await self._context_prep.prepare(step_info)

			self._agent.state.last_model_output = None
			self._agent.state.last_result = None

			await self._action_phase.execute(browser_state_summary)
			await self._post_phase.execute()

		except Exception as e:
			await self._handle_step_error(e)
		finally:
			await self._finalize(browser_state_summary)

	# ── Phase 0: CAPTCHA ──────────────────────────────────────────

	async def _handle_captcha_if_needed(self, step_info: AgentStepInfo | None) -> None:
		try:
			captcha_wait = await self._agent.browser_session.wait_if_captcha_solving()
			if captcha_wait and captcha_wait.waited:
				self._step_start_time = time.time()
				duration_s = captcha_wait.duration_ms / 1000
				msg = f'Waited {duration_s:.1f}s for {captcha_wait.vendor} CAPTCHA. Result: {captcha_wait.result}.'
				self._agent.logger.info(f'\U0001f512 {msg}')
				result = ActionResult(long_term_memory=msg)
				if self._agent.state.last_result:
					self._agent.state.last_result.append(result)
				else:
					self._agent.state.last_result = [result]
		except Exception as e:
			self._agent.logger.warning(f'Phase 0 captcha wait failed (non-fatal): {e}')

	# ── Shared helpers called by sub-modules ──────────────────────

	async def _check_stop_or_pause(self) -> None:
		"""Check stop/pause (usable by ActionPhase without circular import)."""
		if self._agent.register_should_stop_callback and await self._agent.register_should_stop_callback():
			self._agent.logger.info('External callback requested stop')
			self._agent.state.stopped = True
			raise InterruptedError
		if (
			self._agent.register_external_agent_status_raise_error_callback
			and await self._agent.register_external_agent_status_raise_error_callback()
		):
			raise InterruptedError
		if self._agent.state.stopped or self._agent.state.paused:
			raise InterruptedError

	async def _check_and_update_downloads(self, context: str = '') -> None:
		if not self._agent.has_downloads_path:
			return
		try:
			current_downloads = self._agent.browser_session.downloaded_files
			if current_downloads != self._agent._last_known_downloads:
				self._update_available_file_paths(current_downloads)
				self._agent._last_known_downloads = current_downloads
				if context:
					self._agent.logger.debug(f'\U0001f4c1 {context}: Updated available files')
		except Exception as e:
			extra = f' {context}' if context else ''
			self._agent.logger.debug(f'\U0001f4c1 Failed to check for downloads{extra}: {type(e).__name__}: {e}')

	def _update_available_file_paths(self, downloads: list[str]) -> None:
		if not self._agent.has_downloads_path:
			return
		current_files = set(self._agent.available_file_paths or [])
		new_files = set(downloads) - current_files
		if new_files:
			self._agent.available_file_paths = list(current_files | new_files)
			self._agent.logger.info(
				f'\U0001f4c1 Added {len(new_files)} downloaded files to available_file_paths (total: {len(self._agent.available_file_paths)} files)'
			)
			for f in new_files:
				self._agent.logger.info(f'\U0001f4c4 New file available: {f}')
		else:
			self._agent.logger.debug(f'\U0001f4c1 No new downloads detected (tracking {len(current_files)} files)')

	# ── Error handling ────────────────────────────────────────────

	async def _handle_step_error(self, error: Exception) -> None:
		if isinstance(error, InterruptedError):
			msg = 'The agent was interrupted mid-step' + (f' - {error}' if str(error) else '')
			self._agent.logger.warning(f'{msg}')
			return

		if self._is_connection_like_error(error):
			if self._agent.browser_session.is_reconnecting:
				try:
					await asyncio.wait_for(
						self._agent.browser_session._reconnect_event.wait(),
						timeout=self._agent.browser_session.RECONNECT_WAIT_TIMEOUT,
					)
				except TimeoutError:
					pass
				if self._agent.browser_session.is_cdp_connected:
					self._agent.logger.info('\U0001f504 Reconnection succeeded')
					self._agent.state.last_result = [ActionResult(error=f'Connection lost and recovered: {error}')]
					return
			if self._is_browser_closed_error(error):
				self._agent.logger.warning(f'\U0001f6d1 Browser closed: {error}')
				self._agent.state.stopped = True
				self._agent._external_pause_event.set()
				return

		include_trace = self._agent.logger.isEnabledFor(logging.DEBUG)
		error_msg = AgentError.format_error(error, include_trace=include_trace)
		max_fails = self._agent.settings.max_failures + int(self._agent.settings.final_response_after_failure)
		self._agent.state.consecutive_failures += 1
		prefix = f'\u274c Failed {self._agent.state.consecutive_failures}/{max_fails}: '
		is_final = self._agent.state.consecutive_failures >= max_fails
		level = logging.ERROR if is_final else logging.WARNING
		self._agent.logger.log(level, f'{prefix}{error_msg}')
		await self._demo_mode_log(f'Step error: {error_msg}', 'error', {'step': self._agent.state.n_steps})
		self._agent.state.last_result = [ActionResult(error=error_msg)]

	def _is_connection_like_error(self, error: Exception) -> bool:
		s = str(error).lower()
		return isinstance(error, ConnectionError) or any(
			x in s
			for x in [
				'websocket connection closed',
				'connection closed',
				'browser has been closed',
				'browser closed',
				'no browser',
			]
		)

	def _is_browser_closed_error(self, error: Exception) -> bool:
		if self._agent.browser_session.is_reconnecting:
			return False
		s = str(error).lower()
		is_conn = isinstance(error, ConnectionError) or any(
			x in s
			for x in [
				'websocket connection closed',
				'connection closed',
				'browser has been closed',
				'browser closed',
				'no browser',
			]
		)
		return is_conn and self._agent.browser_session._cdp_client_root is None

	# ── Finalization ──────────────────────────────────────────────

	async def _finalize(self, browser_state_summary: BrowserStateSummary | None) -> None:
		self._step_end_time = time.time()
		if not self._agent.state.last_result:
			return

		if browser_state_summary:
			step_interval = None
			if self._agent.history.history:
				last_item = self._agent.history.history[-1]
				if last_item.metadata:
					step_interval = max(0, last_item.metadata.step_end_time - last_item.metadata.step_start_time)
			metadata = StepMetadata(
				step_number=self._agent.state.n_steps,
				step_start_time=self._step_start_time,
				step_end_time=self._step_end_time,
				step_interval=step_interval,
			)
			await self._make_history_item(
				self._agent.state.last_model_output,
				browser_state_summary,
				self._agent.state.last_result,
				metadata,
				state_message=self._agent.message_manager.last_state_message_text,
			)

		summary = self._log_step_completion_summary(self._step_start_time, self._agent.state.last_result)
		if summary:
			await self._demo_mode_log(summary, 'info', {'step': self._agent.state.n_steps})
		self._save_file_system_state()

		if browser_state_summary and self._agent.state.last_model_output:
			actions_data = [
				action.model_dump() if hasattr(action, 'model_dump') else {}
				for action in self._agent.state.last_model_output.action
			]
			event = CreateAgentStepEvent.from_agent_step(
				self._agent,
				self._agent.state.last_model_output,
				self._agent.state.last_result,
				actions_data,
				browser_state_summary,
			)
			self._agent.eventbus.dispatch(event)
		self._agent.state.n_steps += 1

	async def _make_history_item(self, model_output, browser_state_summary, result, metadata=None, state_message=None):
		if model_output:
			interacted = AgentHistory.get_interacted_element(model_output, browser_state_summary.dom_state.selector_map)
		else:
			interacted = [None]
		screenshot_path = None
		if browser_state_summary.screenshot:
			screenshot_path = await self._agent.screenshot_service.store_screenshot(
				browser_state_summary.screenshot, self._agent.state.n_steps
			)
		state_history = BrowserStateHistory(
			url=browser_state_summary.url,
			title=browser_state_summary.title,
			tabs=browser_state_summary.tabs,
			interacted_element=interacted,
			screenshot_path=screenshot_path,
		)
		self._agent.history.add_item(
			AgentHistory(
				model_output=model_output, result=result, state=state_history, metadata=metadata, state_message=state_message
			)
		)

	def _save_file_system_state(self) -> None:
		self._agent.state.file_system_state = self._agent.file_system.get_state() if self._agent.file_system else None

	def _log_step_completion_summary(self, step_start_time: float, result: list[ActionResult]) -> str | None:
		if not result:
			return None
		duration = time.time() - step_start_time
		success = sum(1 for r in result if not r.error)
		failure = len(result) - success
		parts = [f'\u2705 {success}'] if success else []
		parts.append(f'\u274c {failure}') if failure else None
		msg = f'\U0001f4cd Step {self._agent.state.n_steps}: Ran {len(result)} action{"s" if len(result) != 1 else ""} in {duration:.2f}s: {" | ".join(parts) if parts else "\u2705 0"}'
		self._agent.logger.debug(msg)
		return msg

	async def _demo_mode_log(self, message: str, level: str = 'info', metadata: dict | None = None) -> None:
		if not self._agent._demo_mode_enabled or not message or self._agent.browser_session is None:
			return
		try:
			await self._agent.browser_session.send_demo_mode_log(
				message=_prepare_demo_message(message), level=level, metadata=metadata or {}
			)
		except Exception as exc:
			self._agent.logger.debug(f'[DemoMode] Failed to send overlay log: {exc}')

	async def _broadcast_model_state(self, parsed: AgentOutput) -> None:
		if not self._agent._demo_mode_enabled:
			return
		state = parsed.current_state
		meta = {'step': self._agent.state.n_steps}
		if state.thinking:
			await self._demo_mode_log(state.thinking, 'thought', meta)
		if state.evaluation_previous_goal:
			level = (
				'success'
				if 'success' in state.evaluation_previous_goal.lower()
				else 'warning'
				if 'failure' in state.evaluation_previous_goal.lower()
				else 'info'
			)
			await self._demo_mode_log(state.evaluation_previous_goal, level, meta)
		if state.memory:
			await self._demo_mode_log(f'Memory: {state.memory}', 'info', meta)
		if state.next_goal:
			await self._demo_mode_log(f'Next goal: {state.next_goal}', 'info', meta)
