from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from browser_use.agent.message_manager.views import MessageManagerState
from browser_use.agent.runtime.context import (
	AgentStateItem,
	BrowserContext,
	BrowserStateItem,
	CompactionItem,
	ContextItem,
	ExtractionArtifactItem,
	PageActionsItem,
	ScreenshotItem,
	SkillItem,
	StepInfoItem,
	TaskItem,
	ToolResultItem,
	UserSteerItem,
	WarningItem,
)
from browser_use.agent.runtime.skills import BrowserSkill
from browser_use.agent.views import AgentStepInfo
from browser_use.browser.views import BrowserStateSummary
from browser_use.filesystem.file_system import FileSystem

logger = logging.getLogger(__name__)


def _strip_known_xml_tag(text: str, tag: str) -> str:
	prefix = f'<{tag}>'
	suffix = f'</{tag}>'
	text = text.strip()
	if text.startswith(prefix) and text.endswith(suffix):
		return text[len(prefix) : -len(suffix)].strip()
	return text


def render_runtime_skills_info(skills: list[BrowserSkill]) -> str | None:
	if not skills:
		return None
	return '\n'.join(f'<skill name="{skill.name}" title="{skill.title}">\n{skill.content.strip()}\n</skill>' for skill in skills)


@dataclass(frozen=True)
class MessageContextBuilder:
	"""Builds the typed model-context mirror for the legacy message manager."""

	task: str
	state: MessageManagerState
	file_system: FileSystem
	include_attributes: list[str]
	sensitive_data_description: str = ''
	include_recent_events: bool = False
	max_clickable_elements_length: int = 40000
	max_history_items: int | None = None

	def build(
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
		"""Build a typed mirror of the legacy message-manager state."""

		context = BrowserContext()
		context.append(TaskItem(text=self.task))
		if self.state.compacted_memory:
			context.append(CompactionItem(summary=self.state.compacted_memory))

		history_context_items, omitted_history_count = self._history_context_items()
		for history_index, history_context_item in enumerate(history_context_items):
			context.append(history_context_item)
			if history_index == 0 and omitted_history_count:
				context.append(
					WarningItem(
						code='history_omitted',
						message=f'{omitted_history_count} previous context items omitted from active context.',
					)
				)

		context.append(
			self._agent_state_context_item(
				available_file_paths=available_file_paths,
				plan_description=plan_description,
			)
		)

		if browser_state_summary is not None:
			context.append(self._browser_state_context_item(browser_state_summary))

		if self.state.read_state_description:
			context.append(ExtractionArtifactItem(source='read_state', content=self.state.read_state_description))

		for image_data in self.state.read_state_images:
			image_name = str(image_data.get('name') or 'image')
			context.append(
				ScreenshotItem(
					source='read_state',
					label=image_name,
					media_type='image/png' if image_name.lower().endswith('.png') else 'image/jpeg',
					included_in_model=True,
				)
			)

		for skill in selected_runtime_skills or []:
			context.append(SkillItem(**skill.model_dump()))

		if page_filtered_actions:
			context.append(PageActionsItem(description=page_filtered_actions))

		if unavailable_skills_info:
			context.append(WarningItem(code='unavailable_skills', message=unavailable_skills_info))

		context.append(
			StepInfoItem(
				step_number=step_info.step_number if step_info else None,
				max_steps=step_info.max_steps if step_info else None,
				today=datetime.now().strftime('%Y-%m-%d'),
			)
		)

		return context

	def _history_context_items(self) -> tuple[list[ContextItem], int]:
		if self._should_render_legacy_history():
			return self._legacy_history_items_for_context()

		if self.max_history_items is None or len(self.state.context_items) <= self.max_history_items:
			return self.state.context_items, 0

		omitted_count = len(self.state.context_items) - self.max_history_items
		recent_items_count = self.max_history_items - 1
		return [
			self.state.context_items[0],
			*self.state.context_items[-recent_items_count:],
		], omitted_count

	def _should_render_legacy_history(self) -> bool:
		return len(self.state.context_items) <= 1 and len(self.state.agent_history_items) > len(self.state.context_items)

	def _legacy_history_items_for_context(self) -> tuple[list[ContextItem], int]:
		if self.max_history_items is None or len(self.state.agent_history_items) <= self.max_history_items:
			legacy_items = self.state.agent_history_items
			omitted_count = 0
		else:
			omitted_count = len(self.state.agent_history_items) - self.max_history_items
			recent_items_count = self.max_history_items - 1
			legacy_items = [
				self.state.agent_history_items[0],
				*self.state.agent_history_items[-recent_items_count:],
			]

		context_items: list[ContextItem] = []
		for history_item in legacy_items:
			if history_item.system_message:
				message = history_item.system_message.strip()
				if message == 'Agent initialized':
					context_items.append(WarningItem(code='agent_initialized', message=message))
				elif '<follow_up_user_request>' in message:
					context_items.append(UserSteerItem(text=_strip_known_xml_tag(message, 'follow_up_user_request')))
				else:
					context_items.append(WarningItem(code='legacy_system_message', message=message))
				continue

			context_items.append(
				ToolResultItem(
					tool_name='legacy.step',
					content=history_item.to_string(),
					structured_content=history_item.model_dump(exclude_none=True),
				)
			)
		return context_items, omitted_count

	def _agent_state_context_item(
		self,
		*,
		available_file_paths: list[str] | None = None,
		plan_description: str | None = None,
	) -> AgentStateItem:
		todo_contents = self.file_system.get_todo_contents() if self.file_system else ''
		if not todo_contents:
			todo_contents = '[empty todo.md, fill it when applicable]'

		return AgentStateItem(
			file_system_description=self.file_system.describe() if self.file_system else 'No file system available',
			todo_contents=todo_contents,
			plan=plan_description,
			sensitive_data_description=self.sensitive_data_description or None,
			available_file_paths=available_file_paths or [],
		)

	def _browser_state_context_item(self, browser_state_summary: BrowserStateSummary) -> BrowserStateItem:
		dom_text = ''
		try:
			dom_text = browser_state_summary.dom_state.llm_representation(include_attributes=self.include_attributes)
		except Exception as e:
			logger.debug(f'Failed to render DOM for typed context mirror: {e}')
		if len(dom_text) > self.max_clickable_elements_length:
			dom_text = f'{dom_text[: self.max_clickable_elements_length]}\n(truncated to {self.max_clickable_elements_length} characters)'

		page_info_text = ''
		if browser_state_summary.page_info:
			page_info = browser_state_summary.page_info
			pages_above = page_info.pixels_above / page_info.viewport_height if page_info.viewport_height > 0 else 0
			pages_below = page_info.pixels_below / page_info.viewport_height if page_info.viewport_height > 0 else 0
			page_info_text = f'<page_info>{pages_above:.1f} pages above, {pages_below:.1f} pages below</page_info>'

		tabs_text = '\n'.join(f'Tab {tab.target_id[-4:]}: {tab.url} - {tab.title[:30]}' for tab in browser_state_summary.tabs)
		current_tab_candidates = [
			tab.target_id
			for tab in browser_state_summary.tabs
			if tab.url == browser_state_summary.url and tab.title == browser_state_summary.title
		]
		current_target_id = current_tab_candidates[0] if len(current_tab_candidates) == 1 else None
		current_tab_text = f'Current tab: {current_target_id[-4:]}' if current_target_id is not None else ''

		recent_events_text = ''
		if self.include_recent_events and browser_state_summary.recent_events:
			recent_events_text = f'Recent browser events: {browser_state_summary.recent_events}'

		closed_popups_text = ''
		if browser_state_summary.closed_popup_messages:
			closed_popups_text = 'Auto-closed JavaScript dialogs:\n' + '\n'.join(
				f'  - {message}' for message in browser_state_summary.closed_popup_messages
			)

		pdf_text = ''
		if browser_state_summary.is_pdf_viewer:
			pdf_text = 'PDF viewer cannot be rendered. Do not use extract on this page; use read_file on the downloaded PDF.'

		text_parts = [
			current_tab_text,
			'Available tabs:',
			tabs_text,
			page_info_text,
			recent_events_text,
			closed_popups_text,
			pdf_text,
			'Interactive elements:',
			dom_text or 'empty page',
		]

		runtime_handles = {
			'tab_target_ids': [tab.target_id for tab in browser_state_summary.tabs],
			'selector_backend_node_ids': list(browser_state_summary.dom_state.selector_map.keys()),
		}
		return BrowserStateItem(
			url=browser_state_summary.url,
			title=browser_state_summary.title,
			text='\n'.join(part for part in text_parts if part).strip(),
			runtime_handles=runtime_handles,
			is_fresh=True,
		)
