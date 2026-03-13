"""
LangChain compatibility wrapper for browser-use.

This wrapper allows using any LangChain-compatible model with browser-use's Agent.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar, overload

from pydantic import BaseModel

from browser_use.llm.base import BaseChatModel
from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.langchain.serializer import LangChainMessageSerializer
from browser_use.llm.messages import BaseMessage
from browser_use.llm.views import ChatInvokeCompletion, ChatInvokeUsage

if TYPE_CHECKING:
	from langchain_core.language_models.chat_models import BaseChatModel as LangChainBaseChatModel  # type: ignore
	from langchain_core.messages import AIMessage as LangChainAIMessage  # type: ignore

T = TypeVar('T', bound=BaseModel)


def is_langchain_model(obj: Any) -> bool:
	"""
	Check if an object is a LangChain model by duck typing.

	This function checks for LangChain-specific attributes without requiring
	langchain_core to be installed.
	"""
	# Check for common LangChain BaseChatModel attributes
	langchain_attributes = [
		'invoke',  # Sync invocation
		'ainvoke',  # Async invocation
		'bind_tools',  # Tool binding
	]

	# Check if object has these attributes (duck typing)
	has_langchain_attrs = all(hasattr(obj, attr) for attr in langchain_attributes)

	# Also check module name to be more certain
	module = getattr(obj.__class__, '__module__', '')
	is_langchain_module = 'langchain' in module

	# Check if it's from browser-use by looking at the module
	browser_use_module = 'browser_use' in module

	# Must have LangChain attributes AND be from langchain module AND NOT from browser-use
	return has_langchain_attrs and is_langchain_module and not browser_use_module


def wrap_langchain_model(llm: Any) -> 'ChatLangchain':
	"""
	Wrap a LangChain model for use with browser-use.

	Args:
		llm: A LangChain-compatible chat model

	Returns:
		A ChatLangchain wrapper instance
	"""
	return ChatLangchain(chat=llm)


@dataclass
class ChatLangchain(BaseChatModel):
	"""
	A wrapper around LangChain BaseChatModel that implements the browser-use BaseChatModel protocol.

	This class allows you to use any LangChain-compatible model with browser-use.

	Example:
		```python
	        from langchain_anthropic import ChatAnthropic
	        from browser_use.llm.langchain import ChatLangchain

	        langchain_model = ChatAnthropic(model='claude-3-5-sonnet-20241022')
	        llm = ChatLangchain(chat=langchain_model)

	        agent = Agent(task='...', llm=llm)
		```

	Note:
		For best performance and reliability, consider using browser-use's native
		model wrappers instead (e.g., `from browser_use.llm import ChatAnthropic`).
	"""

	# The LangChain model to wrap
	chat: 'LangChainBaseChatModel'

	@property
	def model(self) -> str:
		return self.name

	@property
	def provider(self) -> str:
		"""Return the provider name based on the LangChain model class."""
		model_class_name = self.chat.__class__.__name__.lower()
		if 'openai' in model_class_name:
			return 'openai'
		elif 'anthropic' in model_class_name or 'claude' in model_class_name:
			return 'anthropic'
		elif 'google' in model_class_name or 'gemini' in model_class_name:
			return 'google'
		elif 'groq' in model_class_name:
			return 'groq'
		elif 'ollama' in model_class_name:
			return 'ollama'
		elif 'deepseek' in model_class_name:
			return 'deepseek'
		else:
			return 'langchain'

	@property
	def name(self) -> str:
		"""Return the model name."""
		# Try to get model name from the LangChain model using getattr to avoid type errors
		model_name = getattr(self.chat, 'model_name', None)
		if model_name:
			return str(model_name)

		model_attr = getattr(self.chat, 'model', None)
		if model_attr:
			return str(model_attr)

		return self.chat.__class__.__name__

	def _get_usage(self, response: 'LangChainAIMessage') -> ChatInvokeUsage | None:
		usage = getattr(response, 'usage_metadata', None)
		if usage is None:
			return None

		prompt_tokens = usage.get('input_tokens', 0) or 0
		completion_tokens = usage.get('output_tokens', 0) or 0
		total_tokens = usage.get('total_tokens', 0) or 0

		input_token_details = usage.get('input_token_details', None)

		if input_token_details is not None:
			prompt_cached_tokens = input_token_details.get('cache_read', None)
			prompt_cache_creation_tokens = input_token_details.get('cache_creation', None)
		else:
			prompt_cached_tokens = None
			prompt_cache_creation_tokens = None

		return ChatInvokeUsage(
			prompt_tokens=prompt_tokens,
			prompt_cached_tokens=prompt_cached_tokens,
			prompt_cache_creation_tokens=prompt_cache_creation_tokens,
			prompt_image_tokens=None,
			completion_tokens=completion_tokens,
			total_tokens=total_tokens,
		)

	@overload
	async def ainvoke(
		self, messages: list[BaseMessage], output_format: None = None, **kwargs: Any
	) -> ChatInvokeCompletion[str]: ...

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: type[T], **kwargs: Any) -> ChatInvokeCompletion[T]: ...

	async def ainvoke(
		self, messages: list[BaseMessage], output_format: type[T] | None = None, **kwargs: Any
	) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
		"""
		Invoke the LangChain model with the given messages.

		Args:
			messages: List of browser-use chat messages
			output_format: Optional Pydantic model class for structured output
			**kwargs: Additional arguments (ignored for LangChain compatibility)

		Returns:
			Either a string response or an instance of output_format
		"""
		# Convert browser-use messages to LangChain messages
		langchain_messages = LangChainMessageSerializer.serialize_messages(messages)

		try:
			if output_format is None:
				# Return string response
				response = await self.chat.ainvoke(langchain_messages)  # type: ignore

				# Import at runtime for isinstance check
				from langchain_core.messages import AIMessage as LangChainAIMessage  # type: ignore

				if not isinstance(response, LangChainAIMessage):
					raise ModelProviderError(
						message=f'Response is not an AIMessage: {type(response)}',
						model=self.name,
					)

				# Extract content from LangChain response
				content = response.content if hasattr(response, 'content') else str(response)

				usage = self._get_usage(response)
				return ChatInvokeCompletion(
					completion=str(content),
					usage=usage,
				)

			else:
				# Use LangChain's structured output capability
				try:
					structured_chat = self.chat.with_structured_output(output_format)
					parsed_object = await structured_chat.ainvoke(langchain_messages)

					# For structured output, usage metadata is typically not available
					# in the parsed object since it's a Pydantic model, not an AIMessage
					usage = None

					# Type cast since LangChain's with_structured_output returns the correct type
					return ChatInvokeCompletion(
						completion=parsed_object,  # type: ignore
						usage=usage,
					)
				except AttributeError:
					# Fall back to manual parsing if with_structured_output is not available
					response = await self.chat.ainvoke(langchain_messages)  # type: ignore

					from langchain_core.messages import AIMessage as LangChainAIMessage  # type: ignore

					if not isinstance(response, LangChainAIMessage):
						raise ModelProviderError(
							message=f'Response is not an AIMessage: {type(response)}',
							model=self.name,
						)

					content = response.content if hasattr(response, 'content') else str(response)

					try:
						if isinstance(content, str):
							import json

							parsed_data = json.loads(content)
							if isinstance(parsed_data, dict):
								parsed_object = output_format(**parsed_data)
							else:
								raise ValueError('Parsed JSON is not a dictionary')
						else:
							raise ValueError('Content is not a string and structured output not supported')
					except Exception as e:
						raise ModelProviderError(
							message=f'Failed to parse response as {output_format.__name__}: {e}',
							model=self.name,
						) from e

					usage = self._get_usage(response)
					return ChatInvokeCompletion(
						completion=parsed_object,
						usage=usage,
					)

		except Exception as e:
			# Convert any LangChain errors to browser-use ModelProviderError
			raise ModelProviderError(
				message=f'LangChain model error: {str(e)}',
				model=self.name,
			) from e
