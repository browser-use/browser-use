"""Data models for code-use mode."""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr
from uuid_extensions import uuid7str

from browser_use.tokens.views import UsageSummary


class CellType(str, Enum):
	"""Type of notebook cell."""

	CODE = 'code'
	MARKDOWN = 'markdown'


class ExecutionStatus(str, Enum):
	"""Execution status of a cell."""

	PENDING = 'pending'
	RUNNING = 'running'
	SUCCESS = 'success'
	ERROR = 'error'


class CodeCell(BaseModel):
	"""Represents a code cell in the notebook-like execution."""

	model_config = ConfigDict(extra='forbid')

	id: str = Field(default_factory=uuid7str)
	cell_type: CellType = CellType.CODE
	source: str = Field(description='The code to execute')
	output: str | None = Field(default=None, description='The output of the code execution')
	execution_count: int | None = Field(default=None, description='The execution count')
	status: ExecutionStatus = Field(default=ExecutionStatus.PENDING)
	error: str | None = Field(default=None, description='Error message if execution failed')
	browser_state: str | None = Field(default=None, description='Browser state after execution')


class NotebookSession(BaseModel):
	"""Represents a notebook-like session."""

	model_config = ConfigDict(extra='forbid')

	id: str = Field(default_factory=uuid7str)
	cells: list[CodeCell] = Field(default_factory=list)
	current_execution_count: int = Field(default=0)
	namespace: dict[str, Any] = Field(default_factory=dict, description='Current namespace state')
	_complete_history: list[CodeAgentHistory] = PrivateAttr(default_factory=list)
	_usage_summary: UsageSummary | None = PrivateAttr(default=None)

	def add_cell(self, source: str) -> CodeCell:
		"""Add a new code cell to the session."""
		cell = CodeCell(source=source)
		self.cells.append(cell)
		return cell

	def get_cell(self, cell_id: str) -> CodeCell | None:
		"""Get a cell by ID."""
		for cell in self.cells:
			if cell.id == cell_id:
				return cell
		return None

	def get_latest_cell(self) -> CodeCell | None:
		"""Get the most recently added cell."""
		if self.cells:
			return self.cells[-1]
		return None

	def increment_execution_count(self) -> int:
		"""Increment and return the execution count."""
		self.current_execution_count += 1
		return self.current_execution_count

	@property
	def history(self) -> CodeAgentHistoryList:
		"""Get the history as an AgentHistoryList-compatible object."""
		return CodeAgentHistoryList(self._complete_history, self._usage_summary)


class NotebookExport(BaseModel):
	"""Export format for Jupyter notebook."""

	model_config = ConfigDict(extra='forbid')

	nbformat: int = Field(default=4)
	nbformat_minor: int = Field(default=5)
	metadata: dict[str, Any] = Field(default_factory=dict)
	cells: list[dict[str, Any]] = Field(default_factory=list)


class CodeAgentModelOutput(BaseModel):
	"""Model output for CodeAgent - contains the code and full LLM response."""

	model_config = ConfigDict(extra='forbid')

	model_output: str = Field(description='The extracted code from the LLM response')
	full_response: str = Field(description='The complete LLM response including any text/reasoning')


class CodeAgentResult(BaseModel):
	"""Result of executing a code cell in CodeAgent."""

	model_config = ConfigDict(extra='forbid')

	extracted_content: str | None = Field(default=None, description='Output from code execution')
	error: str | None = Field(default=None, description='Error message if execution failed')
	is_done: bool = Field(default=False, description='Whether task is marked as done')
	success: bool | None = Field(default=None, description='Self-reported success from done() call')


class CodeAgentState(BaseModel):
	"""State information for a CodeAgent step."""

	model_config = ConfigDict(extra='forbid', arbitrary_types_allowed=True)

	url: str | None = Field(default=None, description='Current page URL')
	title: str | None = Field(default=None, description='Current page title')
	screenshot_path: str | None = Field(default=None, description='Path to screenshot file')

	def get_screenshot(self) -> str | None:
		"""Load screenshot from disk and return as base64 string."""
		if not self.screenshot_path:
			return None

		import base64
		from pathlib import Path

		path_obj = Path(self.screenshot_path)
		if not path_obj.exists():
			return None

		try:
			with open(path_obj, 'rb') as f:
				screenshot_data = f.read()
			return base64.b64encode(screenshot_data).decode('utf-8')
		except Exception:
			return None


