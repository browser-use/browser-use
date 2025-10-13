import importlib.resources
from datetime import datetime
from typing import TYPE_CHECKING, Literal, Optional

from browser_use.dom.views import NodeType, SimplifiedNode
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
		max_actions_per_step: int = 10,
		override_system_message: str | None = None,
		extend_system_message: str | None = None,
		use_thinking: bool = True,
		flash_mode: bool = False,
	):
		self.max_actions_per_step = max_actions_per_step
		self.use_thinking = use_thinking
		self.flash_mode = flash_mode
		prompt = ''
		if override_system_message is not None:
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


class AgentMessagePrompt:
	vision_detail_level: Literal['auto', 'low', 'high']

	def __init__(
		self,
		browser_state_summary: 'BrowserStateSummary',
		file_system: 'FileSystem',
		agent_history_description: str | None = None,
		read_state_description: str | None = None,
		task: str | None = None,
		include_attributes: list[str] | None = None,
		step_info: Optional['AgentStepInfo'] = None,
		page_filtered_actions: str | None = None,
		max_clickable_elements_length: int = 40000,
		sensitive_data: str | None = None,
		available_file_paths: list[str] | None = None,
		screenshots: list[str] | None = None,
		vision_detail_level: Literal['auto', 'low', 'high'] = 'auto',
		include_recent_events: bool = False,
		sample_images: list[ContentPartTextParam | ContentPartImageParam] | None = None,
	):
		self.browser_state: 'BrowserStateSummary' = browser_state_summary
		self.file_system: 'FileSystem | None' = file_system
		self.agent_history_description: str | None = agent_history_description
		self.read_state_description: str | None = read_state_description
		self.task: str | None = task
		self.include_attributes = include_attributes
		self.step_info = step_info
		self.page_filtered_actions: str | None = page_filtered_actions
		self.max_clickable_elements_length: int = max_clickable_elements_length
		self.sensitive_data: str | None = sensitive_data
		self.available_file_paths: list[str] | None = available_file_paths
		self.screenshots = screenshots or []
		self.vision_detail_level = vision_detail_level
		self.include_recent_events = include_recent_events
		self.sample_images = sample_images or []
		assert self.browser_state

	def _extract_page_statistics(self) -> dict[str, int]:
		"""Extract high-level page statistics from DOM tree for LLM context"""
		stats = {
			'links': 0,
			'iframes': 0,
			'shadow_open': 0,
			'shadow_closed': 0,
			'scroll_containers': 0,
			'images': 0,
			'interactive_elements': 0,
			'total_elements': 0,
		}

		if not self.browser_state.dom_state or not self.browser_state.dom_state._root:
			return stats

		def traverse_node(node: SimplifiedNode) -> None:
			"""Recursively traverse simplified DOM tree to count elements"""
			if not node or not node.original_node:
				return

			original = node.original_node
			stats['total_elements'] += 1

			# Count by node type and tag
			if original.node_type == NodeType.ELEMENT_NODE:
				tag = original.tag_name.lower() if original.tag_name else ''

				if tag == 'a':
					stats['links'] += 1
				elif tag in ('iframe', 'frame'):
					stats['iframes'] += 1
				elif tag == 'img':
					stats['images'] += 1

				# Check if scrollable
				if original.is_actually_scrollable:
					stats['scroll_containers'] += 1

				# Check if interactive
				if node.interactive_index is not None:
					stats['interactive_elements'] += 1

				# Check if this element hosts shadow DOM
				if node.is_shadow_host:
					# Check if any shadow children are closed
					has_closed_shadow = any(
						child.original_node.node_type == NodeType.DOCUMENT_FRAGMENT_NODE
						and child.original_node.shadow_root_type
						and child.original_node.shadow_root_type.lower() == 'closed'
						for child in node.children
					)
					if has_closed_shadow:
						stats['shadow_closed'] += 1
					else:
						stats['shadow_open'] += 1

			elif original.node_type == NodeType.DOCUMENT_FRAGMENT_NODE:
				# Shadow DOM fragment - these are the actual shadow roots
				# But don't double-count since we count them at the host level above
				pass

			# Traverse children
			for child in node.children:
				traverse_node(child)

		traverse_node(self.browser_state.dom_state._root)
		return stats

	@observe_debug(ignore_input=True, ignore_output=True, name='_get_browser_state_description')
	def _get_browser_state_description(self) -> str:
		# Extract page statistics first
		page_stats = self._extract_page_statistics()

		# Format statistics for LLM
		stats_text = '<page_stats>'
		if page_stats['total_elements'] < 10:
			stats_text += 'Page appears empty (SPA not loaded?) - '
		stats_text += f'{page_stats["links"]} links, {page_stats["interactive_elements"]} interactive, '
		stats_text += f'{page_stats["iframes"]} iframes, {page_stats["scroll_containers"]} scroll containers'
		if page_stats['shadow_open'] > 0 or page_stats['shadow_closed'] > 0:
			stats_text += f', {page_stats["shadow_open"]} shadow(open), {page_stats["shadow_closed"]} shadow(closed)'
		if page_stats['images'] > 0:
			stats_text += f', {page_stats["images"]} images'
		stats_text += f', {page_stats["total_elements"]} total elements'
		stats_text += '</page_stats>\n'

		elements_text = self.browser_state.dom_state.llm_representation(include_attributes=self.include_attributes)

		if len(elements_text) > self.max_clickable_elements_length:
			elements_text = elements_text[: self.max_clickable_elements_length]
			truncated_text = f' (truncated to {self.max_clickable_elements_length} characters)'
		else:
			truncated_text = ''

		has_content_above = False
		has_content_below = False
		# Enhanced page information for the model
		page_info_text = ''
		if self.browser_state.page_info:
			pi = self.browser_state.page_info
			# Compute page statistics dynamically
			pages_above = pi.pixels_above / pi.viewport_height if pi.viewport_height > 0 else 0
			pages_below = pi.pixels_below / pi.viewport_height if pi.viewport_height > 0 else 0
			has_content_above = pages_above > 0
			has_content_below = pages_below > 0
			total_pages = pi.page_height / pi.viewport_height if pi.viewport_height > 0 else 0
			current_page_position = pi.scroll_y / max(pi.page_height - pi.viewport_height, 1)
			page_info_text = '<page_info>'
			page_info_text += f'{pages_above:.1f} pages above, '
			page_info_text += f'{pages_below:.1f} pages below, '
			page_info_text += f'{total_pages:.1f} total pages'
			page_info_text += '</page_info>\n'
			# , at {current_page_position:.0%} of page
		if elements_text != '':
			if has_content_above:
				if self.browser_state.page_info:
					pi = self.browser_state.page_info
					pages_above = pi.pixels_above / pi.viewport_height if pi.viewport_height > 0 else 0
					elements_text = f'... {pages_above:.1f} pages above - scroll to see more or extract structured data if you are looking for specific information ...\n{elements_text}'
			else:
				elements_text = f'[Start of page]\n{elements_text}'
			if has_content_below:
				if self.browser_state.page_info:
					pi = self.browser_state.page_info
					pages_below = pi.pixels_below / pi.viewport_height if pi.viewport_height > 0 else 0
					elements_text = f'{elements_text}\n... {pages_below:.1f} pages below - scroll to see more or extract structured data if you are looking for specific information ...'
			else:
				elements_text = f'{elements_text}\n[End of page]'
		else:
			elements_text = 'empty page'

		tabs_text = ''
		current_tab_candidates = []

		# Find tabs that match both URL and title to identify current tab more reliably
		for tab in self.browser_state.tabs:
			if tab.url == self.browser_state.url and tab.title == self.browser_state.title:
				current_tab_candidates.append(tab.target_id)

		# If we have exactly one match, mark it as current
		# Otherwise, don't mark any tab as current to avoid confusion
		current_target_id = current_tab_candidates[0] if len(current_tab_candidates) == 1 else None

		for tab in self.browser_state.tabs:
			tabs_text += f'Tab {tab.target_id[-4:]}: {tab.url} - {tab.title[:30]}\n'

		current_tab_text = f'Current tab: {current_target_id[-4:]}' if current_target_id is not None else ''

		# Check if current page is a PDF viewer and add appropriate message
		pdf_message = ''
		if self.browser_state.is_pdf_viewer:
			pdf_message = (
				'PDF viewer cannot be rendered. In this page, DO NOT use the extract action as PDF content cannot be rendered. '
			)
			pdf_message += 'Use the read_file action on the downloaded PDF in available_file_paths to read the full text content or scroll in the page to see images/figures if needed.\n\n'

		# Add recent events if available and requested
		recent_events_text = ''
		if self.include_recent_events and self.browser_state.recent_events:
			recent_events_text = f'Recent browser events: {self.browser_state.recent_events}\n'

		browser_state = f"""{stats_text}{current_tab_text}
Available tabs:
{tabs_text}
{page_info_text}
{recent_events_text}{pdf_message}Interactive elements{truncated_text}:
{elements_text}
"""
		return browser_state

	def _get_agent_state_description(self) -> str:
		if self.step_info:
			step_info_description = f'Step{self.step_info.step_number + 1} maximum:{self.step_info.max_steps}\n'
		else:
			step_info_description = ''

		time_str = datetime.now().strftime('%Y-%m-%d')
		step_info_description += f'Today:{time_str}'

		_todo_contents = self.file_system.get_todo_contents() if self.file_system else ''
		if not len(_todo_contents):
			_todo_contents = '[empty todo.md, fill it when applicable]'

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
			agent_state += f'<sensitive_data>{self.sensitive_data}</sensitive_data>\n'

		agent_state += f'<step_info>{step_info_description}</step_info>\n'
		if self.available_file_paths:
			available_file_paths_text = '\n'.join(self.available_file_paths)
			agent_state += f'<available_file_paths>{available_file_paths_text}\nUse with absolute paths</available_file_paths>\n'
		return agent_state

	@observe_debug(ignore_input=True, ignore_output=True, name='get_user_message')
	def get_user_message(self, use_vision: bool = True) -> UserMessage:
		"""Get complete state as a single cached message"""
		# Don't pass screenshot to model if page is a new tab page, step is 0, and there's only one tab
		if (
			is_new_tab_page(self.browser_state.url)
			and self.step_info is not None
			and self.step_info.step_number == 0
			and len(self.browser_state.tabs) == 1
		):
			use_vision = False

		# Build complete state description
		state_description = (
			'<agent_history>\n'
			+ (self.agent_history_description.strip('\n') if self.agent_history_description else '')
			+ '\n</agent_history>\n\n'
		)
		state_description += '<agent_state>\n' + self._get_agent_state_description().strip('\n') + '\n</agent_state>\n'
		state_description += '<browser_state>\n' + self._get_browser_state_description().strip('\n') + '\n</browser_state>\n'
		# Only add read_state if it has content
		read_state_description = self.read_state_description.strip('\n').strip() if self.read_state_description else ''
		if read_state_description:
			state_description += '<read_state>\n' + read_state_description + '\n</read_state>\n'

		if self.page_filtered_actions:
			state_description += '<page_specific_actions>\n'
			state_description += self.page_filtered_actions + '\n'
			state_description += '</page_specific_actions>\n'

		if use_vision is True and self.screenshots:
			# Start with text description
			content_parts: list[ContentPartTextParam | ContentPartImageParam] = [ContentPartTextParam(text=state_description)]

			# Add sample images
			content_parts.extend(self.sample_images)

			# Add screenshots with labels
			for i, screenshot in enumerate(self.screenshots):
				if i == len(self.screenshots) - 1:
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
							url=f'data:image/jpeg;base64,{screenshot}',
							media_type='image/jpeg',
							detail=self.vision_detail_level,
						),
					)
				)

			return UserMessage(content=content_parts, cache=True)

		return UserMessage(content=state_description, cache=True)
