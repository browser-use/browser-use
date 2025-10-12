from __future__ import annotations

import json
import logging
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, Literal

from openai import RateLimitError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model, model_validator
from typing_extensions import TypeVar
from uuid_extensions import uuid7str

from browser_use.agent.message_manager.views import MessageManagerState
from browser_use.browser.views import BrowserStateHistory
from browser_use.dom.views import DEFAULT_INCLUDE_ATTRIBUTES, DOMInteractedElement, DOMSelectorMap

# from browser_use.dom.history_tree_processor.service import (
# 	DOMElementNode,
# 	DOMHistoryElement,
# 	HistoryTreeProcessor,
# )
# from browser_use.dom.views import SelectorMap
from browser_use.filesystem.file_system import FileSystemState
from browser_use.llm.base import BaseChatModel
from browser_use.tokens.views import UsageSummary
from browser_use.tools.registry.views import ActionModel

logger = logging.getLogger(__name__)


class AgentSettings(BaseModel):
	"""Configuration options for the Agent"""

	use_vision: bool | Literal['auto'] = 'auto'
	vision_detail_level: Literal['auto', 'low', 'high'] = 'auto'
	save_conversation_path: str | Path | None = None
	save_conversation_path_encoding: str | None = 'utf-8'
	max_failures: int = 3
	generate_gif: bool | str = False
	override_system_message: str | None = None
	extend_system_message: str | None = None
	include_attributes: list[str] | None = DEFAULT_INCLUDE_ATTRIBUTES
	max_actions_per_step: int = 4
	use_thinking: bool = True
	flash_mode: bool = False  # If enabled, disables evaluation_previous_goal and next_goal, and sets use_thinking = False
	max_history_items: int | None = None

	page_extraction_llm: BaseChatModel | None = None
	calculate_cost: bool = False
	include_tool_call_examples: bool = False
	llm_timeout: int = 60  # Timeout in seconds for LLM calls (auto-detected: 30s for gemini, 90s for o3, 60s default)
	step_timeout: int = 180  # Timeout in seconds for each step
	final_response_after_failure: bool = True  # If True, attempt one final recovery call after max_failures


class AgentState(BaseModel):
	"""Holds all state information for an Agent"""

	model_config = ConfigDict(arbitrary_types_allowed=True)

	agent_id: str = Field(default_factory=uuid7str)
	n_steps: int = 1
	consecutive_failures: int = 0
	last_result: list[ActionResult] | None = None
	last_plan: str | None = None
	last_model_output: AgentOutput | None = None

	# Pause/resume state (kept serialisable for checkpointing)
	paused: bool = False
	stopped: bool = False
	session_initialized: bool = False  # Track if session events have been dispatched
	follow_up_task: bool = False  # Track if the agent is a follow-up task

	message_manager_state: MessageManagerState = Field(default_factory=MessageManagerState)
	file_system_state: FileSystemState | None = None


@dataclass
class AgentStepInfo:
	step_number: int
	max_steps: int

	def is_last_step(self) -> bool:
		"""Check if this is the last step"""
		return self.step_number >= self.max_steps - 1


class ActionResult(BaseModel):
	"""Result of executing an action"""

	# For done action
	is_done: bool | None = False
	success: bool | None = None

	# Error handling - always include in long term memory
	error: str | None = None

	# Files
	attachments: list[str] | None = None  # Files to display in the done message

	# Always include in long term memory
	long_term_memory: str | None = None  # Memory of this action

	# if update_only_read_state is True we add the extracted_content to the agent context only once for the next step
	# if update_only_read_state is False we add the extracted_content to the agent long term memory if no long_term_memory is provided
	extracted_content: str | None = None
	include_extracted_content_only_once: bool = False  # Whether the extracted content should be used to update the read_state

	# Metadata for observability (e.g., click coordinates)
	metadata: dict | None = None

	# Deprecated
	include_in_memory: bool = False  # whether to include in extracted_content inside long_term_memory

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
	step_number: int

	@property
	def duration_seconds(self) -> float:
		"""Calculate step duration in seconds"""
		return self.step_end_time - self.step_start_time


class AgentBrain(BaseModel):
	thinking: str | None = None
	evaluation_previous_goal: str
	memory: str
	next_goal: str


