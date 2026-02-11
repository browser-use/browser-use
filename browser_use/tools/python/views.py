"""Pydantic models and dataclasses for the python REPL tool."""

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


@dataclass
class ExecutionCell:
	"""Record of a single code execution."""

	execution_count: int
	source: str
	output: str | None = None
	error: str | None = None
	variables_created: list[str] = field(default_factory=list)


@dataclass
class PythonSession:
	"""Persistent Python execution session.

	Maintains the namespace (variables) across multiple python() calls,
	like Jupyter notebook cells.
	"""

	namespace: dict[str, Any] = field(default_factory=dict)
	execution_count: int = 0
	history: list[ExecutionCell] = field(default_factory=list)

	def increment_execution_count(self) -> int:
		"""Increment and return the execution count."""
		self.execution_count += 1
		return self.execution_count

	def add_history(
		self,
		source: str,
		output: str | None = None,
		error: str | None = None,
		variables_created: list[str] | None = None,
	) -> ExecutionCell:
		"""Add an execution to history."""
		cell = ExecutionCell(
			execution_count=self.execution_count,
			source=source,
			output=output,
			error=error,
			variables_created=variables_created or [],
		)
		self.history.append(cell)
		return cell


class PythonAction(BaseModel):
	"""Parameters for the python action."""

	model_config = ConfigDict(extra='forbid')

	code: str = Field(description='Python code to execute')
