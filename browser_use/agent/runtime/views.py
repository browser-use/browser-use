from __future__ import annotations

import logging
import mimetypes
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator
from uuid_extensions import uuid7str

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
	from browser_use.agent.runtime.compaction import BrowserContextCompactor, ContextCompactionResult
	from browser_use.agent.runtime.context import BrowserContext


RuntimeEventSubscriber = Callable[['BrowserRuntimeEvent'], None]


class BrowserRuntimeEventTypes:
	TURN_STARTED = 'turn.started'
	CONTEXT_BUILT = 'context.built'
	MODEL_DELTA = 'model.delta'
	TOOL_STARTED = 'tool.started'
	TOOL_COMPLETED = 'tool.completed'
	TOOL_FAILED = 'tool.failed'
	BROWSER_STATE_REFRESHED = 'browser.state_refreshed'
	DOWNLOAD_STARTED = 'download.started'
	DOWNLOAD_COMPLETED = 'download.completed'
	ARTIFACT_CREATED = 'artifact.created'
	CONTEXT_COMPACTED = 'context.compacted'
	TURN_COMPLETED = 'turn.completed'
	TURN_FAILED = 'turn.failed'
	RUN_COMPLETED = 'run.completed'
	RUN_FAILED = 'run.failed'

	ALL = (
		TURN_STARTED,
		CONTEXT_BUILT,
		MODEL_DELTA,
		TOOL_STARTED,
		TOOL_COMPLETED,
		TOOL_FAILED,
		BROWSER_STATE_REFRESHED,
		DOWNLOAD_STARTED,
		DOWNLOAD_COMPLETED,
		ARTIFACT_CREATED,
		CONTEXT_COMPACTED,
		TURN_COMPLETED,
		TURN_FAILED,
		RUN_COMPLETED,
		RUN_FAILED,
	)


def _utc_now() -> datetime:
	return datetime.now(UTC)


def _optional_bool_from_attr(obj: Any, names: tuple[str, ...]) -> bool:
	for name in names:
		value = getattr(obj, name, None)
		if callable(value):
			try:
				value = value()
			except TypeError:
				continue
		if value is not None:
			return bool(value)
	return False


def _optional_str_from_attr(obj: Any, names: tuple[str, ...]) -> str | None:
	for name in names:
		value = getattr(obj, name, None)
		if callable(value):
			try:
				value = value()
			except TypeError:
				continue
		if isinstance(value, str) and value:
			return value
	return None


def _is_anthropic_model(provider_lower: str, model_lower: str) -> bool:
	return provider_lower == 'anthropic' or model_lower.startswith('anthropic/') or 'claude' in model_lower


def _is_anthropic_4_5_model(model_lower: str) -> bool:
	is_opus_4_5 = 'opus' in model_lower and ('4.5' in model_lower or '4-5' in model_lower)
	is_haiku_4_5 = 'haiku' in model_lower and ('4.5' in model_lower or '4-5' in model_lower)
	return is_opus_4_5 or is_haiku_4_5


def _supports_coordinate_clicking(model_lower: str) -> bool:
	return any(pattern in model_lower for pattern in ['claude-sonnet-4', 'claude-opus-4', 'gemini-3-pro', 'browser-use/'])


def _default_timeout_s(provider_lower: str, model_lower: str) -> int:
	if 'gemini' in model_lower:
		if '3-pro' in model_lower:
			return 90
		return 75
	if 'groq' in provider_lower or 'groq' in model_lower:
		return 30
	if any(pattern in model_lower for pattern in ['o3', 'claude', 'sonnet', 'deepseek']):
		return 90
	return 75


def _recommended_screenshot_size(model_lower: str) -> tuple[int, int] | None:
	if model_lower.startswith('claude-sonnet'):
		return (1400, 850)
	return None


