from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeVar, overload

from pydantic import BaseModel

from browser_use.llm.base import BaseChatModel
from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.messages import BaseMessage
from browser_use.llm.views import ChatInvokeCompletion, ChatInvokeUsage
from examples.models.langchain.serializer import LangChainMessageSerializer

if TYPE_CHECKING:
	from langchain_core.language_models.chat_models import BaseChatModel as LangChainBaseChatModel  # type: ignore
	from langchain_core.messages import AIMessage as LangChainAIMessage  # type: ignore

T = TypeVar('T', bound=BaseModel)


@dataclass
class ChatLangchain(BaseChatModel):
	"""
	A wrapper around LangChain BaseChatModel that implements the browser-use BaseChatModel protocol.

	This class allows you to use any LangChain-compatible model with browser-use.
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
		usage = response.usage_metadata
		if usage is None:
			return None

		prompt_tokens = usage['input_tokens'] or 0
		completion_tokens = usage['output_tokens'] or 0
		total_tokens = usage['total_tokens'] or 0

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
	async def ainvoke(self, messages: list[BaseMessage], output_format: None = None) -> ChatInvokeCompletion[str]: ...

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: type[T]) -> ChatInvokeCompletion[T]: ...

	async def ainvoke(
		self, messages: list[BaseMessage], output_format: type[T] | None = None
	) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
		"""
		Invoke the LangChain model with the given messages.

		Args:
			messages: List of browser-use chat messages
			output_format: Optional Pydantic model class for structured output (not supported in basic LangChain integration)

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

					if not isinstance(response, 'LangChainAIMessage'):
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
