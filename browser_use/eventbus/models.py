import asyncio
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import AfterValidator, BaseModel, Field, PrivateAttr
from uuid_extensions import uuid7str

from browser_use.utils import get_browser_use_version

# Constants for validation
MAX_STRING_LENGTH = 10000  # 10K chars for most strings
MAX_URL_LENGTH = 2000
MAX_TASK_LENGTH = 5000
MAX_COMMENT_LENGTH = 2000
MAX_FILE_CONTENT_SIZE = 50 * 1024 * 1024  # 50MB

UUIDStr = Annotated[str, AfterValidator(lambda s: str(UUID(s)))]


class BaseEvent(BaseModel):
	"""
	The base model used for all Events that flow through the EventBus system.
	"""

	event_schema: str | None = Field(default=None, description='Event schema version in format ClassName@version', max_length=100)
	event_type: str
	event_id: str = Field(default_factory=uuid7str)
	event_path: list[str] = Field(default_factory=list, description='Path tracking for event routing')

	# Completion tracking fields
	event_created_at: datetime = Field(
		default_factory=lambda: datetime.now(UTC), description='Timestamp when event was queued/created'
	)
	event_started_at: datetime | None = Field(default=None, description='Timestamp when event was started')
	event_completed_at: datetime | None = Field(default=None, description='Timestamp when event was completed')
	event_results: dict[str, Any] = Field(
		default_factory=dict, exclude=True, description='Handler results {handler_name: result}'
	)
	event_errors: dict[str, str] = Field(
		default_factory=dict, exclude=True, description='Handler errors {handler_name: error_str}'
	)
	_event_completed_signal: asyncio.Event | None = PrivateAttr(default=None)

	@property
	def state(self) -> str:
		return 'completed' if self.event_completed_at else 'started' if self.event_started_at else 'queued'

	async def result(self):
		"""Wait for completion and return self with results"""
		if self._event_completed_signal:
			await self._event_completed_signal.wait()
		return self

	def record_results(self, results: dict[str, Any] | None = None, complete: bool = True) -> None:
		"""Update the event results and optionally mark it as completed"""
		self.event_results = {
			**(self.event_results or {}),
			**(results or {}),
		}
		if complete:
			self.event_completed_at = datetime.now(UTC)
			if self._event_completed_signal:
				self._event_completed_signal.set()

	def model_post_init(self, __context: Any) -> None:
		"""Initialize completion event and set event schema after model creation"""

		if self.event_schema is None:
			version = get_browser_use_version()
			self.event_schema = f'{self.__class__.__module__}.{self.__class__.__qualname__}@{version}'

		try:
			asyncio.get_running_loop()  # Only create event if we're in an async context
			self._event_completed_signal = asyncio.Event()
		except RuntimeError:
			self._event_completed_signal = None  # Not in async context, skip
