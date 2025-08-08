import logging
import os
from dataclasses import dataclass
from typing import Any, TypeVar, cast, overload

from httpx import URL
from openai import (
	APIError,
	APIResponseValidationError,
	APIStatusError,
	AsyncOpenAI,
	NotGiven,
	RateLimitError,
	Timeout,
)
from openai.types.chat import ChatCompletion
from openai.types.chat.chat_completion_message_param import ChatCompletionMessageParam
from pydantic import BaseModel

from browser_use.llm.base import BaseChatModel, ChatInvokeCompletion
from browser_use.llm.exceptions import ModelProviderError, ModelRateLimitError
from browser_use.llm.messages import BaseMessage
from browser_use.llm.openai.serializer import OpenAIMessageSerializer
from browser_use.llm.schema import SchemaOptimizer
from browser_use.llm.views import ChatInvokeUsage

T = TypeVar('T', bound=BaseModel)
logger = logging.getLogger(__name__)


@dataclass
class ChatQwen(BaseChatModel):
	"""
	A wrapper around DashScope's OpenAI-compatible API for Qwen models.
	"""

	model: str

	temperature: float | None = None
	top_p: float | None = None
	max_tokens: int | None = None
	enable_thinking: bool = False

	api_key: str | None = None
	base_url: str | URL | None = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
	timeout: float | Timeout | NotGiven | None = None
	max_retries: int = 10

	def get_client(self) -> AsyncOpenAI:
		api_key = self.api_key or os.getenv('DASHSCOPE_API_KEY')
		return AsyncOpenAI(api_key=api_key, base_url=self.base_url, timeout=self.timeout, max_retries=self.max_retries)

	@property
	def provider(self) -> str:
		return 'qwen'

	@property
	def name(self) -> str:
		return str(self.model)

	def _get_usage(self, response: ChatCompletion) -> ChatInvokeUsage | None:
		usage = (
			ChatInvokeUsage(
				prompt_tokens=response.usage.prompt_tokens,
				completion_tokens=response.usage.completion_tokens,
				total_tokens=response.usage.total_tokens,
				prompt_cached_tokens=None,
				prompt_cache_creation_tokens=None,
				prompt_image_tokens=None,
			)
			if response.usage is not None
			else None
		)
		return usage

	def _clean_json_response(self, content: str) -> str:
		"""Clean markdown code blocks and fix common action naming issues."""
		if not content:
			return content

		# Remove markdown code blocks
		if content.startswith('```json'):
			content = content[7:]
		elif content.startswith('```'):
			content = content[3:]
		if content.endswith('```'):
			content = content[:-3]

		content = content.strip()

		# Fix common action naming mistakes
		import json

		try:
			data = json.loads(content)
			if isinstance(data, dict) and 'action' in data:
				actions = data['action']
				if isinstance(actions, list):
					for action in actions:
						if isinstance(action, dict):
							# Fix common naming mistakes
							if 'goto' in action:
								action['go_to_url'] = action.pop('goto')
							elif 'navigate' in action:
								action['go_to_url'] = action.pop('navigate')
							elif 'open_new_tab' in action:
								# Convert open_new_tab to go_to_url
								open_tab_data = action.pop('open_new_tab')
								if isinstance(open_tab_data, dict) and 'url' in open_tab_data:
									action['go_to_url'] = open_tab_data
							elif 'click' in action:
								action['click_element_by_index'] = action.pop('click')
							elif 'type' in action:
								action['input_text'] = action.pop('type')

			# Return the cleaned JSON
			return json.dumps(data, ensure_ascii=False)
		except (json.JSONDecodeError, KeyError, TypeError):
			# If parsing fails, return original content
			pass

		return content

	def _add_json_schema_instruction(
		self, messages: list[ChatCompletionMessageParam], output_format: type[BaseModel]
	) -> list[dict[str, Any]]:
		"""Add JSON schema instruction to messages for structured output."""
		schema = SchemaOptimizer.create_optimized_json_schema(output_format)

		if output_format.__name__ == 'AgentOutput':
			schema_instruction = (
				' Please respond with valid JSON using these exact fields:\n'
				'- thinking (string, optional): Your thought process\n'
				'- evaluation_previous_goal (string): Evaluation of the previous goal\n'
				'- memory (string): What you remember\n'
				'- next_goal (string): Your next goal\n'
				'- action (array): List of actions, each action must have exactly ONE field from the available actions\n\n'
				'CRITICAL ACTION NAMING RULES:\n'
				'- To navigate to a URL, use: {"go_to_url": {"url": "https://example.com"}}\n'
				'- To click an element, use: {"click_element_by_index": {"index": 0}}\n'
				'- To input text, use: {"input_text": {"index": 0, "text": "your text"}}\n'
				'- To search Google, use: {"search_google": {"query": "search terms"}}\n'
				'- To complete task, use: {"done": {"done": "Task completed"}}\n'
				'- To scroll, use: {"scroll": {"direction": "down", "amount": 3}}\n'
				'- To wait, use: {"wait": {"seconds": 2}}\n\n'
				"NEVER use action names like 'goto', 'navigate', 'click', 'type' - these are INVALID. "
				'Each action object must contain exactly one valid action field with its parameters. '
				'Do not include any markdown code blocks, just return the raw JSON.'
			)
		else:
			field_descriptions = []
			if 'properties' in schema:
				for field_name, field_info in schema['properties'].items():
					field_type = field_info.get('type', 'string')
					field_desc = field_info.get('description', '')
					desc_suffix = f' ({field_desc})' if field_desc else ''
					field_descriptions.append(f'{field_name} ({field_type}){desc_suffix}')

			if field_descriptions:
				fields_text = ', '.join(field_descriptions)
				schema_instruction = f' Please respond with valid JSON using exactly these fields: {fields_text}. Do not include any markdown code blocks, just return the raw JSON.'
			else:
				schema_instruction = f' Please respond with valid JSON that follows this exact schema: {schema}. Do not include any markdown code blocks, just return the raw JSON.'

		# Convert to dict format for easier manipulation
		messages_dict = []
		for msg in messages:
			if isinstance(msg, dict):
				messages_dict.append(msg.copy())
			else:
				# Convert to dict if it's not already
				messages_dict.append(dict(msg))

		# Add schema instruction to the last user message
		for msg in reversed(messages_dict):
			if msg.get('role') == 'user':
				content = msg.get('content', '')
				if isinstance(content, list):
					for part in reversed(content):
						if isinstance(part, dict) and part.get('type') == 'text':
							text_content = part.get('text', '')
							if 'json' not in text_content.lower():
								part['text'] = text_content + schema_instruction
							break
				elif isinstance(content, str):
					if 'json' not in content.lower():
						msg['content'] = content + schema_instruction
				break

		return messages_dict

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: None = None) -> ChatInvokeCompletion[str]: ...

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: type[T]) -> ChatInvokeCompletion[T]: ...

	async def ainvoke(
		self, messages: list[BaseMessage], output_format: type[T] | None = None
	) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
		openai_messages = OpenAIMessageSerializer.serialize_messages(messages)

		if output_format is not None:
			openai_messages = self._add_json_schema_instruction(openai_messages, output_format)

		try:
			model_params: dict[str, Any] = {}
			if self.temperature is not None:
				model_params['temperature'] = self.temperature
			if self.top_p is not None:
				model_params['top_p'] = self.top_p
			if self.max_tokens is not None:
				model_params['max_tokens'] = self.max_tokens

			extra_body = {'enable_thinking': self.enable_thinking}

			if output_format is None:
				return await self._invoke_regular_completion(
					cast(list[ChatCompletionMessageParam], openai_messages), model_params, extra_body
				)
			else:
				return await self._invoke_structured_output(
					cast(list[ChatCompletionMessageParam], openai_messages), output_format, model_params, extra_body
				)

		except RateLimitError as e:
			raise ModelRateLimitError(message=e.response.text, status_code=e.response.status_code, model=self.name) from e

		except APIResponseValidationError as e:
			raise ModelProviderError(message=e.response.text, status_code=e.response.status_code, model=self.name) from e

		except APIStatusError as e:
			raise ModelProviderError(message=e.response.text, status_code=e.response.status_code, model=self.name) from e

		except APIError as e:
			raise ModelProviderError(message=e.message, model=self.name) from e
		except Exception as e:
			raise ModelProviderError(message=str(e), model=self.name) from e

	async def _invoke_regular_completion(
		self, openai_messages: list[ChatCompletionMessageParam], model_params: dict[str, Any], extra_body: dict[str, Any]
	) -> ChatInvokeCompletion[str]:
		response = await self.get_client().chat.completions.create(
			messages=openai_messages,
			model=self.model,
			extra_body=extra_body,
			**model_params,
		)
		usage = self._get_usage(response)
		return ChatInvokeCompletion(
			completion=response.choices[0].message.content or '',
			usage=usage,
		)

	async def _invoke_structured_output(
		self,
		openai_messages: list[ChatCompletionMessageParam],
		output_format: type[T],
		model_params: dict[str, Any],
		extra_body: dict[str, Any],
	) -> ChatInvokeCompletion[T]:
		response = await self.get_client().chat.completions.create(
			messages=openai_messages,
			model=self.model,
			extra_body=extra_body,
			**model_params,
		)

		if not response.choices[0].message.content:
			raise ModelProviderError(
				message='No content in response',
				status_code=500,
				model=self.name,
			)

		content = self._clean_json_response(response.choices[0].message.content)
		parsed_response = output_format.model_validate_json(content)
		usage = self._get_usage(response)

		return ChatInvokeCompletion(
			completion=parsed_response,
			usage=usage,
		)
