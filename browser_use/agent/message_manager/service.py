from __future__ import annotations

import logging
from typing import Literal

from browser_use.agent.message_manager.compaction import MessageCompactionService
from browser_use.agent.message_manager.context_builder import MessageContextBuilder, render_runtime_skills_info
from browser_use.agent.message_manager.history import render_agent_history_description, update_agent_history
from browser_use.agent.message_manager.sensitive import filter_sensitive_data_message, get_sensitive_data_description
from browser_use.agent.message_manager.views import (
	HistoryItem,
)
from browser_use.agent.prompts import AgentMessagePrompt
from browser_use.agent.runtime.context import (
	BrowserContext,
)
from browser_use.agent.runtime.skills import BrowserSkill
from browser_use.agent.views import (
	ActionResult,
	AgentOutput,
	AgentStepInfo,
	MessageCompactionSettings,
	MessageManagerState,
)
from browser_use.browser.views import BrowserStateSummary
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm.base import BaseChatModel
from browser_use.llm.messages import (
	BaseMessage,
	ContentPartImageParam,
	ContentPartTextParam,
	SystemMessage,
)
from browser_use.observability import observe_debug
from browser_use.utils import (
	time_execution_sync,
)

logger = logging.getLogger(__name__)


# ========== Logging Helper Functions ==========
# These functions are used ONLY for formatting debug log output.
# They do NOT affect the actual message content sent to the LLM.
# All logging functions start with _log_ for easy identification.


def _log_get_message_emoji(message: BaseMessage) -> str:
	"""Get emoji for a message type - used only for logging display"""
	emoji_map = {
		'UserMessage': '💬',
		'SystemMessage': '🧠',
		'AssistantMessage': '🔨',
	}
	return emoji_map.get(message.__class__.__name__, '🎮')


def _log_format_message_line(message: BaseMessage, content: str, is_last_message: bool, terminal_width: int) -> list[str]:
	"""Format a single message for logging display"""
	try:
		lines = []

		# Get emoji and token info
		emoji = _log_get_message_emoji(message)
		# token_str = str(message.metadata.tokens).rjust(4)
		# TODO: fix the token count
		token_str = '??? (TODO)'
		prefix = f'{emoji}[{token_str}]: '

		# Calculate available width (emoji=2 visual cols + [token]: =8 chars)
		content_width = terminal_width - 10

		# Handle last message wrapping
		if is_last_message and len(content) > content_width:
			# Find a good break point
			break_point = content.rfind(' ', 0, content_width)
			if break_point > content_width * 0.7:  # Keep at least 70% of line
				first_line = content[:break_point]
				rest = content[break_point + 1 :]
			else:
				# No good break point, just truncate
				first_line = content[:content_width]
				rest = content[content_width:]

			lines.append(prefix + first_line)

			# Second line with 10-space indent
			if rest:
				if len(rest) > terminal_width - 10:
					rest = rest[: terminal_width - 10]
				lines.append(' ' * 10 + rest)
		else:
			# Single line - truncate if needed
			if len(content) > content_width:
				content = content[:content_width]
			lines.append(prefix + content)

		return lines
	except Exception as e:
		logger.warning(f'Failed to format message line for logging: {e}')
		# Return a simple fallback line
		return ['❓[   ?]: [Error formatting message]']


# ========== End of Logging Helper Functions ==========


