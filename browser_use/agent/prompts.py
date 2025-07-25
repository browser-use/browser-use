import importlib.resources
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from browser_use.llm.messages import ContentPartImageParam, ContentPartTextParam, ImageURL, SystemMessage, UserMessage
from browser_use.observability import observe_debug
from browser_use.utils import is_new_tab_page

if TYPE_CHECKING:
	from browser_use.agent.views import AgentStepInfo
	from browser_use.browser.views import BrowserStateSummary
	from browser_use.filesystem.file_system import FileSystem


class SystemPrompt:
	def __init__(
		self,
		action_description: str,
		max_actions_per_step: int = 10,
		override_system_message: str | None = None,
		extend_system_message: str | None = None,
		use_thinking: bool = True,
		flash_mode: bool = False,
	):
		self.default_action_description = action_description
		self.max_actions_per_step = max_actions_per_step
		self.use_thinking = use_thinking
		self.flash_mode = flash_mode
		prompt = ''
		if override_system_message:
			prompt = override_system_message
		else:
			self._load_prompt_template()
			prompt = self.prompt_template.format(max_actions=self.max_actions_per_step)

		if extend_system_message:
			prompt += f'\n{extend_system_message}'

		self.system_message = SystemMessage(content=prompt, cache=True)

	def _load_prompt_template(self) -> None:
		"""Load the prompt template from the markdown file."""
		try:
			# Choose the appropriate template based on flash_mode and use_thinking settings
			if self.flash_mode:
				template_filename = 'system_prompt_flash.md'
			elif self.use_thinking:
				template_filename = 'system_prompt.md'
			else:
				template_filename = 'system_prompt_no_thinking.md'

			# This works both in development and when installed as a package
			with importlib.resources.files('browser_use.agent').joinpath(template_filename).open('r', encoding='utf-8') as f:
				self.prompt_template = f.read()
		except Exception as e:
			raise RuntimeError(f'Failed to load system prompt template: {e}')

	def get_system_message(self) -> SystemMessage:
		"""
		Get the system prompt for the agent.

		Returns:
		    SystemMessage: Formatted system prompt
		"""
		return self.system_message


# Functions:
# {self.default_action_description}

# Example:
# {self.example_response()}
# Your AVAILABLE ACTIONS:
# {self.default_action_description}