class AgentOutput(BaseModel):
	model_config = ConfigDict(arbitrary_types_allowed=True, extra='forbid')

	thinking: str | None = None
	evaluation_previous_goal: str | None = None
	memory: str | None = None
	next_goal: str | None = None
	action: list[ActionModel] = Field(
		...,
		json_schema_extra={'min_items': 1},  # Ensure at least one action is provided
	)

	@classmethod
	def model_json_schema(cls, **kwargs):
		schema = super().model_json_schema(**kwargs)
		schema['required'] = ['evaluation_previous_goal', 'memory', 'next_goal', 'action']
		return schema

	@property
	def current_state(self) -> AgentBrain:
		"""For backward compatibility - returns an AgentBrain with the flattened properties"""
		return AgentBrain(
			thinking=self.thinking,
			evaluation_previous_goal=self.evaluation_previous_goal if self.evaluation_previous_goal else '',
			memory=self.memory if self.memory else '',
			next_goal=self.next_goal if self.next_goal else '',
		)

	@staticmethod
	def type_with_custom_actions(custom_actions: type[ActionModel]) -> type[AgentOutput]:
		"""Extend actions with custom actions"""

		model_ = create_model(
			'AgentOutput',
			__base__=AgentOutput,
			action=(
				list[custom_actions],  # type: ignore
				Field(..., description='List of actions to execute', json_schema_extra={'min_items': 1}),
			),
			__module__=AgentOutput.__module__,
		)
		return model_

	@staticmethod
	def type_with_custom_actions_no_thinking(custom_actions: type[ActionModel]) -> type[AgentOutput]:
		"""Extend actions with custom actions and exclude thinking field"""

		class AgentOutputNoThinking(AgentOutput):
			@classmethod
			def model_json_schema(cls, **kwargs):
				schema = super().model_json_schema(**kwargs)
				del schema['properties']['thinking']
				schema['required'] = ['evaluation_previous_goal', 'memory', 'next_goal', 'action']
				return schema

		model = create_model(
			'AgentOutput',
			__base__=AgentOutputNoThinking,
			action=(
				list[custom_actions],  # type: ignore
				Field(..., json_schema_extra={'min_items': 1}),
			),
			__module__=AgentOutputNoThinking.__module__,
		)

		return model

	@staticmethod
	def type_with_custom_actions_flash_mode(custom_actions: type[ActionModel]) -> type[AgentOutput]:
		"""Extend actions with custom actions for flash mode - memory and action fields only"""

		class AgentOutputFlashMode(AgentOutput):
			@classmethod
			def model_json_schema(cls, **kwargs):
				schema = super().model_json_schema(**kwargs)
				# Remove thinking, evaluation_previous_goal, and next_goal fields
				del schema['properties']['thinking']
				del schema['properties']['evaluation_previous_goal']
				del schema['properties']['next_goal']
				# Update required fields to only include remaining properties
				schema['required'] = ['memory', 'action']
				return schema

		model = create_model(
			'AgentOutput',
			__base__=AgentOutputFlashMode,
			action=(
				list[custom_actions],  # type: ignore
				Field(..., json_schema_extra={'min_items': 1}),
			),
			__module__=AgentOutputFlashMode.__module__,
		)

		return model


class AgentHistory(BaseModel):
	"""History item for agent actions"""

	model_output: AgentOutput | None
	result: list[ActionResult]
	state: BrowserStateHistory
	metadata: StepMetadata | None = None
	state_message: str | None = None

	model_config = ConfigDict(arbitrary_types_allowed=True, protected_namespaces=())

	@staticmethod
	def get_interacted_element(model_output: AgentOutput, selector_map: DOMSelectorMap) -> list[DOMInteractedElement | None]:
		elements = []
		for action in model_output.action:
			index = action.get_index()
			if index is not None and index in selector_map:
				el = selector_map[index]
				elements.append(DOMInteractedElement.load_from_enhanced_dom_tree(el))
			else:
				elements.append(None)
		return elements

	def _filter_sensitive_data_from_string(self, value: str, sensitive_data: dict[str, str | dict[str, str]] | None) -> str:
		"""Filter out sensitive data from a string value"""
		if not sensitive_data:
			return value

		# Collect all sensitive values, immediately converting old format to new format
		sensitive_values: dict[str, str] = {}

		# Process all sensitive data entries
		for key_or_domain, content in sensitive_data.items():
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
			return value

		# Replace all valid sensitive data values with their placeholder tags
		for key, val in sensitive_values.items():
			value = value.replace(val, f'<secret>{key}</secret>')

		return value

	def _filter_sensitive_data_from_dict(
		self, data: dict[str, Any], sensitive_data: dict[str, str | dict[str, str]] | None
	) -> dict[str, Any]:
		"""Recursively filter sensitive data from a dictionary"""
		if not sensitive_data:
			return data

		filtered_data = {}
		for key, value in data.items():
			if isinstance(value, str):
				filtered_data[key] = self._filter_sensitive_data_from_string(value, sensitive_data)
			elif isinstance(value, dict):
				filtered_data[key] = self._filter_sensitive_data_from_dict(value, sensitive_data)
			elif isinstance(value, list):
				filtered_data[key] = [
					self._filter_sensitive_data_from_string(item, sensitive_data)
					if isinstance(item, str)
					else self._filter_sensitive_data_from_dict(item, sensitive_data)
					if isinstance(item, dict)
					else item
					for item in value
				]
			else:
				filtered_data[key] = value
		return filtered_data

	def model_dump(self, sensitive_data: dict[str, str | dict[str, str]] | None = None, **kwargs) -> dict[str, Any]:
		"""Custom serialization handling circular references and filtering sensitive data"""

		# Handle action serialization
		model_output_dump = None
		if self.model_output:
			action_dump = [action.model_dump(exclude_none=True) for action in self.model_output.action]

			# Filter sensitive data only from input action parameters if sensitive_data is provided
			if sensitive_data:
				action_dump = [
					self._filter_sensitive_data_from_dict(action, sensitive_data) if 'input' in action else action
					for action in action_dump
				]

			model_output_dump = {
				'evaluation_previous_goal': self.model_output.evaluation_previous_goal,
				'memory': self.model_output.memory,
				'next_goal': self.model_output.next_goal,
				'action': action_dump,  # This preserves the actual action data
			}
			# Only include thinking if it's present
			if self.model_output.thinking is not None:
				model_output_dump['thinking'] = self.model_output.thinking

		# Handle result serialization - don't filter ActionResult data
		# as it should contain meaningful information for the agent
		result_dump = [r.model_dump(exclude_none=True) for r in self.result]

		return {
			'model_output': model_output_dump,
			'result': result_dump,
			'state': self.state.to_dict(),
			'metadata': self.metadata.model_dump() if self.metadata else None,
			'state_message': self.state_message,
		}


