from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator
from uuid_extensions import uuid7str


def _utc_now() -> datetime:
	return datetime.now(UTC)


def _optional_bool_from_attr(obj: Any, names: tuple[str, ...]) -> bool:
	for name in names:
		value = getattr(obj, name, None)
		if callable(value):
			continue
		if value is not None:
			return bool(value)
	return False


class ModelCapabilities(BaseModel):
	"""Capabilities the runtime can assume for a model.

	Model names are copied as-is. Browser Use users often pass freshly released
	model IDs before the library knows about them, so this class must never
	normalize or replace unknown model names.
	"""

	model_config = ConfigDict(frozen=True)

	provider: str | None = None
	model_name: str | None = None
	native_tool_calling: bool = False
	structured_output: bool = False
	vision: bool = False
	streaming: bool = False
	reasoning: bool = False
	parallel_tool_calls: bool = False

	@classmethod
	def from_llm(cls, llm: Any | None) -> ModelCapabilities:
		if llm is None:
			return cls()

		return cls(
			provider=getattr(llm, 'provider', None),
			model_name=getattr(llm, 'model', None) or getattr(llm, 'model_name', None),
			native_tool_calling=_optional_bool_from_attr(llm, ('supports_native_tool_calling', 'supports_tool_calling')),
			structured_output=_optional_bool_from_attr(llm, ('supports_structured_output', 'supports_output_schema')),
			vision=_optional_bool_from_attr(llm, ('supports_vision', 'vision')),
			streaming=_optional_bool_from_attr(llm, ('supports_streaming', 'streaming')),
			reasoning=_optional_bool_from_attr(llm, ('supports_reasoning', 'reasoning')),
			parallel_tool_calls=_optional_bool_from_attr(llm, ('supports_parallel_tool_calls', 'parallel_tool_calls')),
		)


class BrowserRunConfig(BaseModel):
	"""Runtime-level configuration for a browser agent run."""

	model_config = ConfigDict(validate_assignment=True, extra='forbid')

	run_id: str = Field(default_factory=uuid7str)
	max_steps: int = Field(default=100, ge=1)
	max_actions_per_step: int = Field(default=3, ge=1)
	runtime_mode: Literal['legacy', 'codex'] = 'legacy'
	use_native_tool_calls: bool = False
	stream_events: bool = True
	metadata: dict[str, Any] = Field(default_factory=dict)


class BrowserRuntimeEvent(BaseModel):
	"""A single observable runtime event.

	Events are for observability and replay. They are not the control mechanism
	for browser actions.
	"""

	model_config = ConfigDict(frozen=True)

	event_id: str = Field(default_factory=uuid7str)
	run_id: str
	turn_id: str | None = None
	sequence: int = Field(ge=1)
	event_type: str = Field(min_length=1)
	timestamp: datetime = Field(default_factory=_utc_now)
	payload: dict[str, Any] = Field(default_factory=dict)


class BrowserEventStream(BaseModel):
	"""In-memory event stream used by the new runtime skeleton."""

	model_config = ConfigDict(validate_assignment=True)

	events: list[BrowserRuntimeEvent] = Field(default_factory=list)
	_next_sequence: int = PrivateAttr(default=1)

	def emit(
		self,
		*,
		run_id: str,
		event_type: str,
		turn_id: str | None = None,
		payload: dict[str, Any] | None = None,
	) -> BrowserRuntimeEvent:
		event = BrowserRuntimeEvent(
			run_id=run_id,
			turn_id=turn_id,
			sequence=self._next_sequence,
			event_type=event_type,
			payload=payload or {},
		)
		self._next_sequence += 1
		self.events.append(event)
		return event

	def clear(self) -> None:
		self.events.clear()
		self._next_sequence = 1


class ArtifactRef(BaseModel):
	"""Reference to an artifact created during a run."""

	model_config = ConfigDict(frozen=True)

	artifact_id: str = Field(default_factory=uuid7str)
	kind: str = Field(min_length=1)
	name: str | None = None
	path: Path | None = None
	uri: str | None = None
	media_type: str | None = None
	metadata: dict[str, Any] = Field(default_factory=dict)
	created_at: datetime = Field(default_factory=_utc_now)


class ArtifactStore(BaseModel):
	"""Small typed artifact registry for screenshots, downloads, files, and traces."""

	model_config = ConfigDict(validate_assignment=True)

	artifacts: list[ArtifactRef] = Field(default_factory=list)

	def add(
		self,
		*,
		kind: str,
		name: str | None = None,
		path: str | Path | None = None,
		uri: str | None = None,
		media_type: str | None = None,
		metadata: dict[str, Any] | None = None,
	) -> ArtifactRef:
		artifact = ArtifactRef(
			kind=kind,
			name=name,
			path=Path(path) if path is not None else None,
			uri=uri,
			media_type=media_type,
			metadata=metadata or {},
		)
		self.artifacts.append(artifact)
		return artifact

	def get(self, artifact_id: str) -> ArtifactRef | None:
		return next((artifact for artifact in self.artifacts if artifact.artifact_id == artifact_id), None)


