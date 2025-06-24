from __future__ import annotations

import json
import logging

from pydantic import BaseModel

from browser_use.agent.message_manager.views import (
	MessageMetadata,
	SupportedMessageTypes,
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
	AssistantMessage,
	BaseMessage,
	ContentPartTextParam,
	SystemMessage,
	UserMessage,
)
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


class MessageManagerSettings(BaseModel):
	include_attributes: list[str] = []
	message_context: str | None = None
	# Support both old format {key: value} and new format {domain: {key: value}}
	sensitive_data: dict[str, str | dict[str, str]] | None = None
	available_file_paths: list[str] | None = None


class MessageManager:
	def __init__(
		self,
		task: str,
		system_message: SystemMessage,
		file_system: FileSystem,
		available_file_paths: list[str] | None = None,
		settings: MessageManagerSettings = MessageManagerSettings(),
		state: MessageManagerState = MessageManagerState(),
	):
		self.task = task
		self.settings = settings
		self.state = state
		self.system_prompt = system_message
		self.file_system = file_system
		self.agent_history_description = '<system>Agent initialized</system>\n'
		self.read_state_description = ''
		self.sensitive_data_description = ''
		self.available_file_paths = available_file_paths
		# Only initialize messages if state is empty
		if len(self.state.history.messages) == 0:
			self._init_messages()

	def _init_messages(self) -> None:
		"""Initialize the message history with system message, context, task, and other initial messages"""
		self._add_message_with_type(self.system_prompt, message_type='init')

		placeholder_message = UserMessage(
			content='<example_1>\nHere is an example output of thinking and tool call. You can use it as a reference but do not copy it exactly.'
		)
		# placeholder_message = HumanMessage(content='Example output:')
		self._add_message_with_type(placeholder_message, message_type='init')

		example_tool_call_1 = AssistantMessage(
			content=json.dumps(
				{
					'thinking': """I have successfully navigated to https://github.com/explore and can see the page has loaded with a list of featured repositories. The page contains interactive elements and I can identify specific repositories like bytedance/UI-TARS-desktop (index [4]) and ray-project/kuberay (index [5]). The user's request is to explore GitHub repositories and collect information about them such as descriptions, stars, or other metadata. So far, I haven't collected any information.
My navigation to the GitHub explore page was successful. The page loaded correctly and I can see the expected content.
I need to capture the key repositories I've identified so far into my memory and into a file.
Since this appears to be a multi-step task involving visiting multiple repositories and collecting their information, I need to create a structured plan in todo.md.
After writing todo.md, I can also initialize a github.md file to accumulate the information I've collected.
The file system actions do not change the browser state, so I can also click on the bytedance/UI-TARS-desktop (index [4]) to start collecting information.
""",
					'evaluation_previous_goal': 'Navigated to GitHub explore page. Verdict: Success',
					'memory': 'Found initial repositories such as bytedance/UI-TARS-desktop and ray-project/kuberay.',
					'next_goal': 'Create todo.md checklist to track progress, initialize github.md for collecting information, and click on bytedance/UI-TARS-desktop.',
					'action': [
						{
							'write_file': {
								'path': 'todo.md',
								'content': """
# Interesting Github Repositories in Explore Section

## Tasks
- [ ] Initialize a tracking file for GitHub repositories called github.md
- [ ] Visit each Github repository and find their description
- [ ] Visit bytedance/UI-TARS-desktop
- [ ] Visit ray-project/kuberay
- [ ] Check for additional Github repositories by scrolling down
- [ ] Compile all results in the requested format
- [ ] Validate that I have not missed anything in the page
- [ ] Report final results to user
""".strip('\n'),
							}
						},
						{
							'write_file': {
								'path': 'github.md',
								'content': """
# Github Repositories:
""",
							}
						},
						{
							'click_element_by_index': {
								'index': 4,
							}
						},
					],
				}
			)
		)
		self._add_message_with_type(example_tool_call_1, message_type='init')
		self._add_message_with_type(
			UserMessage(
				content='Data written to todo.md.\nData written to github.md.\nClicked element with index 4.\n</example_1>',
			),
			message_type='init',
		)

		placeholder_message = UserMessage(content='<example_2>Example thinking and tool call 2:')
		# self._add_message_with_tokens(placeholder_message, message_type='init')

		# TODO: add this back
		# 		example_tool_call_2 = AssistantMessage(
		# 			content=json.dumps(
		# 				{
		# 					'name': 'AgentOutput',
		# 					'args': {
		# 						'current_state': {
		# 							'thinking': """I
		# **Understanding the Current State:**
		# I am currently on Apple's main homepage, having successfully clicked on an 'Apple' link in the previous step. The page has loaded and I can see the typical Apple website layout with navigation elements. I can see an interactive element at index [4] that is labeled 'iPhone', which indicates this is a navigation link to Apple's iPhone product section.

		# **Evaluating the Previous Action:**
		# The click on the 'Apple' link was successful and brought me to Apple's homepage as expected. The page loaded properly and I can see the navigation structure including the iPhone link. This confirms that the previous navigation action worked correctly and I'm now in the right place to continue with the iPhone-related task.

		# **Tracking and Planning with todo.md:**
		# Based on the context, this seems to be part of a larger task involving Apple products. I should be prepared to update my todo.md file if there are multiple iPhone models or other Apple products to investigate. The current goal is to access the iPhone section to see what product information is available.

		# **Writing Intermediate Results:**
		# Once I reach the iPhone page, I'll need to extract information about different iPhone models, their specifications, prices, or other details. I should accumulate all findings in results.md in a structured format as I collect the information.

		# **Preparing what goes into my memory:**
		# I need to capture that I'm in the process of navigating to the iPhone section and preparing to collect product information.

		# **Planning my next action:**
		# My next action is to click on the iPhone link at index [4] to navigate to Apple's iPhone product page. This will give me access to the iPhone lineup and allow me to gather the requested information.
		# """,
		# 							'evaluation_previous_goal': 'Clicked Apple link and reached the homepage. Verdict: Success',
		# 							'memory': 'On Apple homepage with iPhone link at index [4].',
		# 							'next_goal': 'Click iPhone link.',
		# 						},
		# 						'action': [{'click_element_by_index': {'index': 4}}],
		# 					},
		# 					'id': str(self.state.tool_id),
		# 					'type': 'tool_call',
		# 				},
		# 			),
		# 		)
		# self._add_message_with_tokens(example_tool_call_2, message_type='init')
		# self.add_tool_message(content='Clicked on index [4]. </example_2>', message_type='init')

	def add_new_task(self, new_task: str) -> None:
		self.task = new_task
		self.agent_history_description += f'\n<system>User updated USER REQUEST to: {new_task}</system>\n'

	def _update_agent_history_description(
		self,
		model_output: AgentOutput | None = None,
		result: list[ActionResult] | None = None,
		step_info: AgentStepInfo | None = None,
	) -> None:
		"""Update the agent history description"""

		if result is None:
			result = []
		step_number = step_info.step_number if step_info else 'unknown'

		self.read_state_description = ''

		action_results = ''
		result_len = len(result)
		for idx, action_result in enumerate(result):
			if action_result.include_extracted_content_only_once and action_result.extracted_content:
				self.read_state_description += action_result.extracted_content + '\n'
				logger.debug(f'Added extracted_content to read_state_description: {action_result.extracted_content}')

			if action_result.long_term_memory:
				action_results += f'Action {idx + 1}/{result_len}: {action_result.long_term_memory}\n'
				logger.debug(f'Added long_term_memory to action_results: {action_result.long_term_memory}')
			elif action_result.extracted_content and not action_result.include_extracted_content_only_once:
				action_results += f'Action {idx + 1}/{result_len}: {action_result.extracted_content}\n'
				logger.debug(f'Added extracted_content to action_results: {action_result.extracted_content}')

			if action_result.error:
				action_results += f'Action {idx + 1}/{result_len}: {action_result.error[:200]}\n'
				logger.debug(f'Added error to action_results: {action_result.error[:200]}')

		if action_results:
			action_results = f'Action Results:\n{action_results}'
		action_results = action_results.strip('\n')

		# Handle case where model_output is None (e.g., parsing failed)
		if model_output is None:
			if isinstance(step_number, int) and step_number > 0:
				self.agent_history_description += f"""<step_{step_number}>
Agent failed to output in the right format.
</step_{step_number}>
"""
		else:
			self.agent_history_description += f"""<step_{step_number}>
Evaluation of Previous Step: {model_output.current_state.evaluation_previous_goal}
Memory: {model_output.current_state.memory}
Next Goal: {model_output.current_state.next_goal}
{action_results}
</step_{step_number}>
"""

	def _get_sensitive_data_description(self, current_page_url) -> str:
		sensitive_data = self.settings.sensitive_data
		if not sensitive_data:
			return ''

		# Collect placeholders for sensitive data
		placeholders = set()

		for key, value in sensitive_data.items():
			if isinstance(value, dict):
				# New format: {domain: {key: value}}
				if match_url_with_domain_pattern(current_page_url, key, True):
					placeholders.update(value.keys())
			else:
				# Old format: {key: value}
				placeholders.add(key)
		if placeholders:
			info = f'Here are placeholders for sensitive data: {list(placeholders)}'
			info += '\nTo use them, write <secret>the placeholder name</secret>'
			return info

		return ''

	@time_execution_sync('--add_state_message')
	def add_state_message(
		self,
		browser_state_summary: BrowserStateSummary,
		model_output: AgentOutput | None = None,
		result: list[ActionResult] | None = None,
		step_info: AgentStepInfo | None = None,
		use_vision=True,
		page_filtered_actions: str | None = None,
		sensitive_data=None,
	) -> None:
		"""Add browser state as human message"""

		self._update_agent_history_description(model_output, result, step_info)
		if sensitive_data:
			self.sensitive_data_description = self._get_sensitive_data_description(browser_state_summary.url)
		# otherwise add state message and result to next message (which will not stay in memory)
		assert browser_state_summary
		state_message = AgentMessagePrompt(
			browser_state_summary=browser_state_summary,
			file_system=self.file_system,
			agent_history_description=self.agent_history_description,
			read_state_description=self.read_state_description,
			task=self.task,
			include_attributes=self.settings.include_attributes,
			step_info=step_info,
			page_filtered_actions=page_filtered_actions,
			sensitive_data=self.sensitive_data_description,
			available_file_paths=self.available_file_paths,
		).get_user_message(use_vision)

		self._add_message_with_type(state_message)

	def add_plan(self, plan: str | None, position: int | None = None) -> None:
		if not plan:
			return

		msg = AssistantMessage(content=plan)
		self._add_message_with_type(msg, position)

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

		return [m.message for m in self.state.history.messages]

	def _add_message_with_type(
		self,
		message: BaseMessage,
		position: int | None = None,
		message_type: SupportedMessageTypes | None = None,
	) -> None:
		"""Add message with token count metadata
		position: None for last, -1 for second last, etc.
		"""

		# filter out sensitive data from the message
		if self.settings.sensitive_data:
			message = self._filter_sensitive_data(message)

		metadata = MessageMetadata(message_type=message_type)
		self.state.history.add_message(message, metadata, position)

	@time_execution_sync('--filter_sensitive_data')
	def _filter_sensitive_data(self, message: BaseMessage) -> BaseMessage:
		"""Filter out sensitive data from the message"""

		def replace_sensitive(value: str) -> str:
			if not self.settings.sensitive_data:
				return value

			# Collect all sensitive values, immediately converting old format to new format
			sensitive_values: dict[str, str] = {}

			# Process all sensitive data entries
			for key_or_domain, content in self.settings.sensitive_data.items():
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

	def _remove_last_state_message(self) -> None:
		"""Remove last state message from history"""
		self.state.history.remove_last_state_message()
