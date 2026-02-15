"""Wire protocol for CLI↔Server communication.

Uses JSON over Unix sockets (or TCP on Windows) with newline-delimited messages.
"""

import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Request:
	"""Command request from CLI to server."""

	id: str
	action: str
	session: str
	params: dict[str, Any] = field(default_factory=dict)

	def to_json(self) -> str:
		return json.dumps(asdict(self))

	@classmethod
	def from_json(cls, data: str) -> 'Request':
		d = json.loads(data)
		return cls(
			id=d['id'],
			action=d['action'],
			session=d['session'],
			params=d.get('params', {}),
		)


@dataclass
class Response:
	"""Response from server to CLI."""

	id: str
	success: bool
	data: Any = None
	error: str | None = None

	def to_json(self) -> str:
		return json.dumps(asdict(self))

	@classmethod
	def from_json(cls, data: str) -> 'Response':
		d = json.loads(data)
		return cls(
			id=d['id'],
			success=d['success'],
			data=d.get('data'),
			error=d.get('error'),
		)
