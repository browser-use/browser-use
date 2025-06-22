from typing import TypeVar

from pydantic import BaseModel

T = TypeVar('T', bound=BaseModel)


class ChatInvokeUsage(BaseModel):
	"""
	Usage information for a chat model invocation.
	"""

	prompt_tokens: int
	"""The number of tokens in the prompt."""

	completion_tokens: int
	"""The number of tokens in the completion."""

	total_tokens: int
	"""The total number of tokens in the response."""

	image_tokens: int | None = None
	"""The number of tokens in the image. Google only (prompt tokens is the text tokens + image tokens in that case)"""


class ChatInvokeCompletion[T: BaseModel | str](BaseModel):
	"""
	Response from a chat model invocation.
	"""

	completion: T
	"""The completion of the response."""

	# Thinking stuff
	thinking: str | None = None
	redacted_thinking: str | None = None

	usage: ChatInvokeUsage | None
	"""The usage of the response."""