AgentStructuredOutput = TypeVar('AgentStructuredOutput', bound=BaseModel)


class AgentHistoryList(BaseModel, Generic[AgentStructuredOutput]):
	"""List of AgentHistory messages, i.e. the history of the agent's actions and thoughts."""

	history: list[AgentHistory]
	usage: UsageSummary | None = None

	_output_model_schema: type[AgentStructuredOutput] | None = None

	def total_duration_seconds(self) -> float:
		"""Get total duration of all steps in seconds"""
		total = 0.0
		for h in self.history:
			if h.metadata:
				total += h.metadata.duration_seconds
		return total

	def __len__(self) -> int:
		"""Return the number of history items"""
		return len(self.history)

	def __str__(self) -> str:
		"""Representation of the AgentHistoryList object"""
		return f'AgentHistoryList(all_results={self.action_results()}, all_model_outputs={self.model_actions()})'

	def add_item(self, history_item: AgentHistory) -> None:
		"""Add a history item to the list"""
		self.history.append(history_item)

	def __repr__(self) -> str:
		"""Representation of the AgentHistoryList object"""
		return self.__str__()

	def save_to_file(self, filepath: str | Path, sensitive_data: dict[str, str | dict[str, str]] | None = None) -> None:
		"""Save history to JSON file with proper serialization and optional sensitive data filtering"""
		try:
			Path(filepath).parent.mkdir(parents=True, exist_ok=True)
			data = self.model_dump(sensitive_data=sensitive_data)
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

	def screenshot_paths(self, n_last: int | None = None, return_none_if_not_screenshot: bool = True) -> list[str | None]:
		"""Get all screenshot paths from history"""
		if n_last == 0:
			return []
		if n_last is None:
			if return_none_if_not_screenshot:
				return [h.state.screenshot_path if h.state.screenshot_path is not None else None for h in self.history]
			else:
				return [h.state.screenshot_path for h in self.history if h.state.screenshot_path is not None]
		else:
			if return_none_if_not_screenshot:
				return [h.state.screenshot_path if h.state.screenshot_path is not None else None for h in self.history[-n_last:]]
			else:
				return [h.state.screenshot_path for h in self.history[-n_last:] if h.state.screenshot_path is not None]

	def screenshots(self, n_last: int | None = None, return_none_if_not_screenshot: bool = True) -> list[str | None]:
		"""Get all screenshots from history as base64 strings"""
		if n_last == 0:
			return []

		history_items = self.history if n_last is None else self.history[-n_last:]
		screenshots = []

		for item in history_items:
			screenshot_b64 = item.state.get_screenshot()
			if screenshot_b64:
				screenshots.append(screenshot_b64)
			else:
				if return_none_if_not_screenshot:
					screenshots.append(None)
				# If return_none_if_not_screenshot is False, we skip None values

		return screenshots

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
				# Guard against None interacted_element before zipping
				interacted_elements = h.state.interacted_element or [None] * len(h.model_output.action)
				for action, interacted_element in zip(h.model_output.action, interacted_elements):
					output = action.model_dump(exclude_none=True)
					output['interacted_element'] = interacted_element
					outputs.append(output)
		return outputs

	def action_history(self) -> list[list[dict]]:
		"""Get truncated action history with only essential fields"""
		step_outputs = []

		for h in self.history:
			step_actions = []
			if h.model_output:
				# Guard against None interacted_element before zipping
				interacted_elements = h.state.interacted_element or [None] * len(h.model_output.action)
				# Zip actions with interacted elements and results
				for action, interacted_element, result in zip(h.model_output.action, interacted_elements, h.result):
					action_output = action.model_dump(exclude_none=True)
					action_output['interacted_element'] = interacted_element
					# Only keep long_term_memory from result
					action_output['result'] = result.long_term_memory if result and result.long_term_memory else None
					step_actions.append(action_output)
			step_outputs.append(step_actions)

		return step_outputs

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

	@property
	def structured_output(self) -> AgentStructuredOutput | None:
		"""Get the structured output from the history

		Returns:
			The structured output if both final_result and _output_model_schema are available,
			otherwise None
		"""
		final_result = self.final_result()
		if final_result is not None and self._output_model_schema is not None:
			return self._output_model_schema.model_validate_json(final_result)

		return None


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
