from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from uuid_extensions import uuid7str


def _utc_now() -> datetime:
	return datetime.now(UTC)


def _json(data: Any) -> str:
	return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)


class BaseContextItem(BaseModel):
	"""Base class for typed model-context items."""

	model_config = ConfigDict(frozen=True)

	item_id: str = Field(default_factory=uuid7str)
	created_at: datetime = Field(default_factory=_utc_now)
	metadata: dict[str, Any] = Field(default_factory=dict)

	def render(self) -> str:
		raise NotImplementedError


class TaskItem(BaseContextItem):
	"""The original task the browser agent must complete."""

	kind: Literal['task'] = 'task'
	text: str

	def render(self) -> str:
		return f'<user_request>\n{self.text.strip()}\n</user_request>'


class UserSteerItem(BaseContextItem):
	"""A follow-up user instruction added after the run has started."""

	kind: Literal['user_steer'] = 'user_steer'
	text: str

	def render(self) -> str:
		return f'<follow_up_user_request>\n{self.text.strip()}\n</follow_up_user_request>'


class BrowserStateItem(BaseContextItem):
	"""Current browser state shown to the model.

	Runtime handles keep full CDP identity available to the runtime even when
	the model-visible text is compacted or shortened.
	"""

	kind: Literal['browser_state'] = 'browser_state'
	url: str | None = None
	title: str | None = None
	text: str
	runtime_handles: dict[str, Any] = Field(default_factory=dict, exclude=True)
	is_fresh: bool = True

	def render(self) -> str:
		header_parts = []
		if self.url:
			header_parts.append(f'URL: {self.url}')
		if self.title:
			header_parts.append(f'Title: {self.title}')
		if not self.is_fresh:
			header_parts.append('WARNING: browser state may be stale')

		header = '\n'.join(header_parts)
		body = self.text.strip()
		content = f'{header}\n{body}'.strip() if header else body
		return f'<browser_state>\n{content}\n</browser_state>'


class AgentStateItem(BaseContextItem):
	"""Runtime state outside the browser page that the model can use."""

	kind: Literal['agent_state'] = 'agent_state'
	file_system_description: str | None = None
	todo_contents: str | None = None
	plan: str | None = None
	sensitive_data_description: str | None = None
	available_file_paths: list[str] = Field(default_factory=list)

	def render(self) -> str:
		sections = []
		if self.file_system_description is not None:
			sections.append(f'<file_system>\n{self.file_system_description.strip()}\n</file_system>')
		if self.todo_contents is not None:
			sections.append(f'<todo_contents>\n{self.todo_contents.strip()}\n</todo_contents>')
		if self.plan:
			sections.append(f'<plan>\n{self.plan.strip()}\n</plan>')
		if self.sensitive_data_description:
			sections.append(f'<sensitive_data>{self.sensitive_data_description.strip()}</sensitive_data>')
		if self.available_file_paths:
			files_text = '\n'.join(self.available_file_paths)
			sections.append(f'<available_file_paths>{files_text}\nUse with absolute paths</available_file_paths>')
		body = '\n'.join(sections).strip()
		return f'<agent_state>\n{body}\n</agent_state>'


class PageActionsItem(BaseContextItem):
	"""Actions available only for the current page/domain."""

	kind: Literal['page_actions'] = 'page_actions'
	description: str

	def render(self) -> str:
		return f'<page_specific_actions>\n{self.description.strip()}\n</page_specific_actions>'


class StepInfoItem(BaseContextItem):
	"""Per-step metadata kept at the end of model context."""

	kind: Literal['step_info'] = 'step_info'
	step_number: int | None = None
	max_steps: int | None = None
	today: str | None = None

	def render(self) -> str:
		parts = []
		if self.step_number is not None and self.max_steps is not None:
			parts.append(f'Step{self.step_number + 1} maximum:{self.max_steps}')
		if self.today:
			parts.append(f'Today:{self.today}')
		body = '\n'.join(parts)
		return f'<step_info>{body}</step_info>'


class ToolCallItem(BaseContextItem):
	"""A tool call requested by the model."""

	kind: Literal['tool_call'] = 'tool_call'
	tool_name: str
	call_id: str = Field(default_factory=uuid7str)
	arguments: dict[str, Any] = Field(default_factory=dict)

	def render(self) -> str:
		return f'<tool_call id="{self.call_id}" name="{self.tool_name}">\n{_json(self.arguments)}\n</tool_call>'


