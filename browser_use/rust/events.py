"""
Typed wrapper around the NDJSON event stream emitted by the Rust
`browser-use-terminal events <task_id>` subcommand (and persisted to
`~/.browser-use-terminal/state.db`).

The protocol is intentionally open-ended — the Rust side keeps adding event
types as the agent grows. We model the *common* ones as discriminated
Pydantic classes so consumer code can be type-safe for the events it cares
about. Unknown events deserialize to `RawEvent` instead of throwing, so
adding a new `type` Rust-side is a non-breaking change.

The mapping below tracks `crates/browser-use-protocol/src/lib.rs` —
specifically the `EventRecord.type` discriminator. Update both sides when
adding a new variant.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError


class _BaseEvent(BaseModel):
	"""Common envelope. The Rust side guarantees these fields exist."""

	model_config = ConfigDict(extra='allow', populate_by_name=True)
	seq: int
	id: str
	session_id: str
	ts_ms: int


class SessionCreated(_BaseEvent):
	type: Literal['session.created']
	payload: dict[str, Any] = Field(default_factory=dict)


class SessionInput(_BaseEvent):
	type: Literal['session.input']
	payload: dict[str, Any] = Field(default_factory=dict)

	@property
	def text(self) -> str:
		return str(self.payload.get('text') or self.payload.get('content') or '')


class SessionStatus(_BaseEvent):
	type: Literal['session.status']
	payload: dict[str, Any] = Field(default_factory=dict)

	@property
	def status(self) -> str:
		return str(self.payload.get('status') or '')


class SessionResult(_BaseEvent):
	type: Literal['session.result']
	payload: dict[str, Any] = Field(default_factory=dict)

	@property
	def text(self) -> str:
		# Rust emits either {result: "..."} or {text: "..."} depending on path.
		return str(self.payload.get('result') or self.payload.get('text') or '')


class SessionFailure(_BaseEvent):
	type: Literal['session.failure']
	payload: dict[str, Any] = Field(default_factory=dict)

	@property
	def message(self) -> str:
		return str(self.payload.get('error') or self.payload.get('message') or '')


class SessionStartupWarning(_BaseEvent):
	type: Literal['session.startup_warning']
	payload: dict[str, Any] = Field(default_factory=dict)


class WorkspaceContext(_BaseEvent):
	type: Literal['workspace.context']
	payload: dict[str, Any] = Field(default_factory=dict)


class ModelConfig(_BaseEvent):
	type: Literal['model.config']
	payload: dict[str, Any] = Field(default_factory=dict)

	@property
	def model(self) -> str:
		return str(self.payload.get('model') or '')

	@property
	def provider(self) -> str:
		return str(self.payload.get('provider') or '')


class ModelDelta(_BaseEvent):
	"""Rust `model.delta` — one chunk of streamed assistant text."""

	type: Literal['model.delta']
	payload: dict[str, Any] = Field(default_factory=dict)

	@property
	def delta(self) -> str:
		return str(self.payload.get('delta') or self.payload.get('text') or '')


class ModelStreamDelta(_BaseEvent):
	"""Rust `model.stream_delta` — same as ModelDelta with extra streaming meta."""

	type: Literal['model.stream_delta']
	payload: dict[str, Any] = Field(default_factory=dict)

	@property
	def delta(self) -> str:
		return str(self.payload.get('delta') or self.payload.get('text') or '')


class ModelUsage(_BaseEvent):
	"""Rust `model.usage` — per-turn token + cost accounting."""

	type: Literal['model.usage']
	payload: dict[str, Any] = Field(default_factory=dict)

	@property
	def input_tokens(self) -> int:
		return int(self.payload.get('input_tokens') or self.payload.get('prompt_tokens') or 0)

	@property
	def output_tokens(self) -> int:
		return int(self.payload.get('output_tokens') or self.payload.get('completion_tokens') or 0)

	@property
	def total_tokens(self) -> int:
		return int(self.payload.get('total_tokens') or self.input_tokens + self.output_tokens)

	@property
	def cost_usd(self) -> float:
		return float(self.payload.get('cost') or self.payload.get('cost_usd') or 0.0)


class ModelTurnRequest(_BaseEvent):
	type: Literal['model.turn.request']
	payload: dict[str, Any] = Field(default_factory=dict)


class ModelTurnResponse(_BaseEvent):
	type: Literal['model.turn.response']
	payload: dict[str, Any] = Field(default_factory=dict)


class ModelResponseInputItem(_BaseEvent):
	"""Rust `model.response.input_item` — one message in the LLM input prompt."""

	type: Literal['model.response.input_item']
	payload: dict[str, Any] = Field(default_factory=dict)


class ModelResponseOutputItem(_BaseEvent):
	"""Rust `model.response.output_item` — one message in the LLM output."""

	type: Literal['model.response.output_item']
	payload: dict[str, Any] = Field(default_factory=dict)


class ModelResponseCompleted(_BaseEvent):
	type: Literal['model.response.completed']
	payload: dict[str, Any] = Field(default_factory=dict)


class ModelRateLimits(_BaseEvent):
	type: Literal['model.rate_limits']
	payload: dict[str, Any] = Field(default_factory=dict)


class ModelToolCall(_BaseEvent):
	"""Rust `model.tool_call` — the LLM asked us to call this tool."""

	type: Literal['model.tool_call']
	payload: dict[str, Any] = Field(default_factory=dict)

	@property
	def tool_name(self) -> str:
		return str(self.payload.get('name') or self.payload.get('tool') or '')


class ToolStarted(_BaseEvent):
	type: Literal['tool.started']
	payload: dict[str, Any] = Field(default_factory=dict)

	@property
	def tool_name(self) -> str:
		return str(self.payload.get('name') or self.payload.get('tool') or '')


class ToolFinished(_BaseEvent):
	"""Rust `tool.finished` — tool execution completed (success or failure)."""

	type: Literal['tool.finished']
	payload: dict[str, Any] = Field(default_factory=dict)

	@property
	def tool_name(self) -> str:
		return str(self.payload.get('name') or self.payload.get('tool') or '')


class ToolImage(_BaseEvent):
	"""Rust `tool.image` — a screenshot or other image artifact emitted by a tool call.

	Payload: {name, tool_call_id?, image: {path, label, mime_type, bytes, ...}}.
	The `path` is an absolute file path on disk under the task's artifact directory.
	"""

	type: Literal['tool.image']
	payload: dict[str, Any] = Field(default_factory=dict)

	@property
	def tool_call_id(self) -> str | None:
		value = self.payload.get('tool_call_id')
		return str(value) if value else None

	@property
	def image_path(self) -> str | None:
		image = self.payload.get('image') or {}
		value = image.get('path') if isinstance(image, dict) else None
		return str(value) if value else None

	@property
	def label(self) -> str | None:
		image = self.payload.get('image') or {}
		value = image.get('label') if isinstance(image, dict) else None
		return str(value) if value else None


class ToolOutput(_BaseEvent):
	"""Rust `tool.output` — verbose payload variant emitted by tools like `browser_script`.

	Payload includes the `images` array (each with a `path`), the rendered text,
	and outputs. We surface this alongside `ToolFinished` since the latter only
	includes the trimmed summary.
	"""

	type: Literal['tool.output']
	payload: dict[str, Any] = Field(default_factory=dict)

	@property
	def tool_call_id(self) -> str | None:
		value = self.payload.get('tool_call_id')
		return str(value) if value else None

	@property
	def image_paths(self) -> list[str]:
		images = self.payload.get('images') or []
		out: list[str] = []
		if isinstance(images, list):
			for img in images:
				if isinstance(img, dict):
					path = img.get('path')
					if isinstance(path, str) and path:
						out.append(path)
		return out


class TokenCount(_BaseEvent):
	type: Literal['token_count']
	payload: dict[str, Any] = Field(default_factory=dict)


class TaskStarted(_BaseEvent):
	type: Literal['task_started']
	payload: dict[str, Any] = Field(default_factory=dict)


class SessionConfigSnapshot(_BaseEvent):
	type: Literal['session.config_snapshot']
	payload: dict[str, Any] = Field(default_factory=dict)


class SessionBaseInstructions(_BaseEvent):
	type: Literal['session.base_instructions']
	payload: dict[str, Any] = Field(default_factory=dict)


class SessionCollaborationMode(_BaseEvent):
	type: Literal['session.collaboration_mode']
	payload: dict[str, Any] = Field(default_factory=dict)


class SessionInstructionSources(_BaseEvent):
	type: Literal['session.instruction_sources']
	payload: dict[str, Any] = Field(default_factory=dict)


class ContextBaseline(_BaseEvent):
	type: Literal['context.baseline']
	payload: dict[str, Any] = Field(default_factory=dict)


class BrowserScript(_BaseEvent):
	type: Literal['browser_script.response']
	payload: dict[str, Any] = Field(default_factory=dict)


class BrowserConnected(_BaseEvent):
	"""Rust `browser.connected` — emitted right after a successful CDP attach."""

	type: Literal['browser.connected']
	payload: dict[str, Any] = Field(default_factory=dict)

	@property
	def cdp_url(self) -> str | None:
		return self.payload.get('cdp_url') or self.payload.get('cdp_ws_url')


class BrowserLiveUrl(_BaseEvent):
	"""Rust `browser.live_url` — a watch URL for the agent's session (cloud / remote)."""

	type: Literal['browser.live_url']
	payload: dict[str, Any] = Field(default_factory=dict)

	@property
	def url(self) -> str | None:
		return self.payload.get('url') or self.payload.get('live_url')