class BrowserTurnContext(BaseModel):
	"""Typed state for a single model turn."""

	model_config = ConfigDict(validate_assignment=True, arbitrary_types_allowed=True)

	run_id: str
	turn_id: str = Field(default_factory=uuid7str)
	step_index: int = Field(ge=0)
	task: str
	model_capabilities: ModelCapabilities = Field(default_factory=ModelCapabilities)
	browser_state: Any | None = None
	status: Literal['running', 'completed', 'failed', 'cancelled'] = 'running'
	metadata: dict[str, Any] = Field(default_factory=dict)


class ToolContext(BaseModel):
	"""Explicit execution context passed to tools in the new runtime."""

	model_config = ConfigDict(arbitrary_types_allowed=True)

	run_id: str
	turn_id: str
	browser_session: Any | None = None
	tools: Any | None = None
	llm: Any | None = None
	page_extraction_llm: Any | None = None
	file_system: Any | None = None
	sensitive_data: dict[str, str | dict[str, str]] | None = None
	available_file_paths: list[str] | None = None
	extraction_schema: dict[str, Any] | None = None
	action_timeout: float | None = None
	artifact_store: ArtifactStore = Field(default_factory=ArtifactStore)
	event_stream: BrowserEventStream = Field(default_factory=BrowserEventStream)
	metadata: dict[str, Any] = Field(default_factory=dict)

	def emit_tool_event(self, event_type: str, payload: dict[str, Any] | None = None) -> BrowserRuntimeEvent:
		return self.event_stream.emit(
			run_id=self.run_id,
			turn_id=self.turn_id,
			event_type=event_type,
			payload=payload,
		)


class BrowserAgentSession(BaseModel):
	"""Runtime representation of one browser-agent run."""

	model_config = ConfigDict(validate_assignment=True, arbitrary_types_allowed=True)

	run_id: str
	task: str
	config: BrowserRunConfig = Field(default_factory=BrowserRunConfig)
	model_capabilities: ModelCapabilities = Field(default_factory=ModelCapabilities)
	artifact_store: ArtifactStore = Field(default_factory=ArtifactStore)
	event_stream: BrowserEventStream = Field(default_factory=BrowserEventStream)
	turns: list[BrowserTurnContext] = Field(default_factory=list)
	metadata: dict[str, Any] = Field(default_factory=dict)

	@field_validator('task')
	@classmethod
	def _task_must_not_be_empty(cls, task: str) -> str:
		if not task.strip():
			raise ValueError('task must not be empty')
		return task

	@classmethod
	def create(
		cls,
		*,
		task: str,
		llm: Any | None = None,
		config: BrowserRunConfig | None = None,
		metadata: dict[str, Any] | None = None,
	) -> BrowserAgentSession:
		run_config = config or BrowserRunConfig()
		return cls(
			run_id=run_config.run_id,
			task=task,
			config=run_config,
			model_capabilities=ModelCapabilities.from_llm(llm),
			metadata=metadata or {},
		)

	def start_turn(
		self,
		*,
		step_index: int,
		browser_state: Any | None = None,
		metadata: dict[str, Any] | None = None,
	) -> BrowserTurnContext:
		turn = BrowserTurnContext(
			run_id=self.run_id,
			step_index=step_index,
			task=self.task,
			model_capabilities=self.model_capabilities,
			browser_state=browser_state,
			metadata=metadata or {},
		)
		self.turns.append(turn)
		self.event_stream.emit(
			run_id=self.run_id,
			turn_id=turn.turn_id,
			event_type='turn.started',
			payload={'step_index': step_index},
		)
		return turn

	def finish_turn(
		self,
		turn: BrowserTurnContext,
		*,
		status: Literal['completed', 'failed', 'cancelled'] = 'completed',
		metadata: dict[str, Any] | None = None,
	) -> BrowserRuntimeEvent:
		turn.status = status
		if metadata:
			turn.metadata.update(metadata)
		return self.event_stream.emit(
			run_id=self.run_id,
			turn_id=turn.turn_id,
			event_type=f'turn.{status}',
			payload={'step_index': turn.step_index, **(metadata or {})},
		)

	def tool_context(
		self,
		turn: BrowserTurnContext,
		*,
		browser_session: Any | None = None,
		tools: Any | None = None,
		llm: Any | None = None,
		page_extraction_llm: Any | None = None,
		file_system: Any | None = None,
		sensitive_data: dict[str, str | dict[str, str]] | None = None,
		available_file_paths: list[str] | None = None,
		extraction_schema: dict[str, Any] | None = None,
		action_timeout: float | None = None,
		metadata: dict[str, Any] | None = None,
	) -> ToolContext:
		return ToolContext(
			run_id=self.run_id,
			turn_id=turn.turn_id,
			browser_session=browser_session,
			tools=tools,
			llm=llm,
			page_extraction_llm=page_extraction_llm,
			file_system=file_system,
			sensitive_data=sensitive_data,
			available_file_paths=available_file_paths,
			extraction_schema=extraction_schema,
			action_timeout=action_timeout,
			artifact_store=self.artifact_store,
			event_stream=self.event_stream,
			metadata=metadata or {},
		)