class AgentMessagePrompt:
	def __init__(
		self,
		browser_state_summary: 'BrowserStateSummary',
		file_system: 'FileSystem',
		read_state_description: str | None = None,
		task: str | None = None,
		include_attributes: list[str] | None = None,
		step_info: Optional['AgentStepInfo'] = None,
		page_filtered_actions: str | None = None,
		max_clickable_elements_length: int = 40000,
		sensitive_data: str | None = None,
		available_file_paths: list[str] | None = None,
		screenshots: list[str] | None = None,
	):
		self.browser_state: 'BrowserStateSummary' = browser_state_summary
		self.file_system: 'FileSystem | None' = file_system
		self.read_state_description: str | None = read_state_description
		self.task: str | None = task
		self.include_attributes = include_attributes
		self.step_info = step_info
		self.page_filtered_actions: str | None = page_filtered_actions
		self.max_clickable_elements_length: int = max_clickable_elements_length
		self.sensitive_data: str | None = sensitive_data
		self.available_file_paths: list[str] | None = available_file_paths
		self.screenshots = screenshots or []
		assert self.browser_state

	def _deduplicate_screenshots(self, screenshots: list[str]) -> list[str]:
		"""
		Remove consecutive duplicate screenshots, keeping only the most recent of each.

		Args:
			screenshots: List of base64-encoded screenshot strings in chronological order (oldest first)

		Returns:
			List of screenshots with consecutive duplicates removed, maintaining chronological order
		"""
		if not screenshots:
			return []

		if len(screenshots) == 1:
			return screenshots

		# Keep track of unique screenshots by comparing each with the next one
		unique_screenshots = []

		for i in range(len(screenshots)):
			# Always keep the last screenshot
			if i == len(screenshots) - 1:
				unique_screenshots.append(screenshots[i])
			# Only keep screenshot if it's different from the next one
			elif screenshots[i] != screenshots[i + 1]:
				unique_screenshots.append(screenshots[i])

		return unique_screenshots

	def _get_browser_state_description(self) -> str:
		elements_text = self.browser_state.element_tree.clickable_elements_to_string(include_attributes=self.include_attributes)

		if len(elements_text) > self.max_clickable_elements_length:
			elements_text = elements_text[: self.max_clickable_elements_length]
			truncated_text = f' (truncated to {self.max_clickable_elements_length} characters)'
		else:
			truncated_text = ''

		has_content_above = (self.browser_state.pixels_above or 0) > 0
		has_content_below = (self.browser_state.pixels_below or 0) > 0

		# Enhanced page information for the model
		page_info_text = ''
		if self.browser_state.page_info:
			pi = self.browser_state.page_info
			# Compute page statistics dynamically
			pages_above = pi.pixels_above / pi.viewport_height if pi.viewport_height > 0 else 0
			pages_below = pi.pixels_below / pi.viewport_height if pi.viewport_height > 0 else 0
			total_pages = pi.page_height / pi.viewport_height if pi.viewport_height > 0 else 0
			current_page_position = pi.scroll_y / max(pi.page_height - pi.viewport_height, 1)
			page_info_text = f'Page info: {pi.viewport_width}x{pi.viewport_height}px viewport, {pi.page_width}x{pi.page_height}px total page size, {pages_above:.1f} pages above, {pages_below:.1f} pages below, {total_pages:.1f} total pages, at {current_page_position:.0%} of page'

		if elements_text != '':
			if has_content_above:
				if self.browser_state.page_info:
					pi = self.browser_state.page_info
					pages_above = pi.pixels_above / pi.viewport_height if pi.viewport_height > 0 else 0
					elements_text = f'... {self.browser_state.pixels_above} pixels above ({pages_above:.1f} pages) - scroll to see more or extract structured data if you are looking for specific information ...\n{elements_text}'
				else:
					elements_text = f'... {self.browser_state.pixels_above} pixels above - scroll to see more or extract structured data if you are looking for specific information ...\n{elements_text}'
			else:
				elements_text = f'[Start of page]\n{elements_text}'
			if has_content_below:
				if self.browser_state.page_info:
					pi = self.browser_state.page_info
					pages_below = pi.pixels_below / pi.viewport_height if pi.viewport_height > 0 else 0
					elements_text = f'{elements_text}\n... {self.browser_state.pixels_below} pixels below ({pages_below:.1f} pages) - scroll to see more or extract structured data if you are looking for specific information ...'
				else:
					elements_text = f'{elements_text}\n... {self.browser_state.pixels_below} pixels below - scroll to see more or extract structured data if you are looking for specific information ...'
			else:
				elements_text = f'{elements_text}\n[End of page]'
		else:
			elements_text = 'empty page'

		tabs_text = ''
		current_tab_candidates = []

		# Find tabs that match both URL and title to identify current tab more reliably
		for tab in self.browser_state.tabs:
			if tab.url == self.browser_state.url and tab.title == self.browser_state.title:
				current_tab_candidates.append(tab.page_id)

		# If we have exactly one match, mark it as current
		# Otherwise, don't mark any tab as current to avoid confusion
		current_tab_id = current_tab_candidates[0] if len(current_tab_candidates) == 1 else None

		for tab in self.browser_state.tabs:
			tabs_text += f'Tab {tab.page_id}: {tab.url} - {tab.title[:30]}\n'

		current_tab_text = f'Current tab: {current_tab_id}' if current_tab_id is not None else ''

		# Check if current page is a PDF viewer and add appropriate message
		pdf_message = ''
		if self.browser_state.is_pdf_viewer:
			pdf_message = 'PDF viewer cannot be rendered. In this page, DO NOT use the extract_structured_data action as PDF content cannot be rendered. Use the read_file action on the downloaded PDF in available_file_paths to read the full content.\n\n'

		browser_state = f"""{current_tab_text}
Available tabs:
{tabs_text}
{page_info_text}
{pdf_message}Interactive elements from top layer of the current page inside the viewport{truncated_text}:
{elements_text}
"""
		return browser_state

	def _get_agent_state_description(self) -> str:
		if self.step_info:
			step_info_description = f'Step {self.step_info.step_number + 1} of {self.step_info.max_steps} max possible steps\n'
		else:
			step_info_description = ''
		time_str = datetime.now().strftime('%Y-%m-%d %H:%M')
		step_info_description += f'Current date and time: {time_str}'

		_todo_contents = self.file_system.get_todo_contents() if self.file_system else ''
		if not len(_todo_contents):
			_todo_contents = '[Current todo.md is empty, fill it with your plan when applicable]'

		agent_state = f"""
<user_request>
{self.task}
</user_request>
<file_system>
{self.file_system.describe() if self.file_system else 'No file system available'}
</file_system>
<todo_contents>
{_todo_contents}
</todo_contents>
"""
		if self.sensitive_data:
			agent_state += f'<sensitive_data>\n{self.sensitive_data}\n</sensitive_data>\n'

		agent_state += f'<step_info>\n{step_info_description}\n</step_info>\n'
		if self.available_file_paths:
			agent_state += '<available_file_paths>\n' + '\n'.join(self.available_file_paths) + '\n</available_file_paths>\n'
		return agent_state

	def get_agent_state_message(self) -> UserMessage:
		"""Get agent state as a separate message (not cached - changes every step)"""
		agent_state_content = '<agent_state>\n' + self._get_agent_state_description().strip('\n') + '\n</agent_state>'
		return UserMessage(content=agent_state_content, cache=False)

	def get_browser_state_message(self, use_vision: bool = True) -> UserMessage:
		"""Get browser state as a separate message, optionally with screenshots"""
		# Don't pass screenshot to model if page is a new tab page, step is 0, and there's only one tab
		if (
			is_new_tab_page(self.browser_state.url)
			and self.step_info is not None
			and self.step_info.step_number == 0
			and len(self.browser_state.tabs) == 1
		):
			use_vision = False

		browser_state_content = '<browser_state>\n' + self._get_browser_state_description().strip('\n') + '\n</browser_state>'

		if self.page_filtered_actions:
			browser_state_content += '\n<page_specific_actions>\n'
			browser_state_content += self.page_filtered_actions + '\n'
			browser_state_content += '</page_specific_actions>\n'

		if use_vision is True and self.screenshots:
			# Start with text description
			content_parts: list[ContentPartTextParam | ContentPartImageParam] = [ContentPartTextParam(text=browser_state_content)]

			# Deduplicate screenshots, keeping only the most recent of each unique image
			unique_screenshots = self._deduplicate_screenshots(self.screenshots)

			# Add screenshots with labels
			for i, screenshot in enumerate(unique_screenshots):
				if i == len(unique_screenshots) - 1:
					label = 'Current screenshot:'
				else:
					# Use simple, accurate labeling since we don't have actual step timing info
					label = 'Previous screenshot:'

				# Add label as text content
				content_parts.append(ContentPartTextParam(text=label))

				# Add the screenshot
				content_parts.append(
					ContentPartImageParam(
						image_url=ImageURL(
							url=f'data:image/png;base64,{screenshot}',
							media_type='image/png',
						),
					)
				)

			return UserMessage(content=content_parts, cache=False)

		return UserMessage(content=browser_state_content, cache=False)

	def get_read_state_message(self) -> UserMessage | None:
		"""Get read state as a separate message"""
		if not self.read_state_description:
			return None
		if not self.read_state_description.strip('\n').strip():
			return None

		read_state_content = '<read_state>\n' + self.read_state_description.strip('\n') + '\n</read_state>'
		return UserMessage(content=read_state_content, cache=False)

	@observe_debug(ignore_input=True, ignore_output=True, name='get_user_message')
	def get_user_message(self, use_vision: bool = True) -> UserMessage:
		"""
		DEPRECATED: This method is kept for backward compatibility but should not be used.
		Use get_agent_state_message(), get_browser_state_message(), and get_read_state_message() instead.
		"""
		# For backward compatibility, return all messages concatenated in a single message
		agent_state_message = self.get_agent_state_message()
		browser_state_message = self.get_browser_state_message(use_vision)
		read_state_message = self.get_read_state_message()

		# Flatten the three message objects into a single list of content parts,
		# handling both raw-text (`str`) and already-structured (`list[...]`) cases.
		content_parts: list[ContentPartTextParam | ContentPartImageParam] = []

		for msg in (agent_state_message, browser_state_message, read_state_message):
			if msg is None:
				continue

			if isinstance(msg.content, list):
				# Message is already a list of content parts – reuse as-is.
				content_parts.extend(msg.content)
			else:
				# Wrap plain text in a ContentPartTextParam.
				content_parts.append(ContentPartTextParam(text=str(msg.content)))

		return UserMessage(content=content_parts, cache=True)