class TelemetryTrace(_BaseEvent):
	"""Rust `telemetry.trace` — emitted once per session with the Laminar trace ID.

	Payload: `{backend: "laminar", transport: "otlp_http_proto", trace_id, endpoint}`.
	`trace_id` is the OTel hex trace id; lets the eval pipeline build a
	`https://www.lmnr.ai/project/<project>/traces?traceId=<id>` deep link.
	"""

	type: Literal['telemetry.trace']
	payload: dict[str, Any] = Field(default_factory=dict)

	@property
	def trace_id(self) -> str | None:
		value = self.payload.get('trace_id')
		return str(value) if value else None

	@property
	def backend(self) -> str | None:
		value = self.payload.get('backend')
		return str(value) if value else None


# Legacy aliases — older consumer code can still import these names.
ModelTextDelta = ModelDelta
ToolCall = ModelToolCall
ToolResult = ToolFinished


class RawEvent(_BaseEvent):
	"""Catch-all for unrecognised types. Preserves payload as-is."""

	type: str
	payload: dict[str, Any] = Field(default_factory=dict)


_KNOWN_TYPED = Annotated[
	Union[
		SessionCreated,
		SessionInput,
		SessionStatus,
		SessionResult,
		SessionFailure,
		SessionStartupWarning,
		SessionConfigSnapshot,
		SessionBaseInstructions,
		SessionCollaborationMode,
		SessionInstructionSources,
		WorkspaceContext,
		ContextBaseline,
		ModelConfig,
		ModelDelta,
		ModelStreamDelta,
		ModelUsage,
		ModelTurnRequest,
		ModelTurnResponse,
		ModelResponseInputItem,
		ModelResponseOutputItem,
		ModelResponseCompleted,
		ModelRateLimits,
		ModelToolCall,
		ToolStarted,
		ToolFinished,
		ToolImage,
		ToolOutput,
		TokenCount,
		TaskStarted,
		TelemetryTrace,
		BrowserScript,
		BrowserConnected,
		BrowserLiveUrl,
	],
	Field(discriminator='type'),
]
AnyAgentEvent = Union[_KNOWN_TYPED, RawEvent]

