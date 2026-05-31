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
	ExtractionArtifactItem,
	PageActionsItem,
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

		for history_item in self.state.agent_history_items:
			if history_item.system_message:
				message = history_item.system_message.strip()
				if message == 'Agent initialized':
					context.append(WarningItem(code='agent_initialized', message=message))
				elif '<follow_up_user_request>' in message:
					context.append(UserSteerItem(text=_strip_known_xml_tag(message, 'follow_up_user_request')))
				else:
					context.append(WarningItem(code='legacy_system_message', message=message))
				continue

			context.append(
				ToolResultItem(
					tool_name='legacy.step',
					content=history_item.to_string(),
					structured_content=history_item.model_dump(exclude_none=True),
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

		runtime_handles = {
			'tab_target_ids': [tab.target_id for tab in browser_state_summary.tabs],
			'selector_backend_node_ids': list(browser_state_summary.dom_state.selector_map.keys()),
		}
		return BrowserStateItem(
			url=browser_state_summary.url,
			title=browser_state_summary.title,
			text=dom_text or 'empty page',
			runtime_handles=runtime_handles,
			is_fresh=True,
		)
