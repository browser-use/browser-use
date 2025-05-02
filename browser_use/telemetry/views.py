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
class RegisteredFunction:
	name: str
	params: dict[str, Any]


@dataclass
class ControllerRegisteredFunctionsTelemetryEvent(BaseTelemetryEvent):
	registered_functions: list[RegisteredFunction]
	name: str = 'controller_registered_functions'


@dataclass
class AgentStepTelemetryEvent(BaseTelemetryEvent):
	agent_id: str
	step: int
	step_error: list[str]
	consecutive_failures: int
	actions: list[dict]
	name: str = 'agent_step'


@dataclass
class AgentRunTelemetryEvent(BaseTelemetryEvent):
	agent_id: str
	use_vision: bool
	task: str
	model_name: str
	chat_model_library: str
	version: str
	source: str
	name: str = 'agent_run'


@dataclass
class AgentEndTelemetryEvent(BaseTelemetryEvent):
	agent_id: str
	steps: int
	max_steps_reached: bool
	is_done: bool
	success: bool | None
	total_input_tokens: int
	total_duration_seconds: float

	errors: Sequence[str | None]
	name: str = 'agent_end'
