from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from browser_use.llm.messages import (
	BaseMessage,
)

if TYPE_CHECKING:
	pass


class HistoryItem(BaseModel):
	"""Represents a single agent history item with its data and string representation"""

	step_number: int | None = None
	evaluation_previous_goal: str | None = None
	memory: str | None = None
	next_goal: str | None = None
	action_results: str | None = None
	error: str | None = None
	system_message: str | None = None

	model_config = ConfigDict(arbitrary_types_allowed=True)

	def model_post_init(self, __context) -> None:
		"""Validate that error and system_message are not both provided"""
		if self.error is not None and self.system_message is not None:
			raise ValueError('Cannot have both error and system_message at the same time')

	def to_string(self) -> str:
		"""Get string representation of the history item"""
		step_str = f'step_{self.step_number}' if self.step_number is not None else 'step_unknown'

		if self.error:
			return f"""<{step_str}>
{self.error}
</{step_str}>"""
		elif self.system_message:
			return f"""<sys>
{self.system_message}
</sys>"""
		else:
			content_parts = []

			# Only include evaluation_previous_goal if it's not None/empty
			if self.evaluation_previous_goal:
				content_parts.append(f'Evaluation of Previous Step: {self.evaluation_previous_goal}')

			# Always include memory
			if self.memory:
				content_parts.append(f'Memory: {self.memory}')

			# Only include next_goal if it's not None/empty
			if self.next_goal:
				content_parts.append(f'Next Goal: {self.next_goal}')

			if self.action_results:
				content_parts.append(self.action_results)

			content = '\n'.join(content_parts)

			return f"""<{step_str}>
{content}
</{step_str}>"""


class MessageHistory(BaseModel):
	"""History of messages"""

	system_message: BaseMessage | None = None
	state_message: BaseMessage | None = None
	context_messages: list[BaseMessage] = Field(default_factory=list)
	model_config = ConfigDict(arbitrary_types_allowed=True)

	def get_messages(self) -> list[BaseMessage]:
		"""Get all messages in the correct order: system -> state -> contextual"""
		messages = []
		if self.system_message:
			messages.append(self.system_message)
		if self.state_message:
			messages.append(self.state_message)
		messages.extend(self.context_messages)

		return messages


class MessageManagerState(BaseModel):
	"""Holds the state for MessageManager"""

	history: MessageHistory = Field(default_factory=MessageHistory)
	tool_id: int = 1
	agent_history_items: list[HistoryItem] = Field(
		default_factory=lambda: [HistoryItem(step_number=0, system_message='Agent initialized')]
	)
	read_state_description: str = ''

	model_config = ConfigDict(arbitrary_types_allowed=True)