class MessageManager:
	vision_detail_level: Literal['auto', 'low', 'high']

	def __init__(
		self,
		task: str,
		system_message: SystemMessage,
		file_system: FileSystem,
		state: MessageManagerState | None = None,
		use_thinking: bool = True,
		include_attributes: list[str] | None = None,
		sensitive_data: dict[str, str | dict[str, str]] | None = None,
		max_history_items: int | None = None,
		vision_detail_level: Literal['auto', 'low', 'high'] = 'auto',
		include_tool_call_examples: bool = False,
		include_recent_events: bool = False,
		sample_images: list[ContentPartTextParam | ContentPartImageParam] | None = None,
		llm_screenshot_size: tuple[int, int] | None = None,
		max_clickable_elements_length: int = 40000,
	):
		self.task = task
		self.state = state or MessageManagerState()
		self.system_prompt = system_message
		self.file_system = file_system
		self.sensitive_data_description = ''
		self.use_thinking = use_thinking
		self.max_history_items = max_history_items
		self.vision_detail_level = vision_detail_level
		self.include_tool_call_examples = include_tool_call_examples
		self.include_recent_events = include_recent_events
		self.sample_images = sample_images
		self.llm_screenshot_size = llm_screenshot_size
		self.max_clickable_elements_length = max_clickable_elements_length

		assert max_history_items is None or max_history_items > 5, 'max_history_items must be None or greater than 5'

		# Store settings as direct attributes instead of in a settings object
		self.include_attributes = include_attributes or []
		self.sensitive_data = sensitive_data
		self.last_input_messages = []
		self.last_state_message_text: str | None = None
		self.last_typed_context: BrowserContext | None = None
		# Only initialize messages if state is empty
		if len(self.state.history.get_messages()) == 0:
			self._set_message_with_type(self.system_prompt, 'system')

	@property
	def agent_history_description(self) -> str:
		"""Build agent history description from list of items, respecting max_history_items limit"""
		return render_agent_history_description(self.state, self.max_history_items)

	def add_new_task(self, new_task: str) -> None:
		new_task = '<follow_up_user_request> ' + new_task.strip() + ' </follow_up_user_request>'
		if '<initial_user_request>' not in self.task:
			self.task = '<initial_user_request>' + self.task + '</initial_user_request>'
		self.task += '\n' + new_task
		task_update_item = HistoryItem(system_message=new_task)
		self.state.agent_history_items.append(task_update_item)

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
		"""Build a typed mirror of the legacy message-manager state."""

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

	def prepare_step_state(
		self,
		browser_state_summary: BrowserStateSummary,
		model_output: AgentOutput | None = None,
		result: list[ActionResult] | None = None,
		step_info: AgentStepInfo | None = None,
		sensitive_data=None,
	) -> None:
		"""Prepare state for the next LLM call without building the final state message."""
		self.state.history.context_messages.clear()
		self._update_agent_history_description(model_output, result, step_info)

		effective_sensitive_data = sensitive_data if sensitive_data is not None else self.sensitive_data
		if effective_sensitive_data is not None:
			self.sensitive_data = effective_sensitive_data
			self.sensitive_data_description = self._get_sensitive_data_description(browser_state_summary.url)

	async def maybe_compact_messages(
		self,
		llm: BaseChatModel | None,
		settings: MessageCompactionSettings | None,
		step_info: AgentStepInfo | None = None,
	) -> bool:
		compactor = MessageCompactionService(state=self.state, sensitive_data=self.sensitive_data)
		return await compactor.maybe_compact(llm=llm, settings=settings, step_info=step_info)

	def _update_agent_history_description(
		self,
		model_output: AgentOutput | None = None,
		result: list[ActionResult] | None = None,
		step_info: AgentStepInfo | None = None,
	) -> None:
		"""Update the agent history description"""
		update_agent_history(self.state, model_output=model_output, result=result, step_info=step_info)

	def _get_sensitive_data_description(self, current_page_url) -> str:
		return get_sensitive_data_description(self.sensitive_data, current_page_url)

	@observe_debug(ignore_input=True, ignore_output=True, name='create_state_messages')
	@time_execution_sync('--create_state_messages')
	def create_state_messages(
		self,
		browser_state_summary: BrowserStateSummary,
		model_output: AgentOutput | None = None,
		result: list[ActionResult] | None = None,
		step_info: AgentStepInfo | None = None,
		use_vision: bool | Literal['auto'] = True,
		page_filtered_actions: str | None = None,
		sensitive_data=None,
		available_file_paths: list[str] | None = None,  # Always pass current available_file_paths
		unavailable_skills_info: str | None = None,  # Information about skills that cannot be used yet
		selected_runtime_skills: list[BrowserSkill] | None = None,  # Small task-relevant guidance snippets
		plan_description: str | None = None,  # Rendered plan for injection into agent state
		skip_state_update: bool = False,
	) -> None:
		"""Create single state message with all content"""

		if not skip_state_update:
			self.prepare_step_state(
				browser_state_summary=browser_state_summary,
				model_output=model_output,
				result=result,
				step_info=step_info,
				sensitive_data=sensitive_data,
			)

		self.last_typed_context = self.build_typed_context(
			browser_state_summary,
			page_filtered_actions=page_filtered_actions,
			available_file_paths=available_file_paths,
			unavailable_skills_info=unavailable_skills_info,
			selected_runtime_skills=selected_runtime_skills,
			plan_description=plan_description,
			step_info=step_info,
		)

		# Use only the current screenshot, but check if action results request screenshot inclusion
		screenshots = []
		include_screenshot_requested = False

		# Check if any action results request screenshot inclusion
		if result:
			for action_result in result:
				if action_result.metadata and action_result.metadata.get('include_screenshot'):
					include_screenshot_requested = True
					logger.debug('Screenshot inclusion requested by action result')
					break

		# Handle different use_vision modes:
		# - "auto": Only include screenshot if explicitly requested by action (e.g., screenshot)
		# - True: Always include screenshot
		# - False: Never include screenshot
		include_screenshot = False
		if use_vision is True:
			# Always include screenshot when use_vision=True
			include_screenshot = True
		elif use_vision == 'auto':
			# Only include screenshot if explicitly requested by action when use_vision="auto"
			include_screenshot = include_screenshot_requested
		# else: use_vision is False, never include screenshot (include_screenshot stays False)

		if include_screenshot and browser_state_summary.screenshot:
			screenshots.append(browser_state_summary.screenshot)

		# Use vision in the user message if screenshots are included
		effective_use_vision = len(screenshots) > 0

		# Create single state message with all content
		assert browser_state_summary
		state_message = AgentMessagePrompt(
			browser_state_summary=browser_state_summary,
			file_system=self.file_system,
			agent_history_description=self.agent_history_description,
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
		).get_user_message(effective_use_vision)

		# Store state message text for history
		self.last_state_message_text = state_message.text

		# Set the state message with caching enabled
		self._set_message_with_type(state_message, 'state')

	def _log_history_lines(self) -> str:
		"""Generate a formatted log string of message history for debugging / printing to terminal"""
		# TODO: fix logging

		# try:
		# 	total_input_tokens = 0
		# 	message_lines = []
		# 	terminal_width = shutil.get_terminal_size((80, 20)).columns

		# 	for i, m in enumerate(self.state.history.messages):
		# 		try:
		# 			total_input_tokens += m.metadata.tokens
		# 			is_last_message = i == len(self.state.history.messages) - 1

		# 			# Extract content for logging
		# 			content = _log_extract_message_content(m.message, is_last_message, m.metadata)

		# 			# Format the message line(s)
		# 			lines = _log_format_message_line(m, content, is_last_message, terminal_width)
		# 			message_lines.extend(lines)
		# 		except Exception as e:
		# 			logger.warning(f'Failed to format message {i} for logging: {e}')
		# 			# Add a fallback line for this message
		# 			message_lines.append('❓[   ?]: [Error formatting this message]')

		# 	# Build final log message
		# 	return (
		# 		f'📜 LLM Message history ({len(self.state.history.messages)} messages, {total_input_tokens} tokens):\n'
		# 		+ '\n'.join(message_lines)
		# 	)
		# except Exception as e:
		# 	logger.warning(f'Failed to generate history log: {e}')
		# 	# Return a minimal fallback message
		# 	return f'📜 LLM Message history (error generating log: {e})'

		return ''

	@time_execution_sync('--get_messages')
	def get_messages(self) -> list[BaseMessage]:
		"""Get current message list, potentially trimmed to max tokens"""

		# Log message history for debugging
		logger.debug(self._log_history_lines())
		self.last_input_messages = self.state.history.get_messages()
		return self.last_input_messages

	def _set_message_with_type(self, message: BaseMessage, message_type: Literal['system', 'state']) -> None:
		"""Replace a specific state message slot with a new message"""
		# System messages don't need filtering - they only contain instructions/placeholders
		# State messages need filtering - they include agent_history_description which contains
		# action results with real sensitive values (after placeholder replacement during execution)
		if message_type == 'system':
			self.state.history.system_message = message
		elif message_type == 'state':
			if self.sensitive_data:
				message = self._filter_sensitive_data(message)
			self.state.history.state_message = message
		else:
			raise ValueError(f'Invalid state message type: {message_type}')

	def _add_context_message(self, message: BaseMessage) -> None:
		"""Add a contextual message specific to this step (e.g., validation errors, retry instructions, timeout warnings)"""
		# Context messages typically contain error messages and validation info, not action results
		# with sensitive data, so filtering is not needed here
		self.state.history.context_messages.append(message)

	@time_execution_sync('--filter_sensitive_data')
	def _filter_sensitive_data(self, message: BaseMessage) -> BaseMessage:
		"""Filter out sensitive data from the message"""
		return filter_sensitive_data_message(message, self.sensitive_data)