class CodeAgentStepMetadata(BaseModel):
	"""Metadata for a single CodeAgent step including timing and token information."""

	model_config = ConfigDict(extra='forbid')

	input_tokens: int | None = Field(default=None, description='Number of input tokens used')
	output_tokens: int | None = Field(default=None, description='Number of output tokens used')
	step_start_time: float = Field(description='Step start timestamp (Unix time)')
	step_end_time: float = Field(description='Step end timestamp (Unix time)')

	@property
	def duration_seconds(self) -> float:
		"""Calculate step duration in seconds."""
		return self.step_end_time - self.step_start_time


class CodeAgentHistory(BaseModel):
	"""History item for CodeAgent actions."""

	model_config = ConfigDict(extra='forbid', arbitrary_types_allowed=True)

	model_output: CodeAgentModelOutput | None = Field(default=None, description='LLM output for this step')
	result: list[CodeAgentResult] = Field(default_factory=list, description='Results from code execution')
	state: CodeAgentState = Field(description='Browser state at this step')
	metadata: CodeAgentStepMetadata | None = Field(default=None, description='Step timing and token metadata')
	screenshot_path: str | None = Field(default=None, description='Legacy field for screenshot path')

	def model_dump(self, **kwargs) -> dict[str, Any]:
		"""Custom serialization for CodeAgentHistory."""
		return {
			'model_output': self.model_output.model_dump() if self.model_output else None,
			'result': [r.model_dump() for r in self.result],
			'state': self.state.model_dump(),
			'metadata': self.metadata.model_dump() if self.metadata else None,
			'screenshot_path': self.screenshot_path,
		}


