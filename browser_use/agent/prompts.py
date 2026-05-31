import importlib.resources
import re
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from browser_use.browser.views import PLACEHOLDER_4PX_SCREENSHOT
from browser_use.dom.views import NodeType, SimplifiedNode
from browser_use.llm.messages import ContentPartImageParam, ContentPartTextParam, ImageURL, SystemMessage, UserMessage
from browser_use.observability import observe_debug
from browser_use.utils import is_new_tab_page, sanitize_surrogates

if TYPE_CHECKING:
	from browser_use.agent.views import AgentStepInfo
	from browser_use.browser.views import BrowserStateSummary
	from browser_use.filesystem.file_system import FileSystem


def _is_anthropic_4_5_model(model_name: str | None) -> bool:
	"""Check if the model is Claude Opus 4.5 or Haiku 4.5 (requires 4096+ token prompts for caching)."""
	if not model_name:
		return False
	model_lower = model_name.lower()
	# Check for Opus 4.5 or Haiku 4.5 variants
	is_opus_4_5 = 'opus' in model_lower and ('4.5' in model_lower or '4-5' in model_lower)
	is_haiku_4_5 = 'haiku' in model_lower and ('4.5' in model_lower or '4-5' in model_lower)
	return is_opus_4_5 or is_haiku_4_5


def _strip_structured_output_contract(prompt: str) -> str:
	"""Remove the legacy AgentOutput JSON contract when native tools are the model protocol."""
	return re.sub(r'\n?<output>.*?</output>', '', prompt, flags=re.DOTALL).strip()


class SystemPromptTemplateSource(str, Enum):
	"""Where the selected system prompt template is rendered from."""

	RESOURCE = 'resource'
	INLINE = 'inline'


class SystemPromptTemplateSpec(BaseModel):
	"""Declarative system prompt template entry."""

	model_config = ConfigDict(frozen=True)

	name: str
	source: SystemPromptTemplateSource
	resource_filename: str | None = None
	inline_template: str | None = None


_BROWSER_USE_THINKING_TEMPLATE = """You are a browser-use agent operating in thinking mode. You automate browser tasks by outputting structured JSON actions.

<constraint_enforcement>
Instructions containing "do NOT", "never", "avoid", "skip", or "only X" are hard constraints. Before each action, check: does this violate any constraint? If yes, stop and find an alternative.
</constraint_enforcement>

<output>
You must ALWAYS respond with a valid JSON in this exact format:
{{
  "thinking": "A structured reasoning block analyzing: current page state, what was attempted, what worked/failed, and strategic planning for next steps.",
  "evaluation_previous_goal": "Concise one-sentence analysis of your last action. Clearly state success, failure, or uncertain.",
  "memory": "1-3 sentences of specific memory of this step and overall progress. Track items found, pages visited, forms filled, etc.",
  "next_goal": "State the next immediate goal and action to achieve it, in one clear sentence.",
  "action": [{{"action_name": {{...params...}}}}]
}}
Action list should NEVER be empty.
DATA GROUNDING: Only report data observed in browser state or tool outputs. Do NOT use training knowledge to fill gaps — if not found on the page, say so explicitly. Never fabricate values.
</output>
"""

_BROWSER_USE_NO_THINKING_TEMPLATE = """You are a browser-use agent. You automate browser tasks by outputting structured JSON actions.

<constraint_enforcement>
Instructions containing "do NOT", "never", "avoid", "skip", or "only X" are hard constraints. Before each action, check: does this violate any constraint? If yes, stop and find an alternative.
</constraint_enforcement>

<output>
You must ALWAYS respond with a valid JSON in this exact format:
{{
  "evaluation_previous_goal": "Concise one-sentence analysis of your last action. Clearly state success, failure, or uncertain.",
  "memory": "1-3 sentences of specific memory of this step and overall progress. Track items found, pages visited, forms filled, etc.",
  "next_goal": "State the next immediate goal and action to achieve it, in one clear sentence.",
  "action": [{{"action_name": {{...params...}}}}]
}}
Action list should NEVER be empty.
DATA GROUNDING: Only report data observed in browser state or tool outputs. Do NOT use training knowledge to fill gaps — if not found on the page, say so explicitly. Never fabricate values.
</output>
"""

