from __future__ import annotations

import json
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Type

from langchain_core.language_models.chat_models import BaseChatModel
from openai import RateLimitError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from browser_use.agent.message_manager.views import MessageManagerState
from browser_use.browser.views import BrowserState, BrowserStateHistory
from browser_use.controller.registry.views import ActionModel
from browser_use.dom.history_tree_processor.service import (
	DOMElementNode,
	DOMHistoryElement,
	HistoryTreeProcessor,
)
from browser_use.dom.views import SelectorMap
import logging

logger = logging.getLogger(__name__)

ToolCallingMethod = Literal['function_calling', 'json_mode', 'raw', 'auto']


class AgentSettings(BaseModel):
	"""Options for the agent"""

	use_vision: bool = True
	use_vision_for_planner: bool = False
	save_conversation_path: Optional[str] = None
	save_conversation_path_encoding: Optional[str] = 'utf-8'
	max_failures: int = 3
	retry_delay: int = 10
	max_input_tokens: int = 128000
	validate_output: bool = False
	message_context: Optional[str] = None
	generate_gif: bool | str = False
	available_file_paths: Optional[list[str]] = None
	override_system_message: Optional[str] = None
	extend_system_message: Optional[str] = None
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

	tool_calling_method: Optional[ToolCallingMethod] = 'auto'
	page_extraction_llm: Optional[BaseChatModel] = None
	planner_llm: Optional[BaseChatModel] = None
	planner_interval: int = 1  # Run planner every N steps


class AgentState(BaseModel):
	"""State of the agent"""
	agent_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
	n_steps: int = 0
	consecutive_failures: int = 0
	stopped: bool = False
	last_result: Optional[List['ActionResult']] = None
	history: AgentHistoryList = Field(default_factory=lambda: AgentHistoryList(items=[]))
	last_plan: Optional[str] = None
	paused: bool = False
	message_manager_state: Optional[Dict[str, Any]] = None
	cached_run: bool = False


@dataclass
class AgentStepInfo:
	step: int
	max_steps: int
	browser_state: BrowserState
	errors: List[str]
	
	@property
	def recent_actions(self) -> List[str]:
		# Get the last 5 actions from browser state history
		if not self.browser_state:
			return []
		# Just return an empty list for now until we determine the correct attribute
		return []
	
	@property
	def has_errors(self) -> bool:
		return len(self.errors) > 0

	def is_last_step(self) -> bool:
		"""Check if this is the last step"""
		return self.step >= self.max_steps


class ActionResult(BaseModel):
	"""Result of executing an action"""

	is_done: Optional[bool] = False
	success: Optional[bool] = None
	extracted_content: Optional[str] = None
	error: Optional[str] = None
	include_in_memory: bool = False  # whether to include in past messages as context or not


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
	"""Current state of the agent"""

	evaluation_previous_goal: str
	memory: str
	next_goal: str


class AgentOutput(BaseModel):
	"""Output model for agent

	@dev note: this model is extended with custom actions in AgentService. You can also use some fields that are not in this model as provided by the linter, as long as they are registered in the DynamicActions model.
	"""

	model_config = ConfigDict(arbitrary_types_allowed=True)

	current_state: AgentBrain
	action: list[ActionModel] = Field(
		...,
		description='List of actions to execute',
		json_schema_extra={'min_items': 1},  # Ensure at least one action is provided
	)

	@staticmethod
	def type_with_custom_actions(custom_actions: Type[ActionModel]) -> Type['AgentOutput']:
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
	metadata: Optional[StepMetadata] = None

	model_config = ConfigDict(arbitrary_types_allowed=True, protected_namespaces=())

	@staticmethod
	def get_interacted_element(model_output: AgentOutput, selector_map: SelectorMap) -> list[DOMHistoryElement | None]:
		elements = []
		for action in model_output.action:
			index = action.get_index()
			if index and index in selector_map:
				el: DOMElementNode = selector_map[index]
				elements.append(HistoryTreeProcessor.convert_dom_element_to_history_element(el))
			else:
				elements.append(None)
		return elements

	def model_dump(self, **kwargs) -> Dict[str, Any]:
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

	def to_dict(self) -> Dict[str, Any]:
		"""Convert to dictionary"""
		return self.model_dump()


