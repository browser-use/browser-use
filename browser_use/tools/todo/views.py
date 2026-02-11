"""Pydantic models for the todo_write tool."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TodoItem(BaseModel):
	"""A single todo item tracked by the agent."""

	model_config = ConfigDict(extra='forbid', populate_by_name=True)

	content: str = Field(description='Task description in imperative form (e.g. "Run tests")')
	status: Literal['pending', 'in_progress', 'completed'] = Field(description='Current task state')
	active_form: str = Field(
		alias='activeForm',
		description='Present continuous form shown during execution (e.g. "Running tests")',
	)


class TodoStats(BaseModel):
	"""Statistics about the current todo list."""

	total: int
	pending: int
	in_progress: int
	completed: int


class TodoWriteAction(BaseModel):
	"""Parameters for the todo_write action."""

	model_config = ConfigDict(extra='forbid', populate_by_name=True)

	todos: list[TodoItem] = Field(description='The complete updated todo list')
	replan: bool = Field(default=False, description='Set True to discard old plan and start fresh')
	replan_reason: str | None = Field(
		default=None,
		description='Why the old plan was wrong (recommended when replan=True)',
	)
