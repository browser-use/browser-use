"""
Public Pydantic models + AgentHistoryList-compat views for the rust Agent.

NOTE: this module used to be split between `views.py` (pydantic) and
`compat.py` (legacy AgentHistoryList view classes). They're merged here
because uv/pip kept serving a wheel that silently dropped compat.py in
CI — easier to fix the layering than chase a build cache bug.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from uuid_extensions import uuid7str

from browser_use.rust.events import AnyAgentEvent, ModelConfig


class Provider(str, Enum):
	"""
	Internal-only: which `browser-use-terminal run-<provider>` subcommand the
	wrapper picks. Inferred from the `llm` class name; NOT exposed as a
	constructor argument.
	"""

	OPENAI = 'openai'
	ANTHROPIC = 'anthropic'
	OPENROUTER = 'openrouter'
	DEEPSEEK = 'deepseek'
	CODEX = 'codex'

	@property
	def subcommand(self) -> str:
		return f'run-{self.value}'

	@property
	def api_key_env(self) -> str:
		"""Conventional environment variable name for this provider's key."""
		return {
			Provider.OPENAI: 'OPENAI_API_KEY',
			Provider.ANTHROPIC: 'ANTHROPIC_API_KEY',
			Provider.OPENROUTER: 'OPENROUTER_API_KEY',
			Provider.DEEPSEEK: 'DEEPSEEK_API_KEY',
			Provider.CODEX: 'CODEX_AUTH',
		}[self]


class StepRecord(BaseModel):
	"""One agent turn — tool call + result + the model text that produced it.

	`screenshot_paths` holds absolute disk paths to screenshot/image artifacts
	emitted by `tool.image` events for this tool call (in arrival order).
	"""

	model_config = ConfigDict(extra='allow')

	seq: int
	tool: str | None = None
	tool_input: dict[str, Any] | None = None
	tool_output: dict[str, Any] | None = None
	model_text: str = ''
	screenshot_paths: list[str] = Field(default_factory=list)


