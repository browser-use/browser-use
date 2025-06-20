"""
We have switched all of our code from langchain to openai.types.chat.chat_completion_message_param.

For easier transition we have
"""

from typing import Protocol, Type, TypeVar, overload

from pydantic import BaseModel

from browser_use.llm.messages import BaseMessage

T = TypeVar('T', bound=BaseModel)


class BaseChatModel(Protocol):
	_verified_api_keys: bool = False

	model: str

	@property
	def provider(self) -> str: ...

	@property
	def llm_type(self) -> str: ...

	@property
	def name(self) -> str: ...

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: None = None) -> str: ...

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: Type[T]) -> T: ...

	async def ainvoke(self, messages: list[BaseMessage], output_format: Type[T] | None = None) -> T | str: ...
