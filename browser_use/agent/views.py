from __future__ import annotations

import json
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from langchain_core.language_models.chat_models import BaseChatModel
from openai import RateLimitError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model, model_validator
from uuid_extensions import uuid7str

from browser_use.agent.message_manager.views import MessageManagerState
from browser_use.browser.views import BrowserStateHistory
from browser_use.controller.registry.views import ActionModel
from browser_use.dom.history_tree_processor.service import (
	DOMElementNode,
	DOMHistoryElement,
	HistoryTreeProcessor,
)
from browser_use.dom.views import SelectorMap

ToolCallingMethod = Literal['function_calling', 'json_mode', 'raw', 'auto', 'tools']
REQUIRED_LLM_API_ENV_VARS = {
	'ChatOpenAI': ['OPENAI_API_KEY'],
	'AzureChatOpenAI': ['AZURE_OPENAI_ENDPOINT', 'AZURE_OPENAI_KEY'],
	'ChatBedrockConverse': ['ANTHROPIC_API_KEY'],
	'ChatAnthropic': ['ANTHROPIC_API_KEY'],
	'ChatGoogleGenerativeAI': ['GOOGLE_API_KEY'],
	'ChatDeepSeek': ['DEEPSEEK_API_KEY'],
	'ChatOllama': [],
	'ChatGrok': ['GROK_API_KEY'],
}


class AgentSettings(BaseModel):
	"""Configuration options for the Agent"""

	use_vision: bool = True
	use_vision_for_planner: bool = False
	save_conversation_path: str | Path | None = None
	save_conversation_path_encoding: str | None = 'utf-8'
	max_failures: int = 3
	retry_delay: int = 10
	max_input_tokens: int = 128000
	validate_output: bool = False
	message_context: str | None = None
	generate_gif: bool | str = False
	available_file_paths: list[str] | None = None
	override_system_message: str | None = None
	extend_system_message: str | None = None
	include_attributes: list[str] = [
		'title',
		'type',
		'name',
		'role',
		'tabindex',
		'aria-label',
		'placeholder',
		'value',
		'alt',
		'aria-expanded',
	]
	max_actions_per_step: int = 10

	tool_calling_method: ToolCallingMethod | None = 'auto'
	page_extraction_llm: BaseChatModel | None = None
	planner_llm: BaseChatModel | None = None
	planner_interval: int = 1  # Run planner every N steps
	is_planner_reasoning: bool = False  # type: ignore
	extend_planner_system_message: str | None = None


class AgentState(BaseModel):
	"""Holds all state information for an Agent"""

	agent_id: str = Field(default_factory=uuid7str)
	n_steps: int = 1
	consecutive_failures: int = 0
	last_result: list[ActionResult] | None = None
	history: AgentHistoryList = Field(default_factory=lambda: AgentHistoryList(history=[]))
	last_plan: str | None = None
	paused: bool = False
	stopped: bool = False

	message_manager_state: MessageManagerState = Field(default_factory=MessageManagerState)

	# class Config:
	# 	arbitrary_types_allowed = True


@dataclass
class AgentStepInfo:
	step_number: int
	max_steps: int

	def is_last_step(self) -> bool:
		"""Check if this is the last step"""
		return self.step_number >= self.max_steps - 1


class ActionResult(BaseModel):
	"""Result of executing an action"""

	is_done: bool | None = False
	success: bool | None = None
	extracted_content: str | None = None
	error: str | None = None
	include_in_memory: bool = False  # whether to include in past messages as context or not

	@model_validator(mode='after')
	def validate_success_requires_done(self):
		"""Ensure success=True can only be set when is_done=True"""
		if self.success is True and self.is_done is not True:
			raise ValueError(
				'success=True can only be set when is_done=True. '
				'For regular actions that succeed, leave success as None. '
				'Use success=False only for actions that fail.'
			)
		return self


class StepMetadata(BaseModel):
	"""Metadata for a single step including timing and token information"""

	step_start_time: float
	step_end_time: float
	input_tokens: int  # Approximate tokens from message manager for this step
	step_number: int

	@property
	def duration_seconds(self) -> float:
		"""Calculate step duration in seconds"""
		return self.step_end_time - self.step_start_time


class AgentBrain(BaseModel):
	"""Current internal working memory of the agent, we ask the LLM to decide new values for these on each output"""

	evaluation_previous_goal: str
	memory: str
	next_goal: str


