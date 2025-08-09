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

	# Option to disable structured output when using incompatible APIs
	disable_structured_output: bool = False

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
			output_format: Optional Pydantic model class for structured output

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
				structured_output_success = False
				response = None

				# First, try to use structured output if not disabled
				if not self.disable_structured_output:
					try:
						# For LangChain OpenAI models, disable json_schema mode if it's causing issues
						if hasattr(self.chat, 'model_kwargs'):
							# Temporarily modify model kwargs to use json_mode instead of json_schema
							original_kwargs = getattr(self.chat, 'model_kwargs', {})
							setattr(self.chat, 'model_kwargs', {**original_kwargs})

							# Check if this is a ChatOpenAI model with structured output issues
							if self.chat.__class__.__name__ == 'ChatOpenAI':
								# Use method="function_calling" instead of default "json_mode"
								structured_chat = self.chat.with_structured_output(output_format, method='function_calling')
							else:
								structured_chat = self.chat.with_structured_output(output_format)
						else:
							structured_chat = self.chat.with_structured_output(output_format)

						parsed_object = await structured_chat.ainvoke(langchain_messages)
						structured_output_success = True

						# For structured output, usage metadata is typically not available
						# in the parsed object since it's a Pydantic model, not an AIMessage
						usage = None

						# Type cast since LangChain's with_structured_output returns the correct type
						return ChatInvokeCompletion(
							completion=parsed_object,  # type: ignore
							usage=usage,
						)
					except Exception as e:
						# If structured output fails, fall back to manual parsing
						# This handles cases where the API doesn't support json_schema
						if 'json_schema' in str(e) or 'response_format' in str(e):
							# Fall through to manual parsing
							pass
						else:
							# Re-raise other errors
							raise

				# Fall back to manual parsing if structured output failed or was disabled
				if not structured_output_success:
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

							# Try to extract JSON from the content
							# Handle cases where the model returns markdown code blocks
							content_str = str(content).strip()
							if content_str.startswith('```json') and content_str.endswith('```'):
								content_str = content_str[7:-3].strip()
							elif content_str.startswith('```') and content_str.endswith('```'):
								content_str = content_str[3:-3].strip()

							parsed_data = json.loads(content_str)
							if isinstance(parsed_data, dict):
								parsed_object = output_format(**parsed_data)
							else:
								raise ValueError('Parsed JSON is not a dictionary')
						else:
							raise ValueError('Content is not a string and structured output not supported')
					except Exception as e:
						raise ModelProviderError(
							message=f'Failed to parse response as {output_format.__name__}: {e}. Consider using disable_structured_output=True for APIs that do not support structured output.',
							model=self.name,
						) from e

					usage = self._get_usage(response)
					return ChatInvokeCompletion(
						completion=parsed_object,
						usage=usage,
					)

		except ModelProviderError:
			# Re-raise our own errors
			raise
		except Exception as e:
			# Convert any LangChain errors to browser-use ModelProviderError
			raise ModelProviderError(
				message=f'LangChain model error: {str(e)}',
				model=self.name,
			) from e

		# This should never be reached, but add fallback for type checker
		raise ModelProviderError(
			message='Unexpected code path reached in ainvoke',
			model=self.name,
		)
