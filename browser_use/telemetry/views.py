from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

SCHEMA_VERSION = 5  # 2: no task, result, code, typed text, URLs or error messages; 3: timings, per-step arrays;
# 4: urls_visited, error_messages, final_result; 5: judge, judge_context, judgement


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
	(model, helper, tool, module, exception class) or a hostname, or a list or map of those; and the URLs visited
	without query strings, error messages, the final result and the judgement's texts (description, failure_reason,
	gotchas), scrubbed of secrets and credentials (stats.scrub). Never the task text, judge_context, typed text, code or
	secrets."""

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
	cdp_url: str | None = None  # cdp mode only, its kind: browser-use-cloud | localhost | private | public-other (cdp_category)
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
	error_type: str | None = None  # exception class; its message is in error_messages
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
	domain_restrictions: bool = False  # Browser(allowed_domains / prohibited_domains / block_ip_addresses) set; never the domains
	domain_blocks: int = 0  # navigations refused or blocked, and tabs reset, by those restrictions
	downloads_started: int = 0
	downloads: int = 0
	download_exts: dict[str, int] = field(default_factory=dict)
	# --- schema 3 ---
	is_internal: bool = False  # BROWSER_USE_TELEMETRY_INTERNAL: our own evals and tests
	# configuration
	web_search: bool = False
	use_vision: bool = True
	highlight_actions: bool = True
	judge: bool = True
	judge_context: bool = False  # set or not, never its text
	max_context_chars_set: bool = False
	captcha_solver: bool | None = None
	headless: bool | None = None
	chrome_profile: bool = False
	user_data_dir: bool = False
	browser_exe: str | None = None  # chrome | chromium | edge | other: from the path's file name, never the path
	allowed_domains_n: int = 0
	prohibited_domains_n: int = 0
	block_ip_addresses: bool = False
	gateway: bool = False
	model_api: str = ''  # responses | chat | anthropic | google | other
	compaction_mode: str = ''  # server | client
	context_window: int | None = None
	sync: bool = False
	run_in_process: int = 0
	concurrent_runs: int = 0
	# where the time went, in ms
	ms_total: int = 0
	ms_preflight: int = 0
	ms_browser_start: int | None = None
	ms_repl_start: int = 0
	ms_model: int = 0
	ms_ttft: int = 0
	ms_cells: int = 0
	ms_helpers: int = 0
	ms_waits: int = 0
	ms_cdp: int = 0
	ms_compaction: int = 0
	ms_retry_sleep: int = 0
	ms_delivery: int = 0
	ms_shutdown: int = 0
	ms_other: int = 0
	# how it ended
	error_phase: str | None = None
	budget_hit: str | None = None
	delivery_turn: bool = False
	delivery_repairs: int = 0
	# model
	model_attempts: int = 0
	length_finishes: int = 0
	invalid_tool_calls: int = 0
	response_models: dict[str, int] = field(default_factory=dict)
	cost_search_usd: float | None = None
	cost_compaction_usd: float | None = None
	retries: dict[str, int] = field(default_factory=dict)
	model_fails: list[list[Any]] = field(default_factory=list)
	compactions: list[list[int]] = field(default_factory=list)
	# browsing
	first_nav_step: int | None = None
	first_nav_ms: int | None = None
	first_ok_action_ms: int | None = None
	revisit_navs: int = 0
	nav_failures: int = 0
	nav_errors: dict[str, int] = field(default_factory=dict)
	helper_stats: dict[str, list[int]] = field(default_factory=dict)
	cdp_stats: dict[str, list[int]] = field(default_factory=dict)
	host_stats: dict[str, list[int]] = field(default_factory=dict)
	# struggle
	max_err_streak: int = 0
	err_streaks_3: int = 0
	streak_err: str | None = None
	streak_kind: str | None = None
	streak_helper: str | None = None
	repeat_fail_steps: int = 0
	repeat_code_steps: int = 0
	max_host_streak: int = 0
	last_progress_step: int = 0
	wasted_steps: int = 0
	# per step (parallel arrays, one entry per model response)
	s_t: list[int] = field(default_factory=list)
	s_model_ms: list[int] = field(default_factory=list)
	s_ttft_ms: list[int] = field(default_factory=list)
	s_in: list[int] = field(default_factory=list)
	s_out: list[int] = field(default_factory=list)
	s_cached: list[int] = field(default_factory=list)
	s_reason: list[int] = field(default_factory=list)
	s_finish: list[str] = field(default_factory=list)
	s_tools: list[str] = field(default_factory=list)
	s_cells: list[int] = field(default_factory=list)
	s_cell_ms: list[int] = field(default_factory=list)
	s_wait_ms: list[int] = field(default_factory=list)
	s_cdp_ms: list[int] = field(default_factory=list)
	s_err: list[str] = field(default_factory=list)
	s_helpers: list[str] = field(default_factory=list)
	s_kind: list[str] = field(default_factory=list)
	s_host: list[str] = field(default_factory=list)
	s_nav: list[int] = field(default_factory=list)
	s_out_chars: list[int] = field(default_factory=list)
	s_imgs: list[int] = field(default_factory=list)
	s_ev: list[int] = field(default_factory=list)
	# telemetry itself
	tel_build_us: int = 0
	tel_bytes: int = 0
	tel_steps_dropped: int = 0
	tel_prev_send_fail: int = 0
	# --- schema 4 --- (scrubbed: stats.scrub)
	urls_visited: list[str] = field(default_factory=list)  # scheme://host/path, in order, once; 50 at most, 200 chars each
	error_messages: list[str] = field(default_factory=list)  # the run's error, then each failed cell's; 20, 300 chars each
	final_result: str | None = None  # the result text (structured output as JSON), 500 chars
	# the judge's answer (stats.judged): success, failure_reason, description, prompt_injection_detected,
	# bot_block_or_captcha_detected, gotchas (at most 5; each text scrubbed, 300 chars), cost_usd; None when not judged
	judgement: dict[str, Any] | None = None
	feedback_count: int = 0  # report_issue() calls sent as library_feedback during the run

	name: str = 'agent_event'


@dataclass
class MCPToolCallEvent(BaseTelemetryEvent):
	"""One per tool call to the browser-use MCP server (--cli-mcp, --mcp), under 0.x's event name and its tool_name and
	duration_seconds fields. Never the code, its output or arguments; the error message is scrubbed (stats.scrub)."""

	version: str
	tool_name: str  # browser_exec, browser_screenshot, browser_login, browser_feedback, a 0.x tool name, or 'invalid'
	duration_seconds: float
	ok: bool  # the result was not an error
	# exception class (as in agent_event's cell_error_types), CancelledError for a cancelled call; invalid_arguments or
	# unknown_tool for an error result without an exception
	error_type: str | None
	server: str  # cli-mcp | mcp
	browser: str  # chrome (the user's) | chromium (--mcp's own) | cloud
	agent_client: str | None  # the coding agent the server runs under (claude-code, codex, cursor, ...), from its env
	call_n: int  # this call's number in the server process
	is_internal: bool
	action: str = 'tool_call'
	error_message: str | None = None  # the exception's message (or the rejected arguments' error), 300 chars

	name: str = 'mcp_server_event'


@dataclass
class FeedbackEvent(BaseTelemetryEvent):
	"""One report of what went wrong with browser-use itself (telemetry/feedback.py), in the words of the agent's model,
	the developer or an MCP client, scrubbed (stats.scrub)."""

	version: str
	source: str  # agent (report_issue) | python (browser_use.feedback) | cli (browser-use feedback) | mcp (browser_feedback)
	message: str  # 2000 chars
	category: str  # bug | docs | missing | other
	is_internal: bool
	model: str | None = None  # agent only, as agent_event sends it
	run_id: str | None = None  # agent only: joins this run's agent_event
	step: int | None = None  # agent only: the model response whose cell reported it
	last_error_type: str | None = None  # agent only: the class of the run's last failed cell

	name: str = 'library_feedback'


if not TYPE_CHECKING:  # pyright would accept any name imported from here
	from browser_use.legacy import removed_names

	__getattr__ = removed_names(__name__)  # a 0.x name raises the removed error naming its 1.0 answer
