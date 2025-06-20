"""
We have switched all of our code from langchain to openai.types.chat.chat_completion_message_param.

For easier transition we have
"""

from typing import Protocol, Type, TypeVar, overload

from openai.types.chat.chat_completion_message_param import (
	ChatCompletionMessageParam,
)
from pydantic import BaseModel

T = TypeVar('T', bound=BaseModel)


class BaseChatModel(Protocol):
	_verified_api_keys: bool = False

	model_name: str

	@property
	def provider(self) -> str: ...

	@property
	def llm_type(self) -> str: ...

	@property
	def name(self) -> str: ...

	@overload
	async def ainvoke(self, messages: list[ChatCompletionMessageParam], output_format: None = None) -> str: ...

	@overload
	async def ainvoke(self, messages: list[ChatCompletionMessageParam], output_format: Type[T]) -> T: ...

	async def ainvoke(self, messages: list[ChatCompletionMessageParam], output_format: Type[T] | None = None) -> T | str: ...
