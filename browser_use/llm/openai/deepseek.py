from browser_use.llm.openai.chat import ChatOpenAI
import json

from dataclasses import dataclass
from typing import TypeVar, overload
from openai.types.shared_params.response_format_json_object import ResponseFormatJSONObject

from openai import APIConnectionError, APIStatusError, RateLimitError

from openai.types.shared.chat_model import ChatModel
from openai.types.shared_params.response_format_json_schema import JSONSchema

from pydantic import BaseModel

from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.messages import BaseMessage
from browser_use.llm.openai.serializer import OpenAIMessageSerializer
from browser_use.llm.schema import SchemaOptimizer
from browser_use.llm.views import ChatInvokeCompletion


from browser_use.llm.messages import (
	# AssistantMessage,
	BaseMessage,
	# ContentPartImageParam,
	# ContentPartRefusalParam,
	ContentPartTextParam,
	SystemMessage,
	# ToolCall,
	# UserMessage,
)

T = TypeVar('T', bound=BaseModel)

ReasoningModels: list[ChatModel | str] = ['deepseek-reasoner']


@dataclass
class ChatDeepSeek(ChatOpenAI):
	"""
	A class for to interact with DeepSeek using the OpenAI API schema.
	"""
    

	def append_json_schema(self, messages: list[BaseMessage], output_format: type[T] ) -> list[BaseMessage]:
		"""
		Append a JSON schema to the system messages since the model completion API does not support JSON schema.
		If this is not done, the model's returned result will not be parsed successfully according to the output_format.
		
		Args:
			messages: List of chat messages
			output_format: JSON schema to append

		Returns:
			List of chat messages with JSON schema appended
		"""
		response_format: JSONSchema = {
					'name': 'agent_output',
					'strict': True,
					'schema': SchemaOptimizer.create_optimized_json_schema(output_format),
				}

		hasSystemMessage = False
		for message in messages:
			if not isinstance(message, SystemMessage):
				continue
			if isinstance(message.content, str):
				hasSystemMessage = True
				content = str(message.content).replace("</output>","Please strictly abide by the following json schema:<output_json_schema> </output>")
				message.content = content + "\n\n <output_json_schema>"  + json.dumps(response_format) +"</output_json_schema>"

			elif isinstance(message.content, list):
				content = str(message.content[-1].text).replace("</output>","Please strictly abide by the following json schema:<output_json_schema> </output>")
				message.content[-1].text = content + "\n\n <output_json_schema>"  + json.dumps(response_format) +"</output_json_schema>"
				message.content.append(
					ContentPartTextParam(
						text="\n\n <output_json_schema>"  + json.dumps(response_format) +"</output_json_schema>"
					)
				)
		if not hasSystemMessage:
			messages.insert(
				0,
				SystemMessage(
					content=[
						ContentPartTextParam(
							text="Please output in JSON format and use the following JSON schema: "
							+ json.dumps(response_format)
						)
					]
				),
			)
		return messages
	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: None = None) -> ChatInvokeCompletion[str]: ...

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: type[T]) -> ChatInvokeCompletion[T]: ...

	async def ainvoke(
		self, messages: list[BaseMessage], output_format: type[T] | None = None
	) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
		"""
		Invoke the model with the given messages.

		Args:
			messages: List of chat messages
			output_format: Optional Pydantic model class for structured output

		Returns:
			Either a string response or an instance of output_format
		"""

		try:
			reasoning_effort_dict: dict = {}
			if self.model in ReasoningModels:
				reasoning_effort_dict = {
					'reasoning_effort': self.reasoning_effort,
				}

			if output_format is None:
				openai_messages = OpenAIMessageSerializer.serialize_messages(messages)
				# Return string response
				response = await self.get_client().chat.completions.create(
					model=self.model,
					messages=openai_messages,
					temperature=self.temperature,
					**reasoning_effort_dict,
				)

				usage = self._get_usage(response)
				return ChatInvokeCompletion(
					completion=response.choices[0].message.content or '',
					usage=usage,
				)

			else:
				
				messages = self.append_json_schema(messages, output_format)
				openai_messages = OpenAIMessageSerializer.serialize_messages(messages)


				# Return structured response
				response = await self.get_client().chat.completions.create(
					model=self.model,
					messages=openai_messages,
					temperature=self.temperature,
					response_format= ResponseFormatJSONObject(
						type="json_object",
					),
					**reasoning_effort_dict,
				)

				# print("\n\nRESPONSE.message:", response.choices[0].message.content)

				if response.choices[0].message.content is None:
					raise ModelProviderError(
						message='Failed to parse structured output from model response',
						status_code=500,
						model=self.name,
					)

				usage = self._get_usage(response)

				parsed = output_format.model_validate_json(response.choices[0].message.content)

				return ChatInvokeCompletion(
					completion=parsed,
					usage=usage,
				)

		except RateLimitError as e:
			error_message = e.response.json().get('error', {})
			error_message = (
				error_message.get('message', 'Unknown model error') if isinstance(error_message, dict) else error_message
			)
			raise ModelProviderError(
				message=error_message,
				status_code=e.response.status_code,
				model=self.name,
			) from e

		except APIConnectionError as e:
			raise ModelProviderError(message=str(e), model=self.name) from e

		except APIStatusError as e:
			try:
				error_message = e.response.json().get('error', {})
			except Exception:
				error_message = e.response.text
			error_message = (
				error_message.get('message', 'Unknown model error') if isinstance(error_message, dict) else error_message
			)
			raise ModelProviderError(
				message=error_message,
				status_code=e.response.status_code,
				model=self.name,
			) from e

		except Exception as e:
			raise ModelProviderError(message=str(e), model=self.name) from e

