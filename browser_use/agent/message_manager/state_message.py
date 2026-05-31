from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from browser_use.agent.message_manager.context_builder import MessageContextBuilder, render_runtime_skills_info
from browser_use.agent.message_manager.history import render_agent_history_description
from browser_use.agent.message_manager.views import MessageManagerState
from browser_use.agent.prompts import AgentMessagePrompt
from browser_use.agent.runtime.context import BrowserContext
from browser_use.agent.runtime.skills import BrowserSkill
from browser_use.agent.views import ActionResult, AgentStepInfo
from browser_use.browser.views import BrowserStateSummary
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm.messages import ContentPartImageParam, ContentPartTextParam, UserMessage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StateMessageBuild:
	"""Rendered model input and its typed context mirror for one agent step."""

	message: UserMessage
	typed_context: BrowserContext


def should_include_screenshot(
	use_vision: bool | Literal['auto'],
	result: list[ActionResult] | None,
) -> bool:
	"""Return whether the current screenshot should be sent to the LLM."""

	if use_vision is True:
		return True
	if use_vision is False:
		return False

	if result is None:
		return False

	for action_result in result:
		if action_result.metadata and action_result.metadata.get('include_screenshot'):
			logger.debug('Screenshot inclusion requested by action result')
			return True

	return False


@dataclass(frozen=True)
class StateMessageBuilder:
	"""Builds the model-visible state message for the next LLM call."""

	task: str
	state: MessageManagerState
	file_system: FileSystem
	include_attributes: list[str]
	sensitive_data_description: str = ''
	max_history_items: int | None = None
	vision_detail_level: Literal['auto', 'low', 'high'] = 'auto'
	include_recent_events: bool = False
	sample_images: list[ContentPartTextParam | ContentPartImageParam] | None = None
	llm_screenshot_size: tuple[int, int] | None = None
	max_clickable_elements_length: int = 40000

	def build_typed_context(
		self,
		browser_state_summary: BrowserStateSummary | None = None,
		*,
		page_filtered_actions: str | None = None,
		available_file_paths: list[str] | None = None,
		unavailable_skills_info: str | None = None,
		selected_runtime_skills: list[BrowserSkill] | None = None,
		plan_description: str | None = None,
		step_info: AgentStepInfo | None = None,
	) -> BrowserContext:
		"""Build a typed mirror of the model context for observability and migration."""

		builder = MessageContextBuilder(
			task=self.task,
			state=self.state,
			file_system=self.file_system,
			include_attributes=self.include_attributes,
			sensitive_data_description=self.sensitive_data_description,
		)
		return builder.build(
			browser_state_summary,
			page_filtered_actions=page_filtered_actions,
			available_file_paths=available_file_paths,
			unavailable_skills_info=unavailable_skills_info,
			selected_runtime_skills=selected_runtime_skills,
			plan_description=plan_description,
			step_info=step_info,
		)

	def build(
		self,
		browser_state_summary: BrowserStateSummary,
		*,
		result: list[ActionResult] | None = None,
		step_info: AgentStepInfo | None = None,
		use_vision: bool | Literal['auto'] = True,
		page_filtered_actions: str | None = None,
		available_file_paths: list[str] | None = None,
		unavailable_skills_info: str | None = None,
		selected_runtime_skills: list[BrowserSkill] | None = None,
		plan_description: str | None = None,
	) -> StateMessageBuild:
		"""Build the user message sent to the model and its typed context mirror."""

		typed_context = self.build_typed_context(
			browser_state_summary,
			page_filtered_actions=page_filtered_actions,
			available_file_paths=available_file_paths,
			unavailable_skills_info=unavailable_skills_info,
			selected_runtime_skills=selected_runtime_skills,
			plan_description=plan_description,
			step_info=step_info,
		)

		screenshots: list[str] = []
		if should_include_screenshot(use_vision, result) and browser_state_summary.screenshot:
			screenshots.append(browser_state_summary.screenshot)

		message = AgentMessagePrompt(
			browser_state_summary=browser_state_summary,
			file_system=self.file_system,
			agent_history_description=render_agent_history_description(self.state, self.max_history_items),
			read_state_description=self.state.read_state_description,
			task=self.task,
			include_attributes=self.include_attributes,
			step_info=step_info,
			page_filtered_actions=page_filtered_actions,
			max_clickable_elements_length=self.max_clickable_elements_length,
			sensitive_data=self.sensitive_data_description,
			available_file_paths=available_file_paths,
			screenshots=screenshots,
			vision_detail_level=self.vision_detail_level,
			include_recent_events=self.include_recent_events,
			sample_images=self.sample_images,
			read_state_images=self.state.read_state_images,
			llm_screenshot_size=self.llm_screenshot_size,
			unavailable_skills_info=unavailable_skills_info,
			runtime_skills_info=render_runtime_skills_info(selected_runtime_skills or []),
			plan_description=plan_description,
		).get_user_message(use_vision=bool(screenshots))

		return StateMessageBuild(message=message, typed_context=typed_context)