_BROWSER_USE_FLASH_TEMPLATE = """You are a browser-use agent operating in flash mode. You automate browser tasks by outputting structured JSON actions.

<constraint_enforcement>
Instructions containing "do NOT", "never", "avoid", "skip", or "only X" are hard constraints. Before each action, check: does this violate any constraint? If yes, stop and find an alternative.
</constraint_enforcement>

<output>
You must respond with a valid JSON in this exact format:
{{
  "memory": "Up to 5 sentences of specific reasoning about: Was the previous step successful / failed? What do we need to remember from the current state for the task? Plan ahead what are the best next actions. What's the next immediate goal? Depending on the complexity think longer.",
  "action": [{{"action_name": {{...params...}}}}]
}}
Action list should NEVER be empty.
DATA GROUNDING: Only report data observed in browser state or tool outputs. Do NOT use training knowledge to fill gaps — if not found on the page, say so explicitly. Never fabricate values.
</output>
"""

_FLASH_TEMPLATE = """You are an AI agent designed to operate in an iterative loop to automate browser tasks. Your ultimate goal is accomplishing the task provided in <user_request>.
<language_settings>Default: English. Match user's language.</language_settings>
<user_request>Ultimate objective. Specific tasks: follow each step. Open-ended: plan approach.</user_request>
<browser_state>Elements: [index]<type>text</type>. Only [indexed] are interactive. Indentation=child. *[=new.</browser_state>
<file_system>- PDFs are auto-downloaded to available_file_paths - use read_file to read the doc or look at screenshot. You have access to persistent file system for progress tracking. Long tasks >10 steps: use todo.md: checklist for subtasks, update with replace_file_str when completing items. When writing CSV, use double quotes for commas. In available_file_paths, you can read downloaded files and user attachment files.</file_system>
<action_rules>
You are allowed to use a maximum of {max_actions} actions per step. Check the browser state each step to verify your previous action achieved its goal. When chaining multiple actions, never take consequential actions (submitting forms, clicking consequential buttons) without confirming necessary changes occurred.
</action_rules>
<output>You must respond with a valid JSON in this exact format:
{{
  "memory": "Up to 5 sentences of specific reasoning about: Was the previous step successful / failed? What do we need to remember from the current state for the task? Plan ahead what are the best next actions. What's the next immediate goal? Depending on the complexity think longer. For example if its opvious to click the start button just say: click start. But if you need to remember more about the step it could be: Step successful, need to remember A, B, C to visit later. Next click on A.",
  "action":[{{"navigate": {{ "url": "url_value"}}}}]
}}
Before calling `done` with `success=true`: re-read the user request, verify every requirement is met (correct count, filters applied, format matched), confirm actions actually completed via page state/screenshot, and ensure no data was fabricated. If anything is unmet or uncertain, set `success` to `false`.
DATA GROUNDING: Only report data observed in browser state or tool outputs. Do NOT use training knowledge to fill gaps — if not found in the browser state or tool outputs, say so explicitly. Never fabricate values.
</output>
"""

_FLASH_ANTHROPIC_TEMPLATE = """You are an AI agent designed to operate in an iterative loop to automate browser tasks. Your ultimate goal is accomplishing the task provided in <user_request>.
<user_request>
User request is the ultimate objective. For tasks with specific instructions, follow each step. For open-ended tasks, plan your own approach.
</user_request>
<browser_state>
Elements: [index]<type>text</type>. Only [indexed] are interactive. Indentation=child. *[=new.
</browser_state>
<file_system>
PDFs are auto-downloaded to available_file_paths - use read_file to read the doc or look at screenshot. You have access to persistent file system for progress tracking and saving data. Long tasks >10 steps: use todo.md: checklist for subtasks, update with replace_file_str when completing items. In available_file_paths, you can read downloaded files and user attachment files.
</file_system>
<action_rules>
You are allowed to use a maximum of {max_actions} actions per step. Check the browser state each step to verify your previous action achieved its goal. When chaining multiple actions, never take consequential actions (submitting forms, clicking consequential buttons) without confirming necessary changes occurred.
</action_rules>
<output>You must call the AgentOutput tool with the following schema for the arguments:

{{
  "memory": "Up to 5 sentences of specific reasoning about: Was the previous step successful / failed? What do we need to remember from the current state for the task? Plan ahead what are the best next actions. What's the next immediate goal? Depending on the complexity think longer. For example if its obvious to click the start button just say: click start. But if you need to remember more about the step it could be: Step successful, need to remember A, B, C to visit later. Next click on A.",
  "action": [
    {{
      "action_name": {{
        "parameter1": "value1",
        "parameter2": "value2"
      }}
    }}
  ]
}}

Always put `memory` field before the `action` field.
Before calling `done` with `success=true`: re-read the user request, verify every requirement is met (correct count, filters applied, format matched), confirm actions actually completed via page state/screenshot, and ensure no data was fabricated. If anything is unmet or uncertain, set `success` to `false`.
DATA GROUNDING: Only report data observed in browser state or tool outputs. Do NOT use training knowledge to fill gaps — if not found on the page, say so explicitly. Never fabricate values.
</output>
"""


