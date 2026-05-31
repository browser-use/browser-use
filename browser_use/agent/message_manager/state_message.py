from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from io import BytesIO
from typing import Literal

from PIL import Image

from browser_use.agent.message_manager.context_builder import MessageContextBuilder
from browser_use.agent.message_manager.views import MessageManagerState
from browser_use.agent.runtime.context import BrowserContext
from browser_use.agent.runtime.skills import BrowserSkill
from browser_use.agent.views import ActionResult, AgentStepInfo
from browser_use.browser.views import PLACEHOLDER_4PX_SCREENSHOT, BrowserStateSummary
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm.messages import ContentPartImageParam, ContentPartTextParam, ImageURL, UserMessage
from browser_use.utils import is_new_tab_page, sanitize_surrogates

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
			include_recent_events=self.include_recent_events,
			max_clickable_elements_length=self.max_clickable_elements_length,
			max_history_items=self.max_history_items,
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

		return StateMessageBuild(
			message=self._message_from_typed_context(typed_context, browser_state_summary, screenshots=screenshots),
			typed_context=typed_context,
		)

	def _message_from_typed_context(
		self,
		typed_context: BrowserContext,
		browser_state_summary: BrowserStateSummary,
		*,
		screenshots: list[str],
	) -> UserMessage:
		"""Render typed context as the state message while preserving image attachments."""

		rendered_context = sanitize_surrogates(typed_context.render())
		if is_new_tab_page(browser_state_summary.url):
			screenshots = []
		screenshots = [screenshot for screenshot in screenshots if screenshot != PLACEHOLDER_4PX_SCREENSHOT]
		has_file_images = bool(self.state.read_state_images)

		if not screenshots and not has_file_images:
			return UserMessage(content=rendered_context, cache=True)

		content_parts: list[ContentPartTextParam | ContentPartImageParam] = [ContentPartTextParam(text=rendered_context)]
		content_parts.extend(self.sample_images or [])

		for index, screenshot in enumerate(screenshots):
			label = 'Current screenshot:' if index == len(screenshots) - 1 else 'Previous screenshot:'
			content_parts.append(ContentPartTextParam(text=label))
			content_parts.append(
				ContentPartImageParam(
					image_url=ImageURL(
						url=f'data:image/png;base64,{self._resize_screenshot(screenshot)}',
						media_type='image/png',
						detail=self.vision_detail_level,
					)
				)
			)

		for image_data in self.state.read_state_images:
			image_name = image_data.get('name', 'unknown')
			image_base64 = image_data.get('data', '')
			if not image_base64:
				continue
			media_type = 'image/png' if image_name.lower().endswith('.png') else 'image/jpeg'
			content_parts.append(ContentPartTextParam(text=f'Image from file: {image_name}'))
			content_parts.append(
				ContentPartImageParam(
					image_url=ImageURL(
						url=f'data:{media_type};base64,{image_base64}',
						media_type=media_type,
						detail=self.vision_detail_level,
					)
				)
			)

		return UserMessage(content=content_parts, cache=True)

	def _resize_screenshot(self, screenshot_b64: str) -> str:
		if not self.llm_screenshot_size:
			return screenshot_b64

		try:
			img_data = base64.b64decode(screenshot_b64)
			img = Image.open(BytesIO(img_data))
			if img.size == self.llm_screenshot_size:
				return screenshot_b64

			logger.info(
				'Resizing screenshot from %sx%s to %sx%s for LLM',
				img.size[0],
				img.size[1],
				self.llm_screenshot_size[0],
				self.llm_screenshot_size[1],
			)

			img_resized = img.resize(self.llm_screenshot_size, Image.Resampling.LANCZOS)
			buffer = BytesIO()
			img_resized.save(buffer, format='PNG')
			return base64.b64encode(buffer.getvalue()).decode('utf-8')
		except Exception as exc:
			logger.warning('Failed to resize screenshot: %s, using original', exc)
			return screenshot_b64
