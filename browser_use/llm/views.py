from typing import Generic, TypeVar, Union

from pydantic import BaseModel

T = TypeVar('T', bound=Union[BaseModel, str])


class ChatInvokeUsage(BaseModel):
	"""
	Usage information for a chat model invocation.
	"""

	prompt_tokens: int
	"""The number of tokens in the prompt (this includes the cached tokens as well. When calculating the cost, subtract the cached tokens from the prompt tokens)"""

	prompt_cached_tokens: int | None
	"""The number of cached tokens."""

	prompt_cache_creation_tokens: int | None
	"""Anthropic only: The number of tokens used to create the cache."""

	prompt_image_tokens: int | None
	"""Google only: The number of tokens in the image (prompt tokens is the text tokens + image tokens in that case)"""

	completion_tokens: int
	"""The number of tokens in the completion."""

	total_tokens: int
	"""The total number of tokens in the response."""


class ChatInvokeCompletion(BaseModel, Generic[T]):
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
