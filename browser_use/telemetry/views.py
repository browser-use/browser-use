from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class BaseTelemetryEvent(ABC):
	@property
	@abstractmethod
	def name(self) -> str:
		pass

	@property
	def properties(self) -> dict[str, Any]:
		return {k: v for k, v in asdict(self).items() if k != 'name'}


@dataclass
class AgentTelemetryEvent(BaseTelemetryEvent):
	# start details
	task: str
	model: str
	model_provider: str
	planner_llm: str | None
	max_steps: int
	max_actions_per_step: int
	use_vision: bool
	use_validation: bool
	version: str
	source: str
	# step details
	action_errors: Sequence[str | None]
	action_history: Sequence[list[dict] | None]
	urls_visited: Sequence[str | None]
	# end details
	steps: int
	total_input_tokens: int
	total_duration_seconds: float
	success: bool | None
	final_result_response: str | None
	error_message: str | None

	name: str = 'agent_event'
