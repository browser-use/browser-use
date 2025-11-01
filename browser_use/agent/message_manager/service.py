from __future__ import annotations

import logging
from typing import Literal

from browser_use.agent.message_manager.views import (
	HistoryItem,
)
from browser_use.agent.prompts import AgentMessagePrompt
from browser_use.agent.views import (
	ActionResult,
	AgentOutput,
	AgentStepInfo,
	MessageManagerState,
)
from browser_use.browser.views import BrowserStateSummary
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm.messages import (
	BaseMessage,
	ContentPartImageParam,
	ContentPartTextParam,
	SystemMessage,
)
from browser_use.observability import observe_debug
from browser_use.utils import match_url_with_domain_pattern, time_execution_sync

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
		state: MessageManagerState = MessageManagerState(),
		use_thinking: bool = True,
		include_attributes: list[str] | None = None,
		sensitive_data: dict[str, str | dict[str, str]] | None = None,
		max_history_items: int | None = None,
		vision_detail_level: Literal['auto', 'low', 'high'] = 'auto',
		include_tool_call_examples: bool = False,
		include_recent_events: bool = False,
		sample_images: list[ContentPartTextParam | ContentPartImageParam] | None = None,
	):
		self.task = task
		self.state = state
		self.system_prompt = system_message
		self.file_system = file_system
		self.sensitive_data_description = ''
		self.use_thinking = use_thinking
		self.max_history_items = max_history_items
		self.vision_detail_level = vision_detail_level
		self.include_tool_call_examples = include_tool_call_examples
		self.include_recent_events = include_recent_events
		self.sample_images = sample_images

		assert max_history_items is None or max_history_items > 5, 'max_history_items must be None or greater than 5'

		# Store settings as direct attributes instead of in a settings object
		self.include_attributes = include_attributes or []
		self.sensitive_data = sensitive_data
		self.last_input_messages = []
		self.last_state_message_text: str | None = None
		# Only initialize messages if state is empty
		if len(self.state.history.get_messages()) == 0:
			self._set_message_with_type(self.system_prompt, 'system')

	@property
	def agent_history_description(self) -> str:
		"""Build agent history description from list of items, respecting max_history_items limit"""
		if self.max_history_items is None:
			# Include all items
			return '\n'.join(item.to_string() for item in self.state.agent_history_items)

		total_items = len(self.state.agent_history_items)

		# If we have fewer items than the limit, just return all items
		if total_items <= self.max_history_items:
			return '\n'.join(item.to_string() for item in self.state.agent_history_items)

		# We have more items than the limit, so we need to omit some
		omitted_count = total_items - self.max_history_items

		# Show first item + omitted message + most recent (max_history_items - 1) items
		# The omitted message doesn't count against the limit, only real history items do
		recent_items_count = self.max_history_items - 1  # -1 for first item

		items_to_include = [
			self.state.agent_history_items[0].to_string(),  # Keep first item (initialization)
			f'<sys>[... {omitted_count} previous steps omitted...]</sys>',
		]
		# Add most recent items
		items_to_include.extend([item.to_string() for item in self.state.agent_history_items[-recent_items_count:]])

		return '\n'.join(items_to_include)

	def add_new_task(self, new_task: str) -> None:
		new_task = '<follow_up_user_request> ' + new_task.strip() + ' </follow_up_user_request>'
		if '<initial_user_request>' not in self.task:
			self.task = '<initial_user_request>' + self.task + '</initial_user_request>'
		self.task += '\n' + new_task
		task_update_item = HistoryItem(system_message=new_task)
		self.state.agent_history_items.append(task_update_item)

	def _update_agent_history_description(
		self,
		model_output: AgentOutput | None = None,
		result: list[ActionResult] | None = None,
		step_info: AgentStepInfo | None = None,
	) -> None:
		"""Update the agent history description"""

		if result is None:
			result = []
		step_number = step_info.step_number if step_info else None

		self.state.read_state_description = ''

		action_results = ''
		result_len = len(result)
		read_state_idx = 0

		for idx, action_result in enumerate(result):
			if action_result.include_extracted_content_only_once and action_result.extracted_content:
				self.state.read_state_description += (
					f'<read_state_{read_state_idx}>\n{action_result.extracted_content}\n</read_state_{read_state_idx}>\n'
				)
				read_state_idx += 1
				logger.debug(f'Added extracted_content to read_state_description: {action_result.extracted_content}')

			if action_result.long_term_memory:
				action_results += f'{action_result.long_term_memory}\n'
				logger.debug(f'Added long_term_memory to action_results: {action_result.long_term_memory}')
			elif action_result.extracted_content and not action_result.include_extracted_content_only_once:
				action_results += f'{action_result.extracted_content}\n'
				logger.debug(f'Added extracted_content to action_results: {action_result.extracted_content}')

			if action_result.error:
				if len(action_result.error) > 200:
					error_text = action_result.error[:100] + '......' + action_result.error[-100:]
				else:
					error_text = action_result.error
				action_results += f'{error_text}\n'
				logger.debug(f'Added error to action_results: {error_text}')

		# Simple 60k character limit for read_state_description
		MAX_CONTENT_SIZE = 60000
		if len(self.state.read_state_description) > MAX_CONTENT_SIZE:
			self.state.read_state_description = (
				self.state.read_state_description[:MAX_CONTENT_SIZE] + '\n... [Content truncated at 60k characters]'
			)
			logger.debug(f'Truncated read_state_description to {MAX_CONTENT_SIZE} characters')

		self.state.read_state_description = self.state.read_state_description.strip('\n')

		if action_results:
			action_results = f'Result\n{action_results}'
		action_results = action_results.strip('\n') if action_results else None

		# Simple 60k character limit for action_results
		if action_results and len(action_results) > MAX_CONTENT_SIZE:
			action_results = action_results[:MAX_CONTENT_SIZE] + '\n... [Content truncated at 60k characters]'
			logger.debug(f'Truncated action_results to {MAX_CONTENT_SIZE} characters')

		# Build the history item
		if model_output is None:
			# Add history item for initial actions (step 0) or errors (step > 0)
			if step_number is not None:
				if step_number == 0 and action_results:
					# Step 0 with initial action results
					history_item = HistoryItem(step_number=step_number, action_results=action_results)
					self.state.agent_history_items.append(history_item)
				elif step_number > 0:
					# Error case for steps > 0
					history_item = HistoryItem(step_number=step_number, error='Agent failed to output in the right format.')
					self.state.agent_history_items.append(history_item)
		else:
			history_item = HistoryItem(
				step_number=step_number,
				evaluation_previous_goal=model_output.current_state.evaluation_previous_goal,
				memory=model_output.current_state.memory,
				next_goal=model_output.current_state.next_goal,
				action_results=action_results,
			)
			self.state.agent_history_items.append(history_item)

	def _get_sensitive_data_description(self, current_page_url) -> str:
		sensitive_data = self.sensitive_data
		if not sensitive_data:
			return ''

		# Collect placeholders for sensitive data
		placeholders: set[str] = set()

		for key, value in sensitive_data.items():
			if isinstance(value, dict):
				# New format: {domain: {key: value}}
				if current_page_url and match_url_with_domain_pattern(current_page_url, key, True):
					placeholders.update(value.keys())
			else:
				# Old format: {key: value}
				placeholders.add(key)

		if placeholders:
			placeholder_list = sorted(list(placeholders))
			info = f'Here are placeholders for sensitive data:\n{placeholder_list}\n'
			info += 'To use them, write <secret>the placeholder name</secret>'
			return info

		return ''

	@observe_debug(ignore_input=True, ignore_output=True, name='create_state_messages')
	@time_execution_sync('--create_state_messages')
	def create_state_messages(
		self,
		browser_state_summary: BrowserStateSummary,
		model_output: AgentOutput | None = None,
		result: list[ActionResult] | None = None,
		step_info: AgentStepInfo | None = None,
		use_vision: bool | Literal['auto'] = 'auto',
		page_filtered_actions: str | None = None,
		sensitive_data=None,
		available_file_paths: list[str] | None = None,  # Always pass current available_file_paths
	) -> None:
		"""Create single state message with all content"""

		# Clear contextual messages from previous steps to prevent accumulation
		self.state.history.context_messages.clear()

		# First, update the agent history items with the latest step results
		self._update_agent_history_description(model_output, result, step_info)

		# Use the passed sensitive_data parameter, falling back to instance variable
		effective_sensitive_data = sensitive_data if sensitive_data is not None else self.sensitive_data
		if effective_sensitive_data is not None:
			# Update instance variable to keep it in sync
			self.sensitive_data = effective_sensitive_data
			self.sensitive_data_description = self._get_sensitive_data_description(browser_state_summary.url)

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
			sensitive_data=self.sensitive_data_description,
			available_file_paths=available_file_paths,
			screenshots=screenshots,
			vision_detail_level=self.vision_detail_level,
			include_recent_events=self.include_recent_events,
			sample_images=self.sample_images,
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
		# Don't filter system and state messages - they should contain placeholder tags or normal conversation
		if message_type == 'system':
			self.state.history.system_message = message
		elif message_type == 'state':
			self.state.history.state_message = message
		else:
			raise ValueError(f'Invalid state message type: {message_type}')

	def _add_context_message(self, message: BaseMessage) -> None:
		"""Add a contextual message specific to this step (e.g., validation errors, retry instructions, timeout warnings)"""
		# Don't filter context messages - they should contain normal conversation or error messages
		self.state.history.context_messages.append(message)

	@time_execution_sync('--filter_sensitive_data')
	def _filter_sensitive_data(self, message: BaseMessage) -> BaseMessage:
		"""Filter out sensitive data from the message"""

		def replace_sensitive(value: str) -> str:
			if not self.sensitive_data:
				return value

			# Collect all sensitive values, immediately converting old format to new format
			sensitive_values: dict[str, str] = {}

			# Process all sensitive data entries
			for key_or_domain, content in self.sensitive_data.items():
				if isinstance(content, dict):
					# Already in new format: {domain: {key: value}}
					for key, val in content.items():
						if val:  # Skip empty values
							sensitive_values[key] = val
				elif content:  # Old format: {key: value} - convert to new format internally
					# We treat this as if it was {'http*://*': {key_or_domain: content}}
					sensitive_values[key_or_domain] = content

			# If there are no valid sensitive data entries, just return the original value
			if not sensitive_values:
				logger.warning('No valid entries found in sensitive_data dictionary')
				return value

			# Replace all valid sensitive data values with their placeholder tags
			for key, val in sensitive_values.items():
				value = value.replace(val, f'<secret>{key}</secret>')

			return value

		if isinstance(message.content, str):
			message.content = replace_sensitive(message.content)
		elif isinstance(message.content, list):
			for i, item in enumerate(message.content):
				if isinstance(item, ContentPartTextParam):
					item.text = replace_sensitive(item.text)
					message.content[i] = item
		return message