def _unsupported_vision_reason(model_lower: str) -> str | None:
	if 'deepseek' in model_lower:
		return 'DeepSeek models do not support use_vision=True yet.'
	if 'grok-3' in model_lower or 'grok-code' in model_lower:
		return 'This XAI model does not support use_vision=True yet.'
	return None


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
	prefers_flash_mode: bool = False
	uses_browser_use_prompt: bool = False
	is_anthropic: bool = False
	is_anthropic_4_5: bool = False
	supports_coordinate_clicking: bool = False
	default_timeout_s: int = 75
	recommended_screenshot_size: tuple[int, int] | None = None
	unsupported_vision_reason: str | None = None

	@classmethod
	def from_llm(cls, llm: Any | None) -> ModelCapabilities:
		if llm is None:
			return cls()
		provider = _optional_str_from_attr(llm, ('provider',))
		model_name = _optional_str_from_attr(llm, ('model', 'model_name', 'name'))
		provider_lower = (provider or '').lower()
		model_lower = (model_name or '').lower()

		return cls(
			provider=provider,
			model_name=model_name,
			native_tool_calling=_optional_bool_from_attr(llm, ('supports_native_tool_calling', 'supports_tool_calling')),
			structured_output=_optional_bool_from_attr(llm, ('supports_structured_output', 'supports_output_schema')),
			vision=_optional_bool_from_attr(llm, ('supports_vision', 'vision')),
			streaming=_optional_bool_from_attr(llm, ('supports_streaming', 'streaming')),
			reasoning=_optional_bool_from_attr(llm, ('supports_reasoning', 'reasoning')),
			parallel_tool_calls=_optional_bool_from_attr(llm, ('supports_parallel_tool_calls', 'parallel_tool_calls')),
			prefers_flash_mode=provider_lower == 'browser-use',
			uses_browser_use_prompt=model_lower.startswith('browser-use/'),
			is_anthropic=_is_anthropic_model(provider_lower, model_lower),
			is_anthropic_4_5=_is_anthropic_4_5_model(model_lower),
			supports_coordinate_clicking=_supports_coordinate_clicking(model_lower),
			default_timeout_s=_default_timeout_s(provider_lower, model_lower),
			recommended_screenshot_size=_recommended_screenshot_size(model_lower),
			unsupported_vision_reason=_unsupported_vision_reason(model_lower),
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
	subscriber_errors: list[str] = Field(default_factory=list)
	_next_sequence: int = PrivateAttr(default=1)
	_subscribers: list[RuntimeEventSubscriber] = PrivateAttr(default_factory=list)

	def subscribe(self, subscriber: RuntimeEventSubscriber, *, replay: bool = False) -> Callable[[], None]:
		self._subscribers.append(subscriber)
		if replay:
			for event in self.events:
				self._notify_subscriber(subscriber, event)

		def unsubscribe() -> None:
			if subscriber in self._subscribers:
				self._subscribers.remove(subscriber)

		return unsubscribe

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
		for subscriber in list(self._subscribers):
			self._notify_subscriber(subscriber, event)
		return event

	def snapshot(self, *, after_sequence: int = 0) -> list[BrowserRuntimeEvent]:
		return [event for event in self.events if event.sequence > after_sequence]

	def clear(self) -> None:
		self.events.clear()
		self.subscriber_errors.clear()
		self._next_sequence = 1

	def _notify_subscriber(self, subscriber: RuntimeEventSubscriber, event: BrowserRuntimeEvent) -> None:
		try:
			subscriber(event)
		except Exception as exc:
			message = f'{subscriber!r} failed for {event.event_type}: {exc}'
			self.subscriber_errors.append(message)
			logger.debug(message)


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
			event_type=BrowserRuntimeEventTypes.TURN_STARTED,
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

	def emit_context_built(
		self,
		turn: BrowserTurnContext,
		*,
		item_count: int,
		rendered_chars: int,
		metadata: dict[str, Any] | None = None,
	) -> BrowserRuntimeEvent:
		return self.event_stream.emit(
			run_id=self.run_id,
			turn_id=turn.turn_id,
			event_type=BrowserRuntimeEventTypes.CONTEXT_BUILT,
			payload={
				'step_index': turn.step_index,
				'item_count': item_count,
				'rendered_chars': rendered_chars,
				**(metadata or {}),
			},
		)

	def emit_model_delta(
		self,
		turn: BrowserTurnContext,
		*,
		text: str | None = None,
		tool_call_count: int | None = None,
		is_final: bool = False,
		metadata: dict[str, Any] | None = None,
	) -> BrowserRuntimeEvent:
		payload: dict[str, Any] = {'step_index': turn.step_index, 'is_final': is_final, **(metadata or {})}
		if text is not None:
			payload['text'] = text
			payload['text_chars'] = len(text)
		if tool_call_count is not None:
			payload['tool_call_count'] = tool_call_count
		return self.event_stream.emit(
			run_id=self.run_id,
			turn_id=turn.turn_id,
			event_type=BrowserRuntimeEventTypes.MODEL_DELTA,
			payload=payload,
		)

	def compact_context(
		self,
		context: BrowserContext,
		*,
		compactor: BrowserContextCompactor | None = None,
		turn: BrowserTurnContext | None = None,
	) -> ContextCompactionResult:
		"""Compact typed model context and emit an observable runtime event."""

		if compactor is None:
			from browser_use.agent.runtime.compaction import BrowserContextCompactor

			compactor = BrowserContextCompactor()

		result = compactor.compact(context)
		if result.compacted:
			self.event_stream.emit(
				run_id=self.run_id,
				turn_id=turn.turn_id if turn is not None else None,
				event_type=BrowserRuntimeEventTypes.CONTEXT_COMPACTED,
				payload=result.event_payload(),
			)
		return result

	def emit_download_started(
		self,
		*,
		file_name: str | None = None,
		url: str | None = None,
		turn: BrowserTurnContext | None = None,
		metadata: dict[str, Any] | None = None,
	) -> BrowserRuntimeEvent:
		return self.event_stream.emit(
			run_id=self.run_id,
			turn_id=turn.turn_id if turn is not None else None,
			event_type=BrowserRuntimeEventTypes.DOWNLOAD_STARTED,
			payload={'file_name': file_name, 'url': url, **(metadata or {})},
		)

	def record_download_completed(
		self,
		*,
		file_name: str,
		path: str | Path | None = None,
		url: str | None = None,
		media_type: str | None = None,
		turn: BrowserTurnContext | None = None,
		metadata: dict[str, Any] | None = None,
	) -> ArtifactRef:
		resolved_media_type = media_type or mimetypes.guess_type(file_name)[0]
		artifact = self.artifact_store.add(
			kind='download',
			name=file_name,
			path=path,
			media_type=resolved_media_type,
			metadata={'url': url, **(metadata or {})},
		)
		payload = {
			'artifact_id': artifact.artifact_id,
			'file_name': file_name,
			'path': str(path) if path is not None else None,
			'url': url,
			'media_type': resolved_media_type,
			**(metadata or {}),
		}
		self.event_stream.emit(
			run_id=self.run_id,
			turn_id=turn.turn_id if turn is not None else None,
			event_type=BrowserRuntimeEventTypes.DOWNLOAD_COMPLETED,
			payload=payload,
		)
		self.event_stream.emit(
			run_id=self.run_id,
			turn_id=turn.turn_id if turn is not None else None,
			event_type=BrowserRuntimeEventTypes.ARTIFACT_CREATED,
			payload={'artifact_id': artifact.artifact_id, 'kind': artifact.kind, 'path': str(path) if path else None},
		)
		return artifact

	def complete_run(self, *, metadata: dict[str, Any] | None = None) -> BrowserRuntimeEvent:
		return self.event_stream.emit(
			run_id=self.run_id,
			event_type=BrowserRuntimeEventTypes.RUN_COMPLETED,
			payload=metadata or {},
		)

	def fail_run(self, error: str, *, metadata: dict[str, Any] | None = None) -> BrowserRuntimeEvent:
		return self.event_stream.emit(
			run_id=self.run_id,
			event_type=BrowserRuntimeEventTypes.RUN_FAILED,
			payload={'error': error, **(metadata or {})},
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