SYSTEM_PROMPT_TEMPLATE_SPECS = {
	'system_prompt.md': SystemPromptTemplateSpec(
		name='system_prompt.md',
		source=SystemPromptTemplateSource.RESOURCE,
		resource_filename='system_prompt.md',
	),
	'system_prompt_no_thinking.md': SystemPromptTemplateSpec(
		name='system_prompt_no_thinking.md',
		source=SystemPromptTemplateSource.RESOURCE,
		resource_filename='system_prompt_no_thinking.md',
	),
	'system_prompt_anthropic_flash.md': SystemPromptTemplateSpec(
		name='system_prompt_anthropic_flash.md',
		source=SystemPromptTemplateSource.RESOURCE,
		resource_filename='system_prompt_anthropic_flash.md',
	),
	'system_prompt_flash.md': SystemPromptTemplateSpec(
		name='system_prompt_flash.md',
		source=SystemPromptTemplateSource.INLINE,
		inline_template=_FLASH_TEMPLATE,
	),
	'system_prompt_flash_anthropic.md': SystemPromptTemplateSpec(
		name='system_prompt_flash_anthropic.md',
		source=SystemPromptTemplateSource.INLINE,
		inline_template=_FLASH_ANTHROPIC_TEMPLATE,
	),
	'system_prompt_browser_use.md': SystemPromptTemplateSpec(
		name='system_prompt_browser_use.md',
		source=SystemPromptTemplateSource.INLINE,
		inline_template=_BROWSER_USE_THINKING_TEMPLATE,
	),
	'system_prompt_browser_use_no_thinking.md': SystemPromptTemplateSpec(
		name='system_prompt_browser_use_no_thinking.md',
		source=SystemPromptTemplateSource.INLINE,
		inline_template=_BROWSER_USE_NO_THINKING_TEMPLATE,
	),
	'system_prompt_browser_use_flash.md': SystemPromptTemplateSpec(
		name='system_prompt_browser_use_flash.md',
		source=SystemPromptTemplateSource.INLINE,
		inline_template=_BROWSER_USE_FLASH_TEMPLATE,
	),
}


class SystemPromptTemplateProfile(BaseModel):
	"""Typed selector for the system prompt template shown to the model."""

	model_config = ConfigDict(frozen=True)

	max_actions_per_step: int = Field(default=3, ge=1)
	use_thinking: bool = True
	flash_mode: bool = False
	is_anthropic: bool = False
	is_browser_use_model: bool = False
	is_anthropic_4_5: bool = False
	model_name: str | None = None

	def template_filename(self) -> str:
		if self.is_browser_use_model:
			if self.flash_mode:
				return 'system_prompt_browser_use_flash.md'
			if self.use_thinking:
				return 'system_prompt_browser_use.md'
			return 'system_prompt_browser_use_no_thinking.md'

		if self.is_anthropic_4_5 and self.flash_mode:
			return 'system_prompt_anthropic_flash.md'
		if self.flash_mode and self.is_anthropic:
			return 'system_prompt_flash_anthropic.md'
		if self.flash_mode:
			return 'system_prompt_flash.md'
		if self.use_thinking:
			return 'system_prompt.md'
		return 'system_prompt_no_thinking.md'

	def template_spec(self) -> SystemPromptTemplateSpec:
		return SYSTEM_PROMPT_TEMPLATE_SPECS[self.template_filename()]