class CodeAgentHistoryList:
	"""Compatibility wrapper for CodeAgentHistory that provides AgentHistoryList-like API."""

	def __init__(self, complete_history: list[CodeAgentHistory], usage_summary: UsageSummary | None) -> None:
		"""Initialize with CodeAgent history data."""
		self._complete_history = complete_history
		self._usage_summary = usage_summary

	@property
	def history(self) -> list[CodeAgentHistory]:
		"""Get the raw history list."""
		return self._complete_history

	@property
	def usage(self) -> UsageSummary | None:
		"""Get the usage summary."""
		return self._usage_summary

	def __len__(self) -> int:
		"""Return the number of history items."""
		return len(self._complete_history)

	def __str__(self) -> str:
		"""Representation of the CodeAgentHistoryList object."""
		return f'CodeAgentHistoryList(steps={len(self._complete_history)}, action_results={len(self.action_results())})'

	def __repr__(self) -> str:
		"""Representation of the CodeAgentHistoryList object."""
		return self.__str__()

	def final_result(self) -> None | str:
		"""Final result from history."""
		if self._complete_history and self._complete_history[-1].result:
			return self._complete_history[-1].result[-1].extracted_content
		return None

	def is_done(self) -> bool:
		"""Check if the agent is done."""
		if self._complete_history and len(self._complete_history[-1].result) > 0:
			last_result = self._complete_history[-1].result[-1]
			return last_result.is_done is True
		return False

	def is_successful(self) -> bool | None:
		"""Check if the agent completed successfully."""
		if self._complete_history and len(self._complete_history[-1].result) > 0:
			last_result = self._complete_history[-1].result[-1]
			if last_result.is_done is True:
				return last_result.success
		return None

	def errors(self) -> list[str | None]:
		"""Get all errors from history, with None for steps without errors."""
		errors = []
		for h in self._complete_history:
			step_errors = [r.error for r in h.result if r.error]
			# each step can have only one error
			errors.append(step_errors[0] if step_errors else None)
		return errors

	def has_errors(self) -> bool:
		"""Check if the agent has any non-None errors."""
		return any(error is not None for error in self.errors())

	def urls(self) -> list[str | None]:
		"""Get all URLs from history."""
		return [h.state.url if h.state.url is not None else None for h in self._complete_history]

	def screenshot_paths(self, n_last: int | None = None, return_none_if_not_screenshot: bool = True) -> list[str | None]:
		"""Get all screenshot paths from history."""
		if n_last == 0:
			return []
		if n_last is None:
			if return_none_if_not_screenshot:
				return [h.state.screenshot_path if h.state.screenshot_path is not None else None for h in self._complete_history]
			else:
				return [h.state.screenshot_path for h in self._complete_history if h.state.screenshot_path is not None]
		else:
			if return_none_if_not_screenshot:
				return [
					h.state.screenshot_path if h.state.screenshot_path is not None else None
					for h in self._complete_history[-n_last:]
				]
			else:
				return [h.state.screenshot_path for h in self._complete_history[-n_last:] if h.state.screenshot_path is not None]

	def screenshots(self, n_last: int | None = None, return_none_if_not_screenshot: bool = True) -> list[str | None]:
		"""Get all screenshots from history as base64 strings."""
		if n_last == 0:
			return []
		history_items = self._complete_history if n_last is None else self._complete_history[-n_last:]
		screenshots = []
		for item in history_items:
			screenshot_b64 = item.state.get_screenshot()
			if screenshot_b64:
				screenshots.append(screenshot_b64)
			else:
				if return_none_if_not_screenshot:
					screenshots.append(None)
		return screenshots

	def action_results(self) -> list[CodeAgentResult]:
		"""Get all results from history."""
		results = []
		for h in self._complete_history:
			results.extend([r for r in h.result if r])
		return results

	def extracted_content(self) -> list[str]:
		"""Get all extracted content from history."""
		content = []
		for h in self._complete_history:
			content.extend([r.extracted_content for r in h.result if r.extracted_content])
		return content

	def number_of_steps(self) -> int:
		"""Get the number of steps in the history."""
		return len(self._complete_history)

	def total_duration_seconds(self) -> float:
		"""Get total duration of all steps in seconds."""
		total = 0.0
		for h in self._complete_history:
			if h.metadata:
				total += h.metadata.duration_seconds
		return total

	def last_action(self) -> None | dict:
		"""Last action in history - returns the last code execution."""
		if self._complete_history and self._complete_history[-1].model_output:
			return {
				'execute_code': {
					'code': self._complete_history[-1].model_output.model_output,
					'full_response': self._complete_history[-1].model_output.full_response,
				}
			}
		return None

	def action_names(self) -> list[str]:
		"""Get all action names from history - returns 'execute_code' for each code execution."""
		action_names = []
		for action in self.model_actions():
			actions = list(action.keys())
			if actions:
				action_names.append(actions[0])
		return action_names

	def model_thoughts(self) -> list[Any]:
		"""Get all thoughts from history - returns model_output for CodeAgent."""
		return [h.model_output for h in self._complete_history if h.model_output]

	def model_outputs(self) -> list[CodeAgentModelOutput]:
		"""Get all model outputs from history."""
		return [h.model_output for h in self._complete_history if h.model_output]

	def model_actions(self) -> list[dict]:
		"""Get all actions from history - returns code execution actions with their code."""
		actions = []
		for h in self._complete_history:
			if h.model_output:
				# Create one action dict per result (code execution)
				for _ in h.result:
					action_dict = {
						'execute_code': {
							'code': h.model_output.model_output,
							'full_response': h.model_output.full_response,
						}
					}
					actions.append(action_dict)
		return actions

	def action_history(self) -> list[list[dict]]:
		"""Get truncated action history grouped by step."""
		step_outputs = []
		for h in self._complete_history:
			step_actions = []
			if h.model_output:
				for result in h.result:
					action_dict = {
						'execute_code': {
							'code': h.model_output.model_output,
						},
						'result': {
							'extracted_content': result.extracted_content,
							'is_done': result.is_done,
							'success': result.success,
							'error': result.error,
						},
					}
					step_actions.append(action_dict)
			step_outputs.append(step_actions)
		return step_outputs

	def model_actions_filtered(self, include: list[str] | None = None) -> list[dict]:
		"""Get all model actions from history filtered - returns empty for CodeAgent."""
		return []

	def add_item(self, history_item: CodeAgentHistory) -> None:
		"""Add a history item to the list."""
		self._complete_history.append(history_item)

	def model_dump(self, **kwargs) -> dict[str, Any]:
		"""Custom serialization for CodeAgentHistoryList."""
		return {
			'history': [h.model_dump(**kwargs) for h in self._complete_history],
			'usage': self._usage_summary.model_dump() if self._usage_summary else None,
		}

	def save_to_file(self, filepath: str | Path, sensitive_data: dict[str, str | dict[str, str]] | None = None) -> None:
		"""Save history to JSON file."""
		try:
			Path(filepath).parent.mkdir(parents=True, exist_ok=True)
			data = self.model_dump()
			with open(filepath, 'w', encoding='utf-8') as f:
				json.dump(data, f, indent=2)
		except Exception as e:
			raise e
