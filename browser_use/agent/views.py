"""The result of Agent.run(): keeps the common 0.x AgentHistoryList methods."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic_ai.messages import ModelMessage

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

	def final_result(self) -> str | None:
		"""The answer text, or None when the run did not complete."""
		return self.text if self.status == 'completed' else None

	@property
	def structured_output(self) -> Any:
		"""The output_model_schema instance, or None."""
		return self.output if self.status == 'completed' and not isinstance(self.output, str) else None

	def is_done(self) -> bool:
		return self.status == 'completed'

	def is_successful(self) -> bool | None:
		"""True when the agent delivered a result; None when the run did not finish (0.x semantics)."""
		return True if self.status == 'completed' else None

	def errors(self) -> list[str]:
		return [self.error] if self.error else []

	def has_errors(self) -> bool:
		return self.error is not None

	def number_of_steps(self) -> int:
		return self.steps

	def total_duration_seconds(self) -> float:
		return self.duration_s

	def __getattr__(self, name: str) -> Any:
		if name in REMOVED:
			raise NotImplementedError(
				f'AgentHistoryList.{name} is not available in browser-use 1.0: the agent runs Python cells, not '
				'step actions. Use final_result(), structured_output, errors(), .messages (the full transcript) or '
				'files the agent saved in agent.workspace. See MIGRATING.md.'
			)
		raise AttributeError(f'{type(self).__name__!r} object has no attribute {name!r}')
