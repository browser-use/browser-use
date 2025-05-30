import asyncio
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from uuid_extensions import uuid7str


class Event(BaseModel):
	"""Base event model that gets passed through the event bus"""

	model_config = ConfigDict(extra='forbid', validate_assignment=True, arbitrary_types_allowed=True)

	event_id: str = Field(default_factory=uuid7str)
	timestamp: datetime = Field(default_factory=datetime.utcnow)
	data: dict[str, Any] = Field(default_factory=dict)
	path: list[str] = Field(default_factory=list)

	@property
	def event_type(self) -> str:
		"""Derive event type from class name"""
		return self.__class__.__name__

	def model_dump(self, **kwargs) -> dict[str, Any]:
		"""Override to include event_type in serialization"""
		data = super().model_dump(**kwargs)
		data['event_type'] = self.event_type
		return data

	def model_dump_json(self, **kwargs) -> str:
		"""Override to include event_type in JSON serialization"""
		data = self.model_dump(**kwargs)
		import json

		return json.dumps(data, default=str)

	# Completion tracking fields
	started_at: datetime | None = None
	completed_at: datetime | None = None
	results: dict[str, Any] = Field(default_factory=dict)
	errors: dict[str, Exception] = Field(default_factory=dict)

	# Internal field for completion tracking (excluded from serialization)
	completion_event: asyncio.Event | None = Field(default=None, exclude=True)

	def model_post_init(self, __context: Any) -> None:
		"""Initialize completion event after model creation"""
		try:
			# Only create event if we're in an async context
			asyncio.get_running_loop()
			self.completion_event = asyncio.Event()
		except RuntimeError:
			# Not in async context, skip
			self.completion_event = None

	async def wait_for_completion(self) -> None:
		"""Wait for this event to be fully processed"""
		if self.completion_event:
			await self.completion_event.wait()

	def mark_completed(self) -> None:
		"""Mark this event as completed"""
		self.completed_at = datetime.utcnow()
		if self.completion_event:
			self.completion_event.set()