class AgentOutput(BaseModel):
	"""
	Output model for LLM, i.e. what we are expecting in LLM structured output in response to our prompt.
	{
		current_state: AgentBrain({
			evaluation_previous_goal: "we did ok, team",
			memory: "filled in xyz into page, still need to do xyz...",
			next_goal: "click on the link at index 127, then open that new tab"
		}),
		"action": [
			ActionModel({action_name: "click_element_by_index", action_params: {index: 127}}),
			ActionModel({action_name: "switch_to_tab", action_params: {page_id: 3}}),
			... other multi-action steps ...
		],
	}
	"""

	model_config = ConfigDict(arbitrary_types_allowed=True)

	current_state: AgentBrain
	action: list[ActionModel] = Field(
		...,
		description='List of actions to execute',
		json_schema_extra={'min_items': 1},  # Ensure at least one action is provided
	)

	@staticmethod
	def type_with_custom_actions(custom_actions: type[ActionModel]) -> type[AgentOutput]:
		"""Extend actions with custom actions"""
		model_ = create_model(
			'AgentOutput',
			__base__=AgentOutput,
			action=(
				list[custom_actions],
				Field(..., description='List of actions to execute', json_schema_extra={'min_items': 1}),
			),
			__module__=AgentOutput.__module__,
		)
		model_.__doc__ = 'AgentOutput model with custom actions'
		return model_


class AgentHistory(BaseModel):
	"""History item for agent actions"""

	model_output: AgentOutput | None
	result: list[ActionResult]
	state: BrowserStateHistory
	metadata: StepMetadata | None = None

	model_config = ConfigDict(arbitrary_types_allowed=True, protected_namespaces=())

	@staticmethod
	def get_interacted_element(model_output: AgentOutput, selector_map: SelectorMap) -> list[DOMHistoryElement | None]:
		elements = []
		for action in model_output.action:
			index = action.get_index()
			if index is not None and index in selector_map:
				el: DOMElementNode = selector_map[index]
				elements.append(HistoryTreeProcessor.convert_dom_element_to_history_element(el))
			else:
				elements.append(None)
		return elements

	def model_dump(self, **kwargs) -> dict[str, Any]:
		"""Custom serialization handling circular references"""

		# Handle action serialization
		model_output_dump = None
		if self.model_output:
			action_dump = [action.model_dump(exclude_none=True) for action in self.model_output.action]
			model_output_dump = {
				'current_state': self.model_output.current_state.model_dump(),
				'action': action_dump,  # This preserves the actual action data
			}

		return {
			'model_output': model_output_dump,
			'result': [r.model_dump(exclude_none=True) for r in self.result],
			'state': self.state.to_dict(),
			'metadata': self.metadata.model_dump() if self.metadata else None,
		}


