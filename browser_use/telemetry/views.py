from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Literal

from browser_use.config import is_running_in_docker


@dataclass
class BaseTelemetryEvent(ABC):
	# New fields must be reviewed before they can leave the process.
	telemetry_fields: ClassVar[tuple[str, ...]] = ()

	@property
	@abstractmethod
	def name(self) -> str:
		pass

	@property
	def properties(self) -> dict[str, Any]:
		props = {key: getattr(self, key) for key in self.telemetry_fields}
		# Add Docker context if running in Docker
		props['is_docker'] = is_running_in_docker()
		return props


@dataclass
class AgentTelemetryEvent(BaseTelemetryEvent):
	telemetry_fields: ClassVar[tuple[str, ...]] = (
		'model',
		'model_provider',
		'max_steps',
		'max_actions_per_step',
		'use_vision',
		'version',
		'source',
		'agent_type',
		'steps',
		'total_input_tokens',
		'total_output_tokens',
		'prompt_cached_tokens',
		'total_tokens',
		'total_duration_seconds',
		'success',
		'judge_verdict',
		'judge_reached_captcha',
		'judge_impossible_task',
	)
	# Content fields remain constructor-compatible for existing integrations,
	# but are never included in telemetry properties.
	# start details
	task: str
	model: str
	model_provider: str
	max_steps: int
	max_actions_per_step: int
	use_vision: bool | Literal['auto']
	version: str
	source: str
	cdp_url: str | None
	agent_type: str | None
	# step details
	action_errors: Sequence[str | None]
	action_history: Sequence[list[dict] | None]
	urls_visited: Sequence[str | None]
	# end details
	steps: int
	total_input_tokens: int
	total_output_tokens: int
	prompt_cached_tokens: int
	total_tokens: int
	total_duration_seconds: float
	success: bool | None
	final_result_response: str | None
	error_message: str | None
	# judge details
	judge_verdict: bool | None = None
	judge_reasoning: str | None = None
	judge_failure_reason: str | None = None
	judge_reached_captcha: bool | None = None
	judge_impossible_task: bool | None = None

	name: str = 'agent_event'


@dataclass
class MCPClientTelemetryEvent(BaseTelemetryEvent):
	"""Telemetry event for MCP client usage"""

	telemetry_fields: ClassVar[tuple[str, ...]] = ('tools_discovered', 'version', 'action', 'duration_seconds')

	server_name: str
	command: str
	tools_discovered: int
	version: str
	action: str  # 'connect', 'disconnect', 'tool_call'
	tool_name: str | None = None
	duration_seconds: float | None = None
	error_message: str | None = None

	name: str = 'mcp_client_event'


@dataclass
class MCPServerTelemetryEvent(BaseTelemetryEvent):
	"""Telemetry event for MCP server usage"""

	telemetry_fields: ClassVar[tuple[str, ...]] = ('version', 'action', 'duration_seconds')

	version: str
	action: str  # 'start', 'stop', 'tool_call'
	tool_name: str | None = None
	duration_seconds: float | None = None
	error_message: str | None = None
	parent_process_cmdline: str | None = None

	name: str = 'mcp_server_event'