_KNOWN_TYPE_ADAPTER = TypeAdapter(_KNOWN_TYPED)


def parse_event(line: str | bytes | dict[str, Any]) -> AnyAgentEvent | None:
	"""
	Parse a single NDJSON line into a typed event. Returns `None` for blank
	or malformed JSON. Unknown `type` strings fall through to `RawEvent` so
	upstream additions don't break consumers.
	"""
	import json

	if isinstance(line, (str, bytes)):
		text = line.decode() if isinstance(line, bytes) else line
		text = text.strip()
		if not text:
			return None
		try:
			raw: dict[str, Any] = json.loads(text)
		except json.JSONDecodeError:
			return None
	else:
		raw = line

	try:
		return _KNOWN_TYPE_ADAPTER.validate_python(raw)
	except ValidationError:
		# Fall back to the catch-all if discriminated parsing fails (e.g.
		# the Rust side added a brand-new event type with a payload shape
		# our discriminated union doesn't cover).
		try:
			return RawEvent.model_validate(raw)
		except ValidationError:
			return None


__all__ = [
	'AnyAgentEvent',
	'BrowserScript',
	'ModelConfig',
	'ModelTextDelta',
	'ModelThinkingDelta',
	'ModelTurnComplete',
	'RawEvent',
	'SessionCreated',
	'SessionFailure',
	'SessionInput',
	'SessionResult',
	'SessionStartupWarning',
	'SessionStatus',
	'ToolCall',
	'ToolResult',
	'WorkspaceContext',
	'parse_event',
]
