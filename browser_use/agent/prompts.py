import datetime
import importlib.resources
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage

if TYPE_CHECKING:
	from browser_use.agent.views import ActionResult, AgentStepInfo
	from browser_use.browser.views import BrowserState


class SystemPrompt:
	def __init__(
		self,
		action_description: str,
		max_actions_per_step: int = 10,
		override_system_message: Optional[str] = None,
		extend_system_message: Optional[str] = None,
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
		state: 'BrowserState',
		result: Optional[List['ActionResult']] = None,
		include_attributes: list[str] = [],
		step_info: Optional['AgentStepInfo'] = None,
	):
		self.state = state
		self.result = result
		self.include_attributes = include_attributes
		self.step_info = step_info

	def get_user_message(self, use_vision: bool = True) -> HumanMessage:
		elements_text = self.state.element_tree.clickable_elements_to_string(include_attributes=self.include_attributes)

		has_content_above = (self.state.pixels_above or 0) > 0
		has_content_below = (self.state.pixels_below or 0) > 0

		if elements_text != '':
			if has_content_above:
				elements_text = (
					f'... {self.state.pixels_above} pixels above - scroll or extract content to see more ...\n{elements_text}'
				)
			else:
				elements_text = f'[Start of page]\n{elements_text}'
			if has_content_below:
				elements_text = (
					f'{elements_text}\n... {self.state.pixels_below} pixels below - scroll or extract content to see more ...'
				)
			else:
				elements_text = f'{elements_text}\n[End of page]'
		else:
			elements_text = 'empty page'

		if self.step_info:
			step_info_description = f'Current step: {self.step_info.step + 1}/{self.step_info.max_steps}'
		else:
			step_info_description = ''
		time_str = datetime.now().strftime('%Y-%m-%d %H:%M')
		step_info_description += f'Current date and time: {time_str}'

		state_description = f"""
[Task history memory ends]
[Current state starts here]
The following is one-time information - if you need to remember it write it to memory:
Current url: {self.state.url}
Available tabs:
{self.state.tabs}
Interactive elements from top layer of the current page inside the viewport:
{elements_text}
{step_info_description}
"""

		if self.result:
			for i, result in enumerate(self.result):
				if result.extracted_content:
					state_description += f'\nAction result {i + 1}/{len(self.result)}: {result.extracted_content}'
				if result.error:
					# only use last line of error
					error = result.error.split('\n')[-1]
					state_description += f'\nAction error {i + 1}/{len(self.result)}: ...{error}'

		if self.state.screenshot and use_vision == True:
			# Format message for vision model
			return HumanMessage(
				content=[
					{'type': 'text', 'text': state_description},
					{
						'type': 'image_url',
						'image_url': {'url': f'data:image/png;base64,{self.state.screenshot}'},  # , 'detail': 'low'
					},
				]
			)

		return HumanMessage(content=state_description)


class PlannerPrompt:
	def __init__(self, action_description: Optional[str] = None):
		self.action_description = action_description

	def get_system_message(self) -> str:
		# Implementation details
		return "System message for planner"

	@staticmethod
	def get_system_prompt() -> str:
		"""Get the system prompt for the planner"""
		return """You are an advanced planning assistant for web browsing tasks. Your job is to analyze the current state of a browser automation task and provide structured guidance on next steps.

Your analysis should be based solely on the observable facts provided about the current browser state and task history. Do not speculate or hallucinate information.

Focus on:
1. Analyzing the current state of the task
2. Evaluating progress toward the goal
3. Identifying any challenges or roadblocks
4. Recommending concrete next steps

Your output format should be always a JSON object with the following fields:
{
    "state_analysis": "Brief analysis of the current state and what has been done so far",
    "progress_evaluation": "Evaluation of progress towards the ultimate goal (as percentage and description)",
    "challenges": "List any potential challenges or roadblocks",
    "next_steps": "List 2-3 concrete next steps to take",
    "reasoning": "Explain your reasoning for the suggested next steps"
}

Ignore the other AI messages output structures.

Keep your responses concise and focused on actionable insights."""

	@staticmethod
	def get_human_prompt(
		task: str,
		current_url: str,
		page_title: str,
		step_number: int,
		recent_actions: List[str],
		has_errors: bool,
		screenshot_base64: Optional[str] = None,
	) -> str:
		"""Get the human prompt for the planner"""
		prompt = f"""Task: {task}

Current State:
- URL: {current_url}
- Page Title: {page_title}
- Step Number: {step_number}
- Recent Actions: {', '.join(recent_actions) if recent_actions else 'None'}
- Has Errors: {'Yes' if has_errors else 'No'}

Based on this information, please analyze the current state and provide guidance on next steps in the required JSON format."""

		if screenshot_base64:
			prompt += "\n\nScreenshot is attached to help with your analysis."
			
		return prompt