class SystemPromptRenderer(BaseModel):
	"""Loads and renders system prompt templates for a selected profile."""

	model_config = ConfigDict(frozen=True)

	resource_package: str = 'browser_use.agent.system_prompts'

	def render(self, profile: SystemPromptTemplateProfile) -> str:
		template = self.load_template_spec(profile.template_spec())
		return template.format(max_actions=profile.max_actions_per_step)

	def load_template_spec(self, template_spec: SystemPromptTemplateSpec) -> str:
		if template_spec.source == SystemPromptTemplateSource.INLINE:
			if template_spec.inline_template is None:
				raise RuntimeError(f'Inline system prompt template has no content: {template_spec.name}')
			return template_spec.inline_template

		if template_spec.resource_filename is None:
			raise RuntimeError(f'Resource system prompt template has no filename: {template_spec.name}')
		return self.load_template(template_spec.resource_filename)

	def load_template(self, template_filename: str) -> str:
		try:
			with importlib.resources.files(self.resource_package).joinpath(template_filename).open('r', encoding='utf-8') as f:
				return f.read()
		except Exception as e:
			raise RuntimeError(f'Failed to load system prompt template: {e}')


class SystemPrompt:
	def __init__(
		self,
		max_actions_per_step: int = 3,
		override_system_message: str | None = None,
		extend_system_message: str | None = None,
		use_thinking: bool = True,
		flash_mode: bool = False,
		is_anthropic: bool = False,
		is_browser_use_model: bool = False,
		is_anthropic_4_5: bool | None = None,
		model_name: str | None = None,
		use_native_tool_calls: bool = False,
	):
		self.renderer = SystemPromptRenderer()
		self.profile = SystemPromptTemplateProfile(
			max_actions_per_step=max_actions_per_step,
			use_thinking=use_thinking,
			flash_mode=flash_mode,
			is_anthropic=is_anthropic,
			is_browser_use_model=is_browser_use_model,
			is_anthropic_4_5=_is_anthropic_4_5_model(model_name) if is_anthropic_4_5 is None else is_anthropic_4_5,
			model_name=model_name,
		)
		prompt = ''
		if override_system_message is not None:
			prompt = override_system_message
		else:
			prompt = self.renderer.render(self.profile)

		if extend_system_message:
			prompt += f'\n{extend_system_message}'

		if use_native_tool_calls:
			prompt = _strip_structured_output_contract(prompt)
			prompt += (
				'\n\n<native_tool_calling>\n'
				'Use the provider-native tools for browser actions. Do not output JSON action objects. '
				'Choose the appropriate tool call(s), with valid arguments, and let the runtime execute them.\n'
				'</native_tool_calling>'
			)

		self.system_message = SystemMessage(content=prompt, cache=True)

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
		read_state_images: list[dict] | None = None,
		llm_screenshot_size: tuple[int, int] | None = None,
		unavailable_skills_info: str | None = None,
		runtime_skills_info: str | None = None,
		plan_description: str | None = None,
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
		self.read_state_images = read_state_images or []
		self.unavailable_skills_info: str | None = unavailable_skills_info
		self.runtime_skills_info: str | None = runtime_skills_info
		self.plan_description: str | None = plan_description
		self.llm_screenshot_size = llm_screenshot_size
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
			'text_chars': 0,
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
				if node.is_interactive:
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

			elif original.node_type == NodeType.TEXT_NODE:
				stats['text_chars'] += len(original.node_value.strip())

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

		# Format statistics
		stats_text = '<page_stats>'
		if page_stats['total_elements'] < 10:
			stats_text += 'Page appears empty (SPA not loaded?) - '
		# Skeleton screen: many elements but almost no text = loading placeholders
		elif page_stats['total_elements'] > 20 and page_stats['text_chars'] < page_stats['total_elements'] * 5:
			stats_text += 'Page appears to show skeleton/placeholder content (still loading?) - '
		stats_text += f'{page_stats["links"]} links, {page_stats["interactive_elements"]} interactive, '
		stats_text += f'{page_stats["iframes"]} iframes'
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
			page_info_text = '<page_info>'
			page_info_text += f'{pages_above:.1f} pages above, {pages_below:.1f} pages below'
			if pages_below > 0.2:
				page_info_text += ' — scroll down to reveal more content'
			page_info_text += '</page_info>\n'
		if elements_text != '':
			if not has_content_above:
				elements_text = f'[Start of page]\n{elements_text}'
			if not has_content_below:
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
			pdf_message += (
				'Use the read_file action on the downloaded PDF in available_file_paths to read the full text content.\n\n'
			)

		# Add recent events if available and requested
		recent_events_text = ''
		if self.include_recent_events and self.browser_state.recent_events:
			recent_events_text = f'Recent browser events: {self.browser_state.recent_events}\n'

		# Add closed popup messages if any
		closed_popups_text = ''
		if self.browser_state.closed_popup_messages:
			closed_popups_text = 'Auto-closed JavaScript dialogs:\n'
			for popup_msg in self.browser_state.closed_popup_messages:
				closed_popups_text += f'  - {popup_msg}\n'
			closed_popups_text += '\n'

		browser_state = f"""{stats_text}{current_tab_text}
Available tabs:
{tabs_text}
{page_info_text}
{recent_events_text}{closed_popups_text}{pdf_message}Interactive elements{truncated_text}:
{elements_text}
"""
		return browser_state

	def _get_agent_state_description(self) -> str:
		_todo_contents = self.file_system.get_todo_contents() if self.file_system else ''
		if not len(_todo_contents):
			_todo_contents = '[empty todo.md, fill it when applicable]'

		agent_state = f"""
<file_system>
{self.file_system.describe() if self.file_system else 'No file system available'}
</file_system>
<todo_contents>
{_todo_contents}
</todo_contents>
"""
		if self.plan_description:
			agent_state += f'<plan>\n{self.plan_description}\n</plan>\n'

		if self.sensitive_data:
			agent_state += f'<sensitive_data>{self.sensitive_data}</sensitive_data>\n'

		if self.available_file_paths:
			available_file_paths_text = '\n'.join(self.available_file_paths)
			agent_state += f'<available_file_paths>{available_file_paths_text}\nUse with absolute paths</available_file_paths>\n'
		return agent_state

	def _get_user_request_description(self) -> str:
		return f'<user_request>\n{self.task}\n</user_request>\n\n'

	def _get_step_meta_description(self) -> str:
		# Per-step varying metadata (step counter, wall-clock date). Kept out of <agent_state> so it
		# lives at the tail of the user message — anything before this block can in principle be
		# treated as the cacheable prefix.
		if self.step_info:
			step_info_description = f'Step{self.step_info.step_number + 1} maximum:{self.step_info.max_steps}\n'
		else:
			step_info_description = ''
		step_info_description += f'Today:{datetime.now().strftime("%Y-%m-%d")}'
		return f'<step_info>{step_info_description}</step_info>\n'

	def _resize_screenshot(self, screenshot_b64: str) -> str:
		"""Resize screenshot to llm_screenshot_size if configured."""
		if not self.llm_screenshot_size:
			return screenshot_b64

		try:
			import base64
			import logging
			from io import BytesIO

			from PIL import Image

			img = Image.open(BytesIO(base64.b64decode(screenshot_b64)))
			if img.size == self.llm_screenshot_size:
				return screenshot_b64

			logging.getLogger(__name__).info(
				f'🔄 Resizing screenshot from {img.size[0]}x{img.size[1]} to {self.llm_screenshot_size[0]}x{self.llm_screenshot_size[1]} for LLM'
			)

			img_resized = img.resize(self.llm_screenshot_size, Image.Resampling.LANCZOS)
			buffer = BytesIO()
			img_resized.save(buffer, format='PNG')
			return base64.b64encode(buffer.getvalue()).decode('utf-8')
		except Exception as e:
			logging.getLogger(__name__).warning(f'Failed to resize screenshot: {e}, using original')
			return screenshot_b64

	@observe_debug(ignore_input=True, ignore_output=True, name='get_user_message')
	def get_user_message(self, use_vision: bool = True) -> UserMessage:
		"""Get complete state as a single cached message"""
		# New-tab pages only carry placeholder screenshots, even later in a multi-tab session.
		if is_new_tab_page(self.browser_state.url):
			use_vision = False

		# Build complete state description
		state_description = (
			self._get_user_request_description()
			+ '<agent_history>\n'
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

		if self.runtime_skills_info:
			state_description += '<runtime_skills>\n'
			state_description += self.runtime_skills_info.strip('\n') + '\n'
			state_description += '</runtime_skills>\n'

		# Add unavailable skills information if any
		if self.unavailable_skills_info:
			state_description += '\n' + self.unavailable_skills_info + '\n'

		# Per-step varying metadata (step counter, date) lives at the tail of the message so that
		# everything above can in principle be treated as a cacheable prefix.
		state_description += self._get_step_meta_description()

		# Sanitize surrogates from all text content
		state_description = sanitize_surrogates(state_description)

		# Check if we have images to include (from read_file action)
		has_images = bool(self.read_state_images)
		screenshots = [screenshot for screenshot in self.screenshots if screenshot != PLACEHOLDER_4PX_SCREENSHOT]

		if (use_vision is True and screenshots) or has_images:
			# Start with text description
			content_parts: list[ContentPartTextParam | ContentPartImageParam] = [ContentPartTextParam(text=state_description)]

			# Add sample images
			content_parts.extend(self.sample_images)

			# Add screenshots with labels
			for i, screenshot in enumerate(screenshots):
				if i == len(screenshots) - 1:
					label = 'Current screenshot:'
				else:
					# Use simple, accurate labeling since we don't have actual step timing info
					label = 'Previous screenshot:'

				# Add label as text content
				content_parts.append(ContentPartTextParam(text=label))

				# Resize screenshot if llm_screenshot_size is configured
				processed_screenshot = self._resize_screenshot(screenshot)

				# Add the screenshot
				content_parts.append(
					ContentPartImageParam(
						image_url=ImageURL(
							url=f'data:image/png;base64,{processed_screenshot}',
							media_type='image/png',
							detail=self.vision_detail_level,
						),
					)
				)

			# Add read_state images (from read_file action) before screenshots
			for img_data in self.read_state_images:
				img_name = img_data.get('name', 'unknown')
				img_base64 = img_data.get('data', '')

				if not img_base64:
					continue

				# Detect image format from name
				if img_name.lower().endswith('.png'):
					media_type = 'image/png'
				else:
					media_type = 'image/jpeg'

				# Add label
				content_parts.append(ContentPartTextParam(text=f'Image from file: {img_name}'))

				# Add the image
				content_parts.append(
					ContentPartImageParam(
						image_url=ImageURL(
							url=f'data:{media_type};base64,{img_base64}',
							media_type=media_type,
							detail=self.vision_detail_level,
						),
					)
				)

			return UserMessage(content=content_parts, cache=True)

		return UserMessage(content=state_description, cache=True)


def get_rerun_summary_prompt(original_task: str, total_steps: int, success_count: int, error_count: int) -> str:
	return f'''You are analyzing the completion of a rerun task. Based on the screenshot and execution info, provide a summary.

Original task: {original_task}

Execution statistics:
- Total steps: {total_steps}
- Successful steps: {success_count}
- Failed steps: {error_count}

Analyze the screenshot to determine:
1. Whether the task completed successfully
2. What the final state shows
3. Overall completion status (complete/partial/failed)

Respond with:
- summary: A clear, concise summary of what happened during the rerun
- success: Whether the task completed successfully (true/false)
- completion_status: One of "complete", "partial", or "failed"'''


def get_rerun_summary_message(prompt: str, screenshot_b64: str | None = None) -> UserMessage:
	"""
	Build a UserMessage for rerun summary generation.

	Args:
		prompt: The prompt text
		screenshot_b64: Optional base64-encoded screenshot

	Returns:
		UserMessage with prompt and optional screenshot
	"""
	if screenshot_b64:
		# With screenshot: use multi-part content
		content_parts: list[ContentPartTextParam | ContentPartImageParam] = [
			ContentPartTextParam(type='text', text=prompt),
			ContentPartImageParam(
				type='image_url',
				image_url=ImageURL(url=f'data:image/png;base64,{screenshot_b64}'),
			),
		]
		return UserMessage(content=content_parts)
	else:
		# Without screenshot: use simple string content
		return UserMessage(content=prompt)


def get_ai_step_system_prompt() -> str:
	"""
	Get system prompt for AI step action used during rerun.

	Returns:
		System prompt string for AI step
	"""
	return """
You are an expert at extracting data from webpages.

<input>
You will be given:
1. A query describing what to extract
2. The markdown of the webpage (filtered to remove noise)
3. Optionally, a screenshot of the current page state
</input>

<instructions>
- Extract information from the webpage that is relevant to the query
- ONLY use the information available in the webpage - do not make up information
- If the information is not available, mention that clearly
- If the query asks for all items, list all of them
</instructions>

<output>
- Present ALL relevant information in a concise way
- Do not use conversational format - directly output the relevant information
- If information is unavailable, state that clearly
</output>
""".strip()


def get_ai_step_user_prompt(query: str, stats_summary: str, content: str) -> str:
	"""
	Build user prompt for AI step action.

	Args:
		query: What to extract or analyze
		stats_summary: Content statistics summary
		content: Page markdown content

	Returns:
		Formatted prompt string
	"""
	return f'<query>\n{query}\n</query>\n\n<content_stats>\n{stats_summary}\n</content_stats>\n\n<webpage_content>\n{content}\n</webpage_content>'
