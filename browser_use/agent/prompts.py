import importlib.resources
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from langchain_core.messages import HumanMessage, SystemMessage

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
	):
		self.default_action_description = action_description
		self.max_actions_per_step = max_actions_per_step
		prompt = ''
		if override_system_message:
			prompt = override_system_message
		else:
			self._load_prompt_template()
			prompt = self.prompt_template.format(max_actions=self.max_actions_per_step)

		if extend_system_message:
			prompt += f'\n{extend_system_message}'

		self.system_message = SystemMessage(content=prompt)

	def _load_prompt_template(self) -> None:
		"""Load the prompt template from the markdown file."""
		try:
			# This works both in development and when installed as a package
			with importlib.resources.files('browser_use.agent').joinpath('system_prompt.md').open('r') as f:
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
		agent_history_description: str | None = None,
		read_state_description: str | None = None,
		task: str | None = None,
		include_attributes: list[str] | None = None,
		step_info: Optional['AgentStepInfo'] = None,
		page_filtered_actions: str | None = None,
		max_clickable_elements_length: int = 10000,
	):
		self.browser_state: 'BrowserStateSummary' = browser_state_summary
		self.file_system: 'FileSystem' | None = file_system
		self.agent_history_description: str | None = agent_history_description
		self.read_state_description: str | None = read_state_description
		self.task: str | None = task
		self.include_attributes = include_attributes or []
		self.step_info = step_info
		self.page_filtered_actions: str | None = page_filtered_actions
		self.max_clickable_elements_length: int = max_clickable_elements_length
		assert self.browser_state

	def _get_browser_state_description(self) -> str:
		elements_text = self.browser_state.element_tree.clickable_elements_to_string(include_attributes=self.include_attributes)

		if len(elements_text) > self.max_clickable_elements_length:
			elements_text = elements_text[: self.max_clickable_elements_length]
			truncated_text = f' (truncated to {self.max_clickable_elements_length} characters)'
		else:
			truncated_text = ''

		has_content_above = (self.browser_state.pixels_above or 0) > 0
		has_content_below = (self.browser_state.pixels_below or 0) > 0

		if elements_text != '':
			if has_content_above:
				elements_text = f'... {self.browser_state.pixels_above} pixels above - scroll or extract content to see more ...\n{elements_text}'
			else:
				elements_text = f'[Start of page]\n{elements_text}'
			if has_content_below:
				elements_text = f'{elements_text}\n... {self.browser_state.pixels_below} pixels below - scroll or extract content to see more ...'
			else:
				elements_text = f'{elements_text}\n[End of page]'
		else:
			elements_text = 'empty page'

		tabs_text = ''
		for tab in self.browser_state.tabs:
			tabs_text += f'Tab {tab.page_id}: URL={tab.url}, Title={tab.title[:30]}\n'

		browser_state = f"""# Browser State
Current URL: {self.browser_state.url}
Available tabs:
{tabs_text}
Interactive elements from top layer of the current page inside the viewport{truncated_text}:
{elements_text}
"""
		return browser_state

	def _get_agent_state_description(self) -> str:
		if self.step_info:
			step_info_description = f'Current step: {self.step_info.step_number + 1}/{self.step_info.max_steps}\n'
		else:
			step_info_description = ''
		time_str = datetime.now().strftime('%Y-%m-%d %H:%M')
		step_info_description += f'Current date and time: {time_str}'

		todo_contents = self.file_system.get_todo_contents()
		if not len(todo_contents):
			todo_contents = '[Current todo.md is empty, fill it with your plan when applicable]'

		agent_state = f"""# Agent State\n
## USER REQUEST:
{self.task}\n
## File System:
{self.file_system.describe()}\n
## Contents of todo.md:
{todo_contents}\n
## Step Info:
{step_info_description}
"""
		return agent_state

	def get_user_message(self, use_vision: bool = True) -> HumanMessage:
		state_description = self.agent_history_description + '\n'
		state_description += self._get_agent_state_description() + '\n'
		state_description += self._get_browser_state_description() + '\n'
		state_description += self.read_state_description + '\n'
		if self.page_filtered_actions:
			state_description += 'For this page, these additional actions are available:\n'
			state_description += self.page_filtered_actions + '\n'

		if self.browser_state.screenshot and use_vision is True:
			# Format message for vision model
			return HumanMessage(
				content=[
					{'type': 'text', 'text': state_description},
					{
						'type': 'image_url',
						'image_url': {'url': f'data:image/png;base64,{self.browser_state.screenshot}'},  # , 'detail': 'low'
					},
				]
			)

		return HumanMessage(content=state_description)


class PlannerPrompt(SystemPrompt):
	def __init__(self, available_actions: str):
		self.available_actions = available_actions

	def get_system_message(
		self, is_planner_reasoning: bool, extended_planner_system_prompt: str | None = None
	) -> SystemMessage | HumanMessage:
		"""Get the system message for the planner.

		Args:
		    is_planner_reasoning: If True, return as HumanMessage for chain-of-thought
		    extended_planner_system_prompt: Optional text to append to the base prompt

		Returns:
		    SystemMessage or HumanMessage depending on is_planner_reasoning
		"""

		planner_prompt_text = """
You are a planning agent that helps break down tasks into smaller steps and reason about the current state.
Your role is to:
1. Analyze the current state and history
2. Evaluate progress towards the ultimate goal
3. Identify potential challenges or roadblocks
4. Suggest the next high-level steps to take

Inside your messages, there will be AI messages from different agents with different formats.

Your output format should be always a JSON object with the following fields:
{{
    "state_analysis": "Brief analysis of the current state and what has been done so far",
    "progress_evaluation": "Evaluation of progress towards the ultimate goal (as percentage and description)",
    "challenges": "List any potential challenges or roadblocks",
    "next_steps": "List 2-3 concrete next steps to take",
    "reasoning": "Explain your reasoning for the suggested next steps"
}}

Ignore the other AI messages output structures.

Keep your responses concise and focused on actionable insights.
"""

		if extended_planner_system_prompt:
			planner_prompt_text += f'\n{extended_planner_system_prompt}'

		if is_planner_reasoning:
			return HumanMessage(content=planner_prompt_text)
		else:
			return SystemMessage(content=planner_prompt_text)
