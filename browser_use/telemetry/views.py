from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any

SCHEMA_VERSION = 2  # 2: no task, result, code, typed text, URLs or error messages (TELEMETRY.md)


@dataclass
class BaseTelemetryEvent(ABC):
	@property
	@abstractmethod
	def name(self) -> str:
		pass

	@property
	def properties(self) -> dict[str, Any]:
		from browser_use.telemetry.stats import environment

		props = {k: v for k, v in asdict(self).items() if k != 'name'}
		return {**environment(), **props, 'schema_version': SCHEMA_VERSION}


@dataclass
class AgentTelemetryEvent(BaseTelemetryEvent):
	"""One per Agent.run(). Every field is a number, a bool, an enum, a name chosen by browser-use or the developer
	(model, helper, tool, module, exception class) or a hostname. TELEMETRY.md lists each one."""

	# install
	version: str
	source: str  # how browser-use is installed: pip | uv | editable | git | unknown
	agent_type: str = 'pydantic'
	run_id: str = ''
	# configuration
	model: str = ''
	model_provider: str = ''
	reasoning: str | None = None
	mode: str = 'default'
	max_steps: int = 0
	timeout_s: float = 0
	structured_output: bool = False
	output_schema_fields: int | None = None
	custom_tools: list[str] = field(default_factory=list)
	sensitive_data_count: int = 0
	sensitive_data_domain_scoped: int = 0
	extend_system_message: bool = False
	custom_workspace: bool = False
	follow_up: bool = False  # add_new_task() continued an earlier conversation
	task_chars: int = 0  # the length only; the task text is never sent
	# browser
	browser_mode: str = ''  # cloud | chromium | chrome | cdp (Browser.kind)
	cdp_url: str | None = None  # hostname only, for Browser(cdp_url=...)
	keep_alive: bool = False
	cloud_profile: bool = False
	cloud_proxy_country: str | None = None
	cloud_timeout_min: int | None = None
	live_view: bool = False
	browser_start_seconds: float | None = None
	# outcome
	status: str = ''  # completed | timeout | max_steps | error | cancelled
	success: bool | None = None
	max_steps_hit: bool = False
	timed_out: bool = False
	finish_via: str | None = None  # finish | finish_from_repl | text
	partial_used: bool = False
	error_type: str | None = None  # exception class only, never its message
	output_chars: int = 0
	total_duration_seconds: float = 0.0
	# model
	steps: int = 0
	model_requests: int = 0
	total_input_tokens: int = 0
	total_output_tokens: int = 0
	prompt_cached_tokens: int = 0
	cache_write_tokens: int = 0
	total_tokens: int = 0
	cost_usd: float | None = None
	tool_calls: dict[str, int] = field(default_factory=dict)
	retry_prompts: int = 0
	# REPL
	cells: int = 0
	cell_errors: int = 0
	cell_seconds: float = 0.0
	cell_error_types: dict[str, int] = field(default_factory=dict)
	helper_counts: dict[str, int] = field(default_factory=dict)
	cdp_method_counts: dict[str, int] = field(default_factory=dict)
	imports: dict[str, int] = field(default_factory=dict)
	screenshots: int = 0
	# browsing
	domains: list[str] = field(default_factory=list)
	domain_count: int = 0
	navigations: int = 0
	captcha_started: int = 0
	captcha_solved: int = 0
	captcha_failed: int = 0
	downloads_started: int = 0
	downloads: int = 0
	download_exts: dict[str, int] = field(default_factory=dict)

	name: str = 'agent_event'
