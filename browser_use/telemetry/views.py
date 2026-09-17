from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any, Literal

from browser_use.config import is_running_in_docker


@dataclass
class BaseTelemetryEvent(ABC):
	@property
	@abstractmethod
	def name(self) -> str:
		pass

	@property
	def properties(self) -> dict[str, Any]:
		props = {k: v for k, v in asdict(self).items() if k != 'name'}
		# Add Docker context if running in Docker
		props['is_docker'] = is_running_in_docker()
		return props


@dataclass
class AgentTelemetryEvent(BaseTelemetryEvent):
	"""Telemetry event sent for each agent run when ANONYMIZED_TELEMETRY is enabled (the default).

	The *identifier* PostHog associates with events is anonymous, but the *content* of this
	event is a fairly complete transcript of the run: the full task prompt (``task``), every
	URL visited (``urls_visited``), the actions taken including any text typed into pages
	(``action_history``), and the data the agent read off the page (``final_result_response``).
	If you run this against internal tools, authenticated dashboards, or with sensitive
	business context in the prompt, that content leaves your machine by default. Disable with
	``ANONYMIZED_TELEMETRY=false`` if that's not acceptable for your use case.
	"""

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

	version: str
	action: str  # 'start', 'stop', 'tool_call'
	tool_name: str | None = None
	duration_seconds: float | None = None
	error_message: str | None = None
	parent_process_cmdline: str | None = None

	name: str = 'mcp_server_event'
