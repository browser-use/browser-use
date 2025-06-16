import importlib.resources
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from langchain_core.messages import HumanMessage, SystemMessage

if TYPE_CHECKING:
	from browser_use.agent.views import ActionResult, AgentStepInfo
	from browser_use.browser.views import BrowserStateSummary


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
		result: list['ActionResult'] | None = None,
		include_attributes: list[str] | None = None,
		step_info: Optional['AgentStepInfo'] = None,
	):
		self.state: 'BrowserStateSummary' = browser_state_summary
		self.result = result
		self.include_attributes = include_attributes or []
		self.step_info = step_info
		assert self.state

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
			step_info_description = f'Current step: {self.step_info.step_number + 1}/{self.step_info.max_steps}'
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

		if self.state.screenshot and use_vision is True:
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


class TaskEnhancementPrompt:
	"""Prompt for enhancing task descriptions to clarify completion criteria"""

	@staticmethod
	def get_system_message() -> str:
		"""Get the system prompt for task enhancement"""
		return """You are a task enhancement specialist for a browser automation agent. Your role is to provide MINIMAL clarification to help the agent understand completion criteria without adding unnecessary complexity.

Enhancement Guidelines:

1. For tasks with clear objectives but unclear completion criteria, add minimal clarification
2. For already specific tasks with clear endpoints, return unchanged
3. For vague tasks, ask for clarification or provide basic structure
4. NEVER add assumptions about specific methods, websites, or procedures
5. Focus on clarifying WHAT constitutes success, not HOW to achieve it
6. Preserve the user's original scope - don't expand the task
7. For tasks involving search criteria (price ranges, dates, locations, categories), suggest using available filters

Filter Usage Enhancement:
When tasks involve criteria that websites commonly filter by, add a note to use filters:
- Price ranges → "use available price filters if present"
- Date ranges → "use available date filters if present" 
- Location/distance → "use available location or distance filters if present"
- Categories/types → "use available category filters if present"
- Ratings/reviews → "use available rating filters if present"

Completion Criteria Clarification:
- "Get X" → "Locate and access X" (clarifies the endpoint)
- "Find the price" → "Find and display the current price" (clarifies what to do with the result)
- "Book a hotel" → unchanged (already clear endpoint)
- "Login to email" → unchanged (already clear endpoint)

Examples:
- "Get the report from the final environmental impact statement for Jamaica Bus Depot expansion" → "Locate and access the final environmental impact statement report for the Jamaica Bus Depot expansion"
- "Find the cheapest flight to Paris" → "Find and identify the cheapest available flight to Paris (use available price and date filters if present)"
- "Find hotels under $200 in downtown" → "Find and identify hotels under $200 in downtown area (use available price and location filters if present)"
- "Book a hotel in Paris for next week" → unchanged (already clear)
- "Find stuff" → "Find specific information (please clarify what you're looking for)"

Focus: Clarify completion criteria and suggest efficient filtering when applicable, without adding complexity or assumptions."""