@dataclass
class AgentHistoryList:
	"""List of agent history items"""
	items: List[AgentHistory] = field(default_factory=list)
	
	def to_dict(self) -> Dict[str, Any]:
		"""Convert to dictionary"""
		return {
			"items": [item.to_dict() for item in self.items]
		}

	def total_duration_seconds(self) -> float:
		"""Get total duration of all steps in seconds"""
		total = 0.0
		for h in self.items:
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
		for h in self.items:
			if h.metadata:
				total += h.metadata.input_tokens
		return total

	def input_token_usage(self) -> list[int]:
		"""Get token usage for each step"""
		return [h.metadata.input_tokens for h in self.items if h.metadata]

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
			data = self.to_dict()
			with open(filepath, 'w', encoding='utf-8') as f:
				json.dump(data, f, indent=2)
		except Exception as e:
			raise e

	def model_dump(self, **kwargs) -> Dict[str, Any]:
		"""Custom serialization that properly uses AgentHistory's model_dump"""
		return {
			'items': [h.model_dump(**kwargs) for h in self.items],
		}

	@classmethod
	def load_from_file(cls, filepath: str | Path, output_model: Type[AgentOutput]) -> 'AgentHistoryList':
		"""Load history from JSON file"""
		with open(filepath, 'r', encoding='utf-8') as f:
			data = json.load(f)
		
		# Process the data to create AgentHistory objects
		history_items = []
		for h in data['items']:
			if h['model_output']:
				if isinstance(h['model_output'], dict):
					h['model_output'] = output_model.model_validate(h['model_output'])
				else:
					h['model_output'] = None
			if 'interacted_element' not in h['state']:
				h['state']['interacted_element'] = None
			
			# Create AgentHistory object
			history_item = AgentHistory.model_validate(h)
			history_items.append(history_item)
		
		# Create and return AgentHistoryList
		return cls(items=history_items)

	def last_action(self) -> None | dict:
		"""Last action in history"""
		if self.items and self.items[-1].model_output:
			return self.items[-1].model_output.action[-1].model_dump(exclude_none=True)
		return None

	def errors(self) -> list[str | None]:
		"""Get all errors from history, with None for steps without errors"""
		errors = []
		for h in self.items:
			step_errors = [r.error for r in h.result if r.error]

			# each step can have only one error
			errors.append(step_errors[0] if step_errors else None)
		return errors

	def final_result(self) -> None | str:
		"""Final result from history"""
		if self.items and self.items[-1].result[-1].extracted_content:
			return self.items[-1].result[-1].extracted_content
		return None

	def is_done(self) -> bool:
		"""Check if the agent is done"""
		if self.items and len(self.items[-1].result) > 0:
			last_result = self.items[-1].result[-1]
			return last_result.is_done is True
		return False

	def is_successful(self) -> bool | None:
		"""Check if the agent completed successfully - the agent decides in the last step if it was successful or not. None if not done yet."""
		if self.items and len(self.items[-1].result) > 0:
			last_result = self.items[-1].result[-1]
			if last_result.is_done is True:
				return last_result.success
		return None

	def has_errors(self) -> bool:
		"""Check if the agent has any non-None errors"""
		return any(error is not None for error in self.errors())

	def urls(self) -> list[str | None]:
		"""Get all unique URLs from history"""
		return [h.state.url if h.state.url is not None else None for h in self.items]

	def screenshots(self) -> list[str | None]:
		"""Get all screenshots from history"""
		return [h.state.screenshot if h.state.screenshot is not None else None for h in self.items]

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
		return [h.model_output.current_state for h in self.items if h.model_output]

	def model_outputs(self) -> list[AgentOutput]:
		"""Get all model outputs from history"""
		return [h.model_output for h in self.items if h.model_output]

	# get all actions with params
	def model_actions(self) -> list[dict]:
		"""Get all actions from history"""
		outputs = []

		for h in self.items:
			if h.model_output:
				for action, interacted_element in zip(h.model_output.action, h.state.interacted_element):
					output = action.model_dump(exclude_none=True)
					output['interacted_element'] = interacted_element
					outputs.append(output)
		return outputs

	def action_results(self) -> list[ActionResult]:
		"""Get all results from history"""
		results = []
		for h in self.items:
			results.extend([r for r in h.result if r])
		return results

	def extracted_content(self) -> list[str]:
		"""Get all extracted content from history"""
		content = []
		for h in self.items:
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
		return len(self.items)


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


@dataclass
class PlanningResult:
	"""Result of planning operation"""
	state_analysis: str
	progress_evaluation: str
	next_steps: str
	challenges: Optional[str] = None
	reasoning: Optional[str] = None
	
	@classmethod
	def from_json(cls, json_str: str) -> "PlanningResult":
		"""Create PlanningResult from JSON string"""
		try:
			data = json.loads(json_str)
			return cls(
				state_analysis=data.get("state_analysis", ""),
				progress_evaluation=data.get("progress_evaluation", ""),
				next_steps=data.get("next_steps", ""),
				challenges=data.get("challenges", None),
				reasoning=data.get("reasoning", None)
			)
		except Exception as e:
			logger.error(f"Error parsing planning result: {e}")
			return cls(
				state_analysis="Error parsing planning result",
				progress_evaluation="Unknown",
				next_steps="Continue with task",
			)
	
	def to_dict(self) -> Dict[str, Any]:
		"""Convert to dictionary"""
		return {
			"state_analysis": self.state_analysis,
			"progress_evaluation": self.progress_evaluation,
			"next_steps": self.next_steps,
			"challenges": self.challenges,
			"reasoning": self.reasoning
		}