class AgentRunResult(BaseModel):
	"""
	Final outcome of an `Agent.run()`.

	The shape intentionally overlaps with `browser_use.agent.views.AgentHistoryList`
	so existing eval harnesses can call the same methods on either object —
	`result.final_result()`, `result.is_done()`, `result.is_successful()`,
	`result.errors()`, `result.action_results()`, `len(result)` — without
	special-casing the Rust path. Methods that require live browser state
	(`screenshots()`, `urls()`, `model_actions()`) are intentionally absent;
	the data isn't propagated from the Rust core today and faking it would
	be worse than letting the harness `getattr`-guard.
	"""

	model_config = ConfigDict(extra='forbid', validate_by_name=True, validate_by_alias=True, arbitrary_types_allowed=True)

	id: str = Field(default_factory=uuid7str)
	session_id: str | None = None
	exit_code: int
	final_summary: str | None = None
	final_output: Any | None = None
	failure: str | None = None
	steps: list[StepRecord] = Field(default_factory=list)
	events: list[AnyAgentEvent] = Field(default_factory=list)
	stderr: str = ''
	started_at: datetime = Field(default_factory=datetime.utcnow)
	ended_at: datetime | None = None
	duration_seconds: float | None = None

	@property
	def succeeded(self) -> bool:
		return self.exit_code == 0 and self.failure is None

	@property
	def status(self) -> Literal['success', 'failed', 'cancelled', 'timeout']:
		if self.exit_code == 124:
			return 'timeout'
		if self.exit_code < 0:
			return 'cancelled'
		if self.failure or self.exit_code != 0:
			return 'failed'
		return 'success'

	# ------------------------------------------------------------------
	# AgentHistoryList-compatible surface (for eval harness drop-in)
	# ------------------------------------------------------------------

	def __len__(self) -> int:
		return len(self.steps)

	def final_result(self) -> str | None:
		"""Top-1 hit in the classic API. Returns the agent's last message."""
		return self.final_summary

	def is_done(self) -> bool:
		"""True once the agent emitted a session.result or exited cleanly."""
		return self.exit_code == 0 and (self.final_summary is not None or self.failure is None)

	def is_successful(self) -> bool | None:
		"""None when not done; otherwise True/False."""
		if not self.is_done():
			return None
		return self.failure is None and self.exit_code == 0

	def errors(self) -> list[str | None]:
		"""One entry per step. Currently only the terminal failure is populated."""
		out: list[str | None] = [None for _ in self.steps]
		if self.failure:
			out.append(self.failure)
		return out

	def has_errors(self) -> bool:
		return any(err for err in self.errors())

	def action_results(self) -> list[dict[str, Any]]:
		"""
		Per-step tool result payloads, flattened — the closest analogue to
		classic `AgentHistoryList.action_results()`. Returns raw dicts since
		we don't reconstruct the classic `ActionResult` pydantic model.
		"""
		return [step.tool_output for step in self.steps if step.tool_output is not None]

	def model_outputs(self) -> list[str]:
		"""The model_text that preceded each tool call. Stripped of empties."""
		return [step.model_text for step in self.steps if step.model_text]

	def action_names(self) -> list[str | None]:
		return [step.tool for step in self.steps]

	def total_duration_seconds(self) -> float:
		return self.duration_seconds or 0.0

	def save_to_file(self, filepath: str, sensitive_data: dict[str, str] | None = None) -> None:
		"""Same signature as classic `AgentHistoryList.save_to_file`. Filters string values."""
		import json
		from pathlib import Path

		blob = self.model_dump(mode='json')
		if sensitive_data:
			text = json.dumps(blob)
			for key, value in sensitive_data.items():
				if value:
					text = text.replace(value, f'<{key}>')
			blob = json.loads(text)
		Path(filepath).write_text(json.dumps(blob, indent=2))

	# ------------------------------------------------------------------
	# AgentHistory-like per-step view for eval harnesses
	# ------------------------------------------------------------------

	@property
	def history(self) -> list[Any]:
		"""
		Eval harnesses iterate `agent.history.history[i].state.url` etc.
		Build the per-step views lazily — first access caches them.
		"""
		if not hasattr(self, '_history_items_cache'):
			object.__setattr__(self, '_history_items_cache', build_history_items(self))
		return getattr(self, '_history_items_cache')

	@property
	def usage(self) -> Any:
		"""Token / cost summary view (`.model_dump()` returns a dict)."""
		if not hasattr(self, '_usage_cache'):
			object.__setattr__(self, '_usage_cache', build_usage(self))
		return getattr(self, '_usage_cache')

	def is_judged(self) -> bool:
		"""Always False — the Rust core doesn't run an inline judge today."""
		return False

	def judgement(self) -> dict[str, Any] | None:
		return None

	def is_validated(self) -> bool | None:
		return None

	@property
	def live_url(self) -> str | None:
		"""URL the user can open to watch the agent live (cloud / remote backends)."""
		from browser_use.rust.events import BrowserLiveUrl

		for event in reversed(self.events):
			if isinstance(event, BrowserLiveUrl):
				return event.url
		return None

	@property
	def cdp_url(self) -> str | None:
		"""CDP URL of the browser the agent attached to (when emitted by the Rust core)."""
		from browser_use.rust.events import BrowserConnected

		for event in reversed(self.events):
			if isinstance(event, BrowserConnected):
				return event.cdp_url
		return None


# ----------------------------------------------------------------------
# AgentHistoryList compatibility views (formerly compat.py)
# ----------------------------------------------------------------------


class _ActionResultView:
	"""Shape: ActionResult — what the legacy harness reads off result[i]."""

	__slots__ = ('_data', 'extracted_content', 'error', 'is_done', 'success', 'long_term_memory')

	def __init__(self, data: dict[str, Any], *, is_done: bool = False) -> None:
		self._data = data
		self.extracted_content = (
			data.get('extracted_content') or data.get('text') or data.get('content') or data.get('result')
		)
		self.error = data.get('error') or data.get('failure')
		self.is_done = bool(data.get('is_done', is_done))
		self.success = data.get('success')
		self.long_term_memory = data.get('long_term_memory')

	def model_dump(self) -> dict[str, Any]:
		return {
			'extracted_content': self.extracted_content,
			'error': self.error,
			'is_done': self.is_done,
			'success': self.success,
			'long_term_memory': self.long_term_memory,
		}


class _StateView:
	"""Shape: BrowserStateHistory."""

	__slots__ = ('url', 'title', '_screenshot_b64')

	def __init__(self, url: str | None = None, title: str | None = None) -> None:
		self.url = url
		self.title = title
		self._screenshot_b64: str | None = None

	def get_screenshot(self) -> str | None:
		return self._screenshot_b64

	def model_dump(self) -> dict[str, Any]:
		return {'url': self.url, 'title': self.title}


