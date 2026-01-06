"""Type-safe event models for sandbox execution SSE streaming"""

import json
from enum import Enum
from typing import Any

from pydantic import BaseModel


class SandboxError(Exception):
	pass


class SSEEventType(str, Enum):
	"""Event types for Server-Sent Events"""

	BROWSER_CREATED = 'browser_created'
	INSTANCE_CREATED = 'instance_created'
	INSTANCE_READY = 'instance_ready'
	LOG = 'log'
	RESULT = 'result'
	ERROR = 'error'
	STREAM_COMPLETE = 'stream_complete'


class BrowserCreatedData(BaseModel):
	"""Data for browser_created event"""

	session_id: str
	live_url: str
	status: str


class LogData(BaseModel):
	"""Data for log event"""

	message: str
	level: str = 'info'  # stdout, stderr, info, warning, error


class ExecutionResponse(BaseModel):
	"""Execution result from the executor"""

	success: bool
	result: Any = None
	error: str | None = None
	traceback: str | None = None


class ResultData(BaseModel):
	"""Data for result event"""

	execution_response: ExecutionResponse


class ErrorData(BaseModel):
	"""Data for error event"""

	error: str
	traceback: str | None = None
	status_code: int = 500


class SSEEvent(BaseModel):
	"""Type-safe SSE Event

	Usage:
	    # Parse from JSON
	    event = SSEEvent.from_json(event_json_string)

	    # Type-safe access with type guards
	    if event.is_browser_created():
	        assert isinstance(event.data, BrowserCreatedData)
	        print(event.data.live_url)

	    # Or check event type directly
	    if event.type == SSEEventType.LOG:
	        assert isinstance(event.data, LogData)
	        print(event.data.message)
	"""

	type: SSEEventType
	data: BrowserCreatedData | LogData | ResultData | ErrorData | dict[str, Any]
	timestamp: str | None = None

	@classmethod
	def from_json(cls, event_json: str) -> 'SSEEvent':
		"""Parse SSE event from JSON string with proper type discrimination

		Args:
		    event_json: JSON string from SSE stream

		Returns:
		    Typed SSEEvent with appropriate data model

		Raises:
		    json.JSONDecodeError: If JSON is malformed
		    ValueError: If event type is invalid
		"""
		raw_data = json.loads(event_json)
		event_type = SSEEventType(raw_data.get('type'))
		data_dict = raw_data.get('data', {})

		# Parse data based on event type
		if event_type == SSEEventType.BROWSER_CREATED:
			data = BrowserCreatedData(**data_dict)
		elif event_type == SSEEventType.LOG:
			data = LogData(**data_dict)
		elif event_type == SSEEventType.RESULT:
			data = ResultData(**data_dict)
		elif event_type == SSEEventType.ERROR:
			data = ErrorData(**data_dict)
		else:
			data = data_dict

		return cls(type=event_type, data=data, timestamp=raw_data.get('timestamp'))

	def is_browser_created(self) -> bool:
		"""Type guard for BrowserCreatedData"""
		return self.type == SSEEventType.BROWSER_CREATED and isinstance(self.data, BrowserCreatedData)

	def is_log(self) -> bool:
		"""Type guard for LogData"""
		return self.type == SSEEventType.LOG and isinstance(self.data, LogData)

	def is_result(self) -> bool:
		"""Type guard for ResultData"""
		return self.type == SSEEventType.RESULT and isinstance(self.data, ResultData)

	def is_error(self) -> bool:
		"""Type guard for ErrorData"""
		return self.type == SSEEventType.ERROR and isinstance(self.data, ErrorData)
