import logging

from browser_use.agent.message_manager.service import MessageManager
from browser_use.agent.views import AgentOutput as AgentOutputModel
from browser_use.agent.views import AgentSettings, AgentState, AgentStepInfo, PlanItem
from browser_use.browser.views import BrowserStateSummary
from browser_use.llm.messages import UserMessage


class AgentPlanningMixin:
	settings: AgentSettings
	state: AgentState
	logger: logging.Logger
	_message_manager: MessageManager
	AgentOutput: type[AgentOutputModel]
	DoneAgentOutput: type[AgentOutputModel]

	def _update_plan_from_model_output(self, model_output: AgentOutputModel) -> None:
		"""Update the plan state from model output fields (current_plan_item, plan_update)."""
		if not self.settings.enable_planning:
			return

		# If model provided a new plan via plan_update, replace the current plan
		if model_output.plan_update is not None:
			self.state.plan = [PlanItem(text=step_text) for step_text in model_output.plan_update]
			self.state.current_plan_item_index = 0
			self.state.plan_generation_step = self.state.n_steps
			if self.state.plan:
				self.state.plan[0].status = 'current'
			self.logger.info(
				f'📋 Plan {"updated" if self.state.plan_generation_step else "created"} with {len(self.state.plan)} steps'
			)
			return

		# If model provided a step index update, advance the plan
		if model_output.current_plan_item is not None and self.state.plan is not None:
			new_idx = model_output.current_plan_item
			# Clamp to valid range
			new_idx = max(0, min(new_idx, len(self.state.plan) - 1))
			old_idx = self.state.current_plan_item_index

			# Mark steps between old and new as done
			for i in range(old_idx, new_idx):
				if i < len(self.state.plan) and self.state.plan[i].status in ('current', 'pending'):
					self.state.plan[i].status = 'done'

			# Mark the new step as current
			if new_idx < len(self.state.plan):
				self.state.plan[new_idx].status = 'current'

			self.state.current_plan_item_index = new_idx

	def _render_plan_description(self) -> str | None:
		"""Render the current plan as a text description for injection into agent context."""
		if not self.settings.enable_planning or self.state.plan is None:
			return None

		markers = {'done': '[x]', 'current': '[>]', 'pending': '[ ]', 'skipped': '[-]'}
		lines = []
		for i, step in enumerate(self.state.plan):
			marker = markers.get(step.status, '[ ]')
			lines.append(f'{marker} {i}: {step.text}')
		return '\n'.join(lines)

	def _inject_replan_nudge(self) -> None:
		"""Inject a replan nudge when stall detection threshold is met."""
		if not self.settings.enable_planning or self.state.plan is None:
			return
		if self.settings.planning_replan_on_stall <= 0:
			return
		if self.state.consecutive_failures >= self.settings.planning_replan_on_stall:
			msg = (
				'REPLAN SUGGESTED: You have failed '
				f'{self.state.consecutive_failures} consecutive times. '
				'Your current plan may need revision. '
				'Output a new `plan_update` with revised steps to recover.'
			)
			self.logger.info(f'📋 Replan nudge injected after {self.state.consecutive_failures} consecutive failures')
			self._message_manager._add_context_message(UserMessage(content=msg))

	def _inject_exploration_nudge(self) -> None:
		"""Nudge the agent to create a plan (or call done) after exploring without one."""
		if not self.settings.enable_planning or self.state.plan is not None:
			return
		if self.settings.planning_exploration_limit <= 0:
			return
		if self.state.n_steps >= self.settings.planning_exploration_limit:
			msg = (
				'PLANNING NUDGE: You have taken '
				f'{self.state.n_steps} steps without creating a plan. '
				'If the task is complex, output a `plan_update` with clear todo items now. '
				'If the task is already done or nearly done, call `done` instead.'
			)
			self.logger.info(f'📋 Exploration nudge injected after {self.state.n_steps} steps without a plan')
			self._message_manager._add_context_message(UserMessage(content=msg))

	def _inject_loop_detection_nudge(self) -> None:
		"""Inject an escalating nudge when behavioral loops are detected."""
		if not self.settings.loop_detection_enabled:
			return
		nudge = self.state.loop_detector.get_nudge_message()
		if nudge:
			self.logger.info(
				f'🔁 Loop detection nudge injected (repetition={self.state.loop_detector.max_repetition_count}, '
				f'stagnation={self.state.loop_detector.consecutive_stagnant_pages})'
			)
			self._message_manager._add_context_message(UserMessage(content=nudge))

	def _update_loop_detector_actions(self) -> None:
		"""Record the actions from the latest step into the loop detector."""
		if not self.settings.loop_detection_enabled:
			return
		if self.state.last_model_output is None:
			return
		# Actions to exclude: wait always hashes identically (instant false positive),
		# done is terminal, go_back is navigation recovery
		_LOOP_EXEMPT_ACTIONS = {'wait', 'done', 'go_back'}
		for action in self.state.last_model_output.action:
			action_data = action.model_dump(exclude_unset=True)
			action_name = next(iter(action_data.keys()), 'unknown')
			if action_name in _LOOP_EXEMPT_ACTIONS:
				continue
			params = action_data.get(action_name, {})
			if not isinstance(params, dict):
				params = {}
			self.state.loop_detector.record_action(action_name, params)

	def _update_loop_detector_page_state(self, browser_state_summary: BrowserStateSummary) -> None:
		"""Record the current page state for stagnation detection."""
		if not self.settings.loop_detection_enabled:
			return
		url = browser_state_summary.url or ''
		element_count = len(browser_state_summary.dom_state.selector_map) if browser_state_summary.dom_state else 0
		# Use the DOM text representation for fingerprinting
		dom_text = ''
		if browser_state_summary.dom_state:
			try:
				dom_text = browser_state_summary.dom_state.llm_representation()
			except Exception:
				dom_text = ''
		self.state.loop_detector.record_page_state(url, dom_text, element_count)

	async def _inject_budget_warning(self, step_info: AgentStepInfo | None = None) -> None:
		"""Inject a prominent budget warning when the agent has used >= 75% of its step budget.

		This gives the LLM advance notice to wrap up, save partial results, and call done
		rather than exhausting all steps with nothing saved.
		"""
		if step_info is None:
			return

		steps_used = step_info.step_number + 1  # Convert 0-indexed to 1-indexed
		budget_ratio = steps_used / step_info.max_steps

		if budget_ratio >= 0.75 and not step_info.is_last_step():
			steps_remaining = step_info.max_steps - steps_used
			pct = int(budget_ratio * 100)
			msg = (
				f'BUDGET WARNING: You have used {steps_used}/{step_info.max_steps} steps '
				f'({pct}%). {steps_remaining} steps remaining. '
				f'If the task cannot be completed in the remaining steps, prioritize: '
				f'(1) consolidate your results (save to files if the file system is in use), '
				f'(2) call done with what you have. '
				f'Partial results are far more valuable than exhausting all steps with nothing saved.'
			)
			self.logger.info(f'Step budget warning: {steps_used}/{step_info.max_steps} ({pct}%)')
			self._message_manager._add_context_message(UserMessage(content=msg))

	async def _force_done_after_last_step(self, step_info: AgentStepInfo | None = None) -> None:
		"""Handle special processing for the last step"""
		if step_info and step_info.is_last_step():
			# Add last step warning if needed
			msg = 'You reached max_steps - this is your last step. Your only tool available is the "done" tool. No other tool is available. All other tools which you see in history or examples are not available.'
			msg += '\nIf the task is not yet fully finished as requested by the user, set success in "done" to false! E.g. if not all steps are fully completed. Else success to true.'
			msg += '\nInclude everything you found out for the ultimate task in the done text.'
			self.logger.debug('Last step finishing up')
			self._message_manager._add_context_message(UserMessage(content=msg))
			self.AgentOutput = self.DoneAgentOutput

	async def _force_done_after_failure(self) -> None:
		"""Force done after failure"""
		# Create recovery message
		if self.state.consecutive_failures >= self.settings.max_failures and self.settings.final_response_after_failure:
			msg = f'You failed {self.settings.max_failures} times. Therefore we terminate the agent.'
			msg += '\nYour only tool available is the "done" tool. No other tool is available. All other tools which you see in history or examples are not available.'
			msg += '\nIf the task is not yet fully finished as requested by the user, set success in "done" to false! E.g. if not all steps are fully completed. Else success to true.'
			msg += '\nInclude everything you found out for the ultimate task in the done text.'

			self.logger.debug('Force done action, because we reached max_failures.')
			self._message_manager._add_context_message(UserMessage(content=msg))
			self.AgentOutput = self.DoneAgentOutput
