"""Data models for code-use mode."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from uuid_extensions import uuid7str


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
