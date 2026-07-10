"""
We have switched all of our code from langchain to openai.types.chat.chat_completion_message_param.

For easier transition we have
"""

from typing import Any, Literal, Protocol, TypeVar, overload, runtime_checkable

from pydantic import BaseModel

from browser_use.llm.messages import BaseMessage
from browser_use.llm.views import ChatInvokeCompletion, ModelCapabilities

T = TypeVar('T', bound=BaseModel)


class ToolDefinition(BaseModel):
	"""Provider-neutral function tool definition."""

	name: str
	description: str
	parameters: dict[str, Any]
	strict: bool = True


ToolChoice = Literal['auto', 'required', 'none'] | str


@runtime_checkable
class BaseChatModel(Protocol):
	_verified_api_keys: bool = False

	model: str

	@property
	def provider(self) -> str: ...

	@property
	def name(self) -> str: ...

	@property
	def model_capabilities(self) -> ModelCapabilities:
		"""Return conservative defaults for adapters without native tool support."""
		return ModelCapabilities()

	@property
	def model_name(self) -> str:
		# for legacy support
		return self.model

	@overload
	async def ainvoke(
		self,
		messages: list[BaseMessage],
		output_format: None = None,
		tools: list[ToolDefinition] | None = None,
		tool_choice: ToolChoice | None = None,
		**kwargs: Any,
	) -> ChatInvokeCompletion[str]: ...

	@overload
	async def ainvoke(
		self,
		messages: list[BaseMessage],
		output_format: type[T],
		tools: list[ToolDefinition] | None = None,
		tool_choice: ToolChoice | None = None,
		**kwargs: Any,
	) -> ChatInvokeCompletion[T]: ...

	async def ainvoke(
		self,
		messages: list[BaseMessage],
		output_format: type[T] | None = None,
		tools: list[ToolDefinition] | None = None,
		tool_choice: ToolChoice | None = None,
		**kwargs: Any,
	) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]: ...

	@classmethod
	def __get_pydantic_core_schema__(
		cls,
		source_type: type,
		handler: Any,
	) -> Any:
		"""
		Allow this Protocol to be used in Pydantic models -> very useful to typesafe the agent settings for example.
		Returns a schema that allows any object (since this is a Protocol).
		"""
		from pydantic_core import core_schema

		# Return a schema that accepts any object for Protocol types
		return core_schema.any_schema()
