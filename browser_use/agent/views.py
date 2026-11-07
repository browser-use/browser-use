"""The result of Agent.run(): keeps the common 0.x AgentHistoryList methods."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic_ai.messages import ModelMessage

from browser_use.exceptions import removed
from browser_use.tools import ActionResult  # 0.x imported it from here

__all__ = ['ActionResult', 'AgentHistoryList']

# 0.x methods built on per-step browser state. 1.0 runs Python cells, so these have no faithful equivalent.
REMOVED = {
	'history',
	'urls',
	'screenshots',
	'screenshot_paths',
	'action_names',
	'action_history',
	'action_results',
	'model_thoughts',
	'model_outputs',
	'model_actions',
	'model_actions_filtered',
	'extracted_content',
	'agent_steps',
	'last_action',
	'save_to_file',
	'load_from_file',
	'get_structured_output',
	'add_item',
	'judgement',
	'is_judged',
	'is_validated',
}
HISTORY_ALTERNATIVE = (
	'the agent runs Python cells, not step actions: use final_result(), structured_output, errors(), .messages (the '
	'full transcript) or the files the agent saved in agent.workspace.'
)


@dataclass
class AgentHistoryList:
	status: str  # completed | timeout | max_steps | error
	text: str
	output: Any
	steps: int
	duration_s: float
	usage: dict[str, int]
	cost_usd: float | None  # None when a model's price is unknown
	partial: Any  # last checkpoint(..., partial=True) when unfinished
	error: str | None
	messages: list[ModelMessage]
	success: bool | None = True  # the agent's own verdict: finish(..., success=False) when it could not do the task
	output_schema: Any = None  # Agent(output_model_schema=...) (str when none); None: unknown, judged by the output

	def __post_init__(self) -> None:
		if self.status != 'completed':
			self.success = None

	def final_result(self) -> str | None:
		"""The answer text, or None when the run did not complete."""
		return self.text if self.status == 'completed' else None

	@property
	def structured_output(self) -> Any:
		"""The output_model_schema instance, or None. A Literal or StrEnum schema delivers a str: still structured."""
		if self.status != 'completed':
			return None
		structured = self.output_schema is not str if self.output_schema is not None else not isinstance(self.output, str)
		return self.output if structured else None

	def is_done(self) -> bool:
		return self.status == 'completed'

	def is_successful(self) -> bool | None:
		"""The agent's verdict: False when it finished but could not do the task; None when the run did not finish
		(0.x semantics). is_done() only says the run completed."""
		return self.success if self.status == 'completed' else None

	def errors(self) -> list[str]:
		"""The error that ended the run, if any. Unlike 0.x (one entry per step), cell errors the agent recovered from
		are not listed: they are in .messages (the python tool results)."""
		return [self.error] if self.error else []

	def has_errors(self) -> bool:
		"""True when an error ended the run (see errors())."""
		return self.error is not None

	def number_of_steps(self) -> int:
		return self.steps

	def total_duration_seconds(self) -> float:
		return self.duration_s

	@classmethod
	def load_from_file(cls, *args: Any, **kwargs: Any) -> Any:
		"""A 0.x classmethod: called on the class, __getattr__ never runs."""
		raise NotImplementedError(removed('AgentHistoryList.load_from_file', HISTORY_ALTERNATIVE))

	def __getattr__(self, name: str) -> Any:
		if name in REMOVED:
			raise NotImplementedError(removed(f'AgentHistoryList.{name}', HISTORY_ALTERNATIVE))
		raise AttributeError(f'{type(self).__name__!r} object has no attribute {name!r}')