class ToolResultItem(BaseContextItem):
	"""Structured result returned by a tool."""

	kind: Literal['tool_result'] = 'tool_result'
	tool_name: str
	call_id: str | None = None
	content: str | None = None
	error: str | None = None
	structured_content: dict[str, Any] | list[Any] | None = None
	artifact_ids: list[str] = Field(default_factory=list)

	def render(self) -> str:
		attributes = f'name="{self.tool_name}"'
		if self.call_id:
			attributes += f' id="{self.call_id}"'

		parts = []
		if self.content:
			parts.append(self.content.strip())
		if self.structured_content is not None:
			parts.append(f'<structured_content>\n{_json(self.structured_content)}\n</structured_content>')
		if self.artifact_ids:
			parts.append(f'<artifacts>\n{_json(self.artifact_ids)}\n</artifacts>')
		if self.error:
			parts.append(f'<error>\n{self.error.strip()}\n</error>')

		body = '\n'.join(parts).strip()
		return f'<tool_result {attributes}>\n{body}\n</tool_result>'


class DownloadItem(BaseContextItem):
	"""A file downloaded by the browser runtime."""

	kind: Literal['download'] = 'download'
	file_name: str
	path: str | None = None
	url: str | None = None
	media_type: str | None = None

	def render(self) -> str:
		return f'<download>\n{_json(self.model_dump(mode="json", exclude={"kind", "item_id", "created_at", "metadata"}))}\n</download>'


class FileArtifactItem(BaseContextItem):
	"""A local file or generated artifact available to the agent."""

	kind: Literal['file_artifact'] = 'file_artifact'
	path: str
	description: str | None = None
	media_type: str | None = None

	def render(self) -> str:
		return f'<file_artifact>\n{_json(self.model_dump(mode="json", exclude={"kind", "item_id", "created_at", "metadata"}))}\n</file_artifact>'


class ScreenshotItem(BaseContextItem):
	"""A screenshot or image artifact known to the runtime."""

	kind: Literal['screenshot'] = 'screenshot'
	source: str
	label: str | None = None
	media_type: str = 'image/png'
	sha256: str | None = None
	byte_length: int | None = None
	included_in_model: bool = False

	def render(self) -> str:
		payload = self.model_dump(mode='json', exclude={'kind', 'item_id', 'created_at', 'metadata'})
		return f'<screenshot>\n{_json(payload)}\n</screenshot>'


class ExtractionArtifactItem(BaseContextItem):
	"""Large extracted page/file content that should be shown explicitly."""

	kind: Literal['extraction_artifact'] = 'extraction_artifact'
	source: str | None = None
	query: str | None = None
	content: str

	def render(self) -> str:
		header = {}
		if self.source:
			header['source'] = self.source
		if self.query:
			header['query'] = self.query

		if header:
			return f'<extraction_artifact metadata="{_json(header)}">\n{self.content.strip()}\n</extraction_artifact>'
		return f'<extraction_artifact>\n{self.content.strip()}\n</extraction_artifact>'


class WarningItem(BaseContextItem):
	"""A runtime warning or recovery hint shown to the model."""

	kind: Literal['warning'] = 'warning'
	message: str
	code: str | None = None

	def render(self) -> str:
		code = f' code="{self.code}"' if self.code else ''
		return f'<warning{code}>\n{self.message.strip()}\n</warning>'


class SkillItem(BaseContextItem):
	"""Task-relevant interaction guidance loaded on demand."""

	kind: Literal['skill'] = 'skill'
	name: str
	title: str
	content: str

	def render(self) -> str:
		return f'<skill name="{self.name}" title="{self.title}">\n{self.content.strip()}\n</skill>'


class CompactionItem(BaseContextItem):
	"""Summary of older context that has been compacted out of active history."""

	kind: Literal['compaction'] = 'compaction'
	summary: str
	source_item_ids: list[str] = Field(default_factory=list)

	def render(self) -> str:
		return (
			'<compacted_memory>\n'
			'<!-- Summary of prior steps. Treat as unverified context unless the current page or tool results confirm it. -->\n'
			f'{self.summary.strip()}\n'
			'</compacted_memory>'
		)


ContextItem = Annotated[
	TaskItem
	| UserSteerItem
	| BrowserStateItem
	| AgentStateItem
	| PageActionsItem
	| StepInfoItem
	| ToolCallItem
	| ToolResultItem
	| DownloadItem
	| FileArtifactItem
	| ScreenshotItem
	| ExtractionArtifactItem
	| WarningItem
	| SkillItem
	| CompactionItem,
	Field(discriminator='kind'),
]


class BrowserContext(BaseModel):
	"""Typed context list for deterministic model input rendering."""

	model_config = ConfigDict(validate_assignment=True)

	items: list[ContextItem] = Field(default_factory=list)

	def append(self, item: ContextItem) -> ContextItem:
		self.items.append(item)
		return item

	def latest_browser_state(self) -> BrowserStateItem | None:
		for item in reversed(self.items):
			if isinstance(item, BrowserStateItem):
				return item
		return None

	def render(self) -> str:
		return BrowserContextRenderer().render(self.items)


class BrowserContextRenderer(BaseModel):
	"""Deterministic renderer for typed browser-agent context items."""

	section_separator: str = '\n\n'

	def render(self, items: list[ContextItem]) -> str:
		rendered = [item.render().strip() for item in items]
		return self.section_separator.join(section for section in rendered if section).strip()