class AgentHistoryList(BaseModel):
	"""List of AgentHistory messages, i.e. the history of the agent's actions and thoughts."""

	history: list[AgentHistory]

	def total_duration_seconds(self) -> float:
		"""Get total duration of all steps in seconds"""
		total = 0.0
		for h in self.history:
			if h.metadata:
				total += h.metadata.duration_seconds
		return total

	def total_input_tokens(self) -> int:
		"""
		Get total tokens used across all steps.
		Note: These are from the approximate token counting of the message manager.
		For accurate token counting, use tools like LangChain Smith or OpenAI's token counters.
		"""
		total = 0
		for h in self.history:
			if h.metadata:
				total += h.metadata.input_tokens
		return total

	def input_token_usage(self) -> list[int]:
		"""Get token usage for each step"""
		return [h.metadata.input_tokens for h in self.history if h.metadata]

	def __str__(self) -> str:
		"""Representation of the AgentHistoryList object"""
		return f'AgentHistoryList(all_results={self.action_results()}, all_model_outputs={self.model_actions()})'

	def __repr__(self) -> str:
		"""Representation of the AgentHistoryList object"""
		return self.__str__()

	def save_to_file(self, filepath: str | Path) -> None:
		"""Save history to JSON file with proper serialization"""
		try:
			Path(filepath).parent.mkdir(parents=True, exist_ok=True)
			data = self.model_dump()
			with open(filepath, 'w', encoding='utf-8') as f:
				json.dump(data, f, indent=2)
		except Exception as e:
			raise e

	# def save_as_playwright_script(
	# 	self,
	# 	output_path: str | Path,
	# 	sensitive_data_keys: list[str] | None = None,
	# 	browser_config: BrowserConfig | None = None,
	# 	context_config: BrowserContextConfig | None = None,
	# ) -> None:
	# 	"""
	# 	Generates a Playwright script based on the agent's history and saves it to a file.
	# 	Args:
	# 		output_path: The path where the generated Python script will be saved.
	# 		sensitive_data_keys: A list of keys used as placeholders for sensitive data
	# 							 (e.g., ['username_placeholder', 'password_placeholder']).
	# 							 These will be loaded from environment variables in the
	# 							 generated script.
	# 		browser_config: Configuration of the original Browser instance.
	# 		context_config: Configuration of the original BrowserContext instance.
	# 	"""
	# 	from browser_use.agent.playwright_script_generator import PlaywrightScriptGenerator

	# 	try:
	# 		serialized_history = self.model_dump()['history']
	# 		generator = PlaywrightScriptGenerator(serialized_history, sensitive_data_keys, browser_config, context_config)

	# 		script_content = generator.generate_script_content()
	# 		path_obj = Path(output_path)
	# 		path_obj.parent.mkdir(parents=True, exist_ok=True)
	# 		with open(path_obj, 'w', encoding='utf-8') as f:
	# 			f.write(script_content)
	# 	except Exception as e:
	# 		raise e

	def model_dump(self, **kwargs) -> dict[str, Any]:
		"""Custom serialization that properly uses AgentHistory's model_dump"""
		return {
			'history': [h.model_dump(**kwargs) for h in self.history],
		}

	@classmethod
	def load_from_file(cls, filepath: str | Path, output_model: type[AgentOutput]) -> AgentHistoryList:
		"""Load history from JSON file"""
		with open(filepath, encoding='utf-8') as f:
			data = json.load(f)
		# loop through history and validate output_model actions to enrich with custom actions
		for h in data['history']:
			if h['model_output']:
				if isinstance(h['model_output'], dict):
					h['model_output'] = output_model.model_validate(h['model_output'])
				else:
					h['model_output'] = None
			if 'interacted_element' not in h['state']:
				h['state']['interacted_element'] = None
		history = cls.model_validate(data)
		return history

	def last_action(self) -> None | dict:
		"""Last action in history"""
		if self.history and self.history[-1].model_output:
			return self.history[-1].model_output.action[-1].model_dump(exclude_none=True)
		return None

	def errors(self) -> list[str | None]:
		"""Get all errors from history, with None for steps without errors"""
		errors = []
		for h in self.history:
			step_errors = [r.error for r in h.result if r.error]

			# each step can have only one error
			errors.append(step_errors[0] if step_errors else None)
		return errors

	def final_result(self) -> None | str:
		"""Final result from history"""
		if self.history and self.history[-1].result[-1].extracted_content:
			return self.history[-1].result[-1].extracted_content
		return None

	def is_done(self) -> bool:
		"""Check if the agent is done"""
		if self.history and len(self.history[-1].result) > 0:
			last_result = self.history[-1].result[-1]
			return last_result.is_done is True
		return False

	def is_successful(self) -> bool | None:
		"""Check if the agent completed successfully - the agent decides in the last step if it was successful or not. None if not done yet."""
		if self.history and len(self.history[-1].result) > 0:
			last_result = self.history[-1].result[-1]
			if last_result.is_done is True:
				return last_result.success
		return None

	def has_errors(self) -> bool:
		"""Check if the agent has any non-None errors"""
		return any(error is not None for error in self.errors())

	def urls(self) -> list[str | None]:
		"""Get all unique URLs from history"""
		return [h.state.url if h.state.url is not None else None for h in self.history]

	def screenshots(self) -> list[str | None]:
		"""Get all screenshots from history"""
		return [h.state.screenshot if h.state.screenshot is not None else None for h in self.history]

	def action_names(self) -> list[str]:
		"""Get all action names from history"""
		action_names = []
		for action in self.model_actions():
			actions = list(action.keys())
			if actions:
				action_names.append(actions[0])
		return action_names

	def model_thoughts(self) -> list[AgentBrain]:
		"""Get all thoughts from history"""
		return [h.model_output.current_state for h in self.history if h.model_output]

	def model_outputs(self) -> list[AgentOutput]:
		"""Get all model outputs from history"""
		return [h.model_output for h in self.history if h.model_output]

	# get all actions with params
	def model_actions(self) -> list[dict]:
		"""Get all actions from history"""
		outputs = []

		for h in self.history:
			if h.model_output:
				for action, interacted_element in zip(h.model_output.action, h.state.interacted_element):
					output = action.model_dump(exclude_none=True)
					output['interacted_element'] = interacted_element
					outputs.append(output)
		return outputs

	def action_results(self) -> list[ActionResult]:
		"""Get all results from history"""
		results = []
		for h in self.history:
			results.extend([r for r in h.result if r])
		return results

	def extracted_content(self) -> list[str]:
		"""Get all extracted content from history"""
		content = []
		for h in self.history:
			content.extend([r.extracted_content for r in h.result if r.extracted_content])
		return content

	def model_actions_filtered(self, include: list[str] | None = None) -> list[dict]:
		"""Get all model actions from history as JSON"""
		if include is None:
			include = []
		outputs = self.model_actions()
		result = []
		for o in outputs:
			for i in include:
				if i == list(o.keys())[0]:
					result.append(o)
		return result

	def number_of_steps(self) -> int:
		"""Get the number of steps in the history"""
		return len(self.history)


class AgentError:
	"""Container for agent error handling"""

	VALIDATION_ERROR = 'Invalid model output format. Please follow the correct schema.'
	RATE_LIMIT_ERROR = 'Rate limit reached. Waiting before retry.'
	NO_VALID_ACTION = 'No valid action found'

	@staticmethod
	def format_error(error: Exception, include_trace: bool = False) -> str:
		"""Format error message based on error type and optionally include trace"""
		message = ''
		if isinstance(error, ValidationError):
			return f'{AgentError.VALIDATION_ERROR}\nDetails: {str(error)}'
		if isinstance(error, RateLimitError):
			return AgentError.RATE_LIMIT_ERROR
		if include_trace:
			return f'{str(error)}\nStacktrace:\n{traceback.format_exc()}'
		return f'{str(error)}'