class _ModelOutputView:
	"""Shape: AgentOutput — `.action` list of dicts + `.current_state`."""

	__slots__ = ('action', 'current_state', '_data')

	def __init__(self, tool: str | None, tool_input: dict[str, Any] | None, model_text: str) -> None:
		self._data = {
			'action': [{tool: tool_input}] if tool else [],
			'current_state': {'thought': model_text} if model_text else {},
		}
		self.action = self._data['action']
		self.current_state = self._data['current_state']

	def model_dump(self) -> dict[str, Any]:
		return self._data


class _MetadataView:
	"""Shape: StepMetadata."""

	__slots__ = ('input_tokens', 'duration_seconds', 'step_start_time', 'step_end_time')

	def __init__(self) -> None:
		self.input_tokens = 0
		self.duration_seconds = 0.0
		self.step_start_time = 0.0
		self.step_end_time = 0.0

	def model_dump(self) -> dict[str, Any]:
		return {
			'input_tokens': self.input_tokens,
			'duration_seconds': self.duration_seconds,
			'step_start_time': self.step_start_time,
			'step_end_time': self.step_end_time,
		}


class _HistoryItemView:
	"""Shape: AgentHistory."""

	__slots__ = ('state', 'result', 'model_output', 'metadata')

	def __init__(self, step, is_last: bool, final_summary: str | None) -> None:
		self.state = _StateView()
		# Read the last screenshot the tool produced (post-action state) and
		# expose it as base64 so the eval judge can render it. The Rust core
		# emits absolute on-disk paths via `tool.image` events; we read them
		# lazily here so we don't keep PNG bytes in memory for the whole run.
		paths = getattr(step, 'screenshot_paths', None) or []
		if paths:
			self.state._screenshot_b64 = _read_screenshot_b64(paths[-1])
		raw_results = step.tool_output or {}
		results = [_ActionResultView(raw_results, is_done=is_last)]
		if is_last and final_summary and not results[0].extracted_content:
			results[0].extracted_content = final_summary
			results[0].is_done = True
		self.result = results
		self.model_output = _ModelOutputView(step.tool, step.tool_input, step.model_text)
		self.metadata = _MetadataView()

	def model_dump(self) -> dict[str, Any]:
		return {
			'state': self.state.model_dump(),
			'result': [r.model_dump() for r in self.result],
			'model_output': self.model_output.model_dump(),
			'metadata': self.metadata.model_dump(),
		}


class _UsageView:
	"""Shape: tokens/cost view exposed via `.usage`."""

	__slots__ = ('input_tokens', 'output_tokens', 'cost', 'model')

	def __init__(self) -> None:
		self.input_tokens = 0
		self.output_tokens = 0
		self.cost = 0.0
		self.model: str | None = None

	def model_dump(self) -> dict[str, Any]:
		return {
			'input_tokens': self.input_tokens,
			'output_tokens': self.output_tokens,
			'cost': self.cost,
			'model': self.model,
		}


class _MessageManagerStub:
	"""Compat for `agent.message_manager.last_input_messages` reads."""

	def __init__(self) -> None:
		self.last_input_messages: list[Any] = []


def build_history_items(result) -> list[_HistoryItemView]:
	"""Turn AgentRunResult.steps + final_summary into AgentHistory views."""
	items: list[_HistoryItemView] = []
	steps = result.steps
	if not steps and result.final_summary:
		synthetic = type(
			'SyntheticStep',
			(),
			{
				'seq': 0,
				'tool': 'done',
				'tool_input': None,
				'tool_output': {'extracted_content': result.final_summary, 'is_done': True, 'success': True},
				'model_text': '',
			},
		)()
		items.append(_HistoryItemView(synthetic, is_last=True, final_summary=result.final_summary))
		return items
	for idx, step in enumerate(steps):
		items.append(
			_HistoryItemView(
				step,
				is_last=idx == len(steps) - 1,
				final_summary=result.final_summary,
			)
		)
	return items


def build_usage(result) -> _UsageView:
	usage = _UsageView()
	for event in result.events:
		if isinstance(event, ModelConfig):
			usage.model = event.model or usage.model
	return usage


def _read_screenshot_b64(path: str) -> str | None:
	"""Read a PNG/JPEG file from disk and return its base64 representation.

	Returns None when the file is missing or unreadable — screenshots are a
	best-effort signal for the judge; we never raise.
	"""
	import base64
	from pathlib import Path

	try:
		data = Path(path).read_bytes()
	except (OSError, FileNotFoundError):
		return None
	if not data:
		return None
	return base64.b64encode(data).decode('ascii')
