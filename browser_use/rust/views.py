"""Public Pydantic models for the rust Agent."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from uuid_extensions import uuid7str

from browser_use.rust.events import AnyAgentEvent


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
	"""One agent turn — tool call + result + the model text that produced it."""

	model_config = ConfigDict(extra='allow')

	seq: int
	tool: str | None = None
	tool_input: dict[str, Any] | None = None
	tool_output: dict[str, Any] | None = None
	model_text: str = ''


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
			from browser_use.rust.compat import build_history_items

			object.__setattr__(self, '_history_items_cache', build_history_items(self))
		return getattr(self, '_history_items_cache')

	@property
	def usage(self) -> Any:
		"""Token / cost summary view (`.model_dump()` returns a dict)."""
		if not hasattr(self, '_usage_cache'):
			from browser_use.rust.compat import build_usage

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
