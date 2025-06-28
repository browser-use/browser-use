import json
from dataclasses import dataclass
from os import getenv
from typing import TYPE_CHECKING, Any, TypeVar, overload

from pydantic import BaseModel

from browser_use.llm.aws.serializer import AWSBedrockMessageSerializer
from browser_use.llm.base import BaseChatModel
from browser_use.llm.exceptions import ModelProviderError, ModelRateLimitError
from browser_use.llm.messages import BaseMessage
from browser_use.llm.views import ChatInvokeCompletion, ChatInvokeUsage

if TYPE_CHECKING:
	from boto3 import client as AwsClient  # type: ignore
	from boto3.session import Session  # type: ignore

T = TypeVar('T', bound=BaseModel)


@dataclass
class ChatAWSBedrock(BaseChatModel):
	"""
	AWS Bedrock chat model supporting multiple providers (Anthropic, Meta, etc.).

	This class provides access to various models via AWS Bedrock,
	supporting both text generation and structured output via tool calling.

	To use this model, you need to either:
	1. Set the following environment variables:
	   - AWS_ACCESS_KEY_ID
	   - AWS_SECRET_ACCESS_KEY
	   - AWS_REGION
	2. Or provide a boto3 Session object
	3. Or use AWS SSO authentication
	"""

	# Model configuration
	model: str = 'anthropic.claude-3-5-sonnet-20240620-v1:0'
	max_tokens: int | None = 4096
	temperature: float | None = None
	top_p: float | None = None
	stop_sequences: list[str] | None = None

	# AWS credentials and configuration
	aws_access_key_id: str | None = None
	aws_secret_access_key: str | None = None
	aws_region: str | None = None
	aws_sso_auth: bool = False
	session: 'Session | None' = None

	# Request parameters
	request_params: dict[str, Any] | None = None

	# Static
	@property
	def provider(self) -> str:
		return 'aws_bedrock'

	def _get_client(self) -> 'AwsClient':  # type: ignore
		"""Get the AWS Bedrock client."""
		try:
			from boto3 import client as AwsClient  # type: ignore
		except ImportError:
			raise ImportError(
				'`boto3` not installed. Please install using `pip install browser-use[aws] or pip install browser-use[all]`'
			)

		if self.session:
			return self.session.client('bedrock-runtime')

		# Get credentials from environment or instance parameters
		access_key = self.aws_access_key_id or getenv('AWS_ACCESS_KEY_ID')
		secret_key = self.aws_secret_access_key or getenv('AWS_SECRET_ACCESS_KEY')
		region = self.aws_region or getenv('AWS_REGION') or getenv('AWS_DEFAULT_REGION')

		if self.aws_sso_auth:
			return AwsClient(service_name='bedrock-runtime', region_name=region)
		else:
			if not access_key or not secret_key:
				raise ModelProviderError(
					message='AWS credentials not found. Please set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables or provide a boto3 session.',
					model=self.name,
				)

			return AwsClient(
				service_name='bedrock-runtime',
				region_name=region,
				aws_access_key_id=access_key,
				aws_secret_access_key=secret_key,
			)

	@property
	def name(self) -> str:
		return str(self.model)

	def _get_inference_config(self) -> dict[str, Any]:
		"""Get the inference configuration for the request."""
		config = {}
		if self.max_tokens is not None:
			config['maxTokens'] = self.max_tokens
		if self.temperature is not None:
			config['temperature'] = self.temperature
		if self.top_p is not None:
			config['topP'] = self.top_p
		if self.stop_sequences is not None:
			config['stopSequences'] = self.stop_sequences
		return config

	def _format_tools_for_request(self, output_format: type[BaseModel]) -> list[dict[str, Any]]:
		"""Format a Pydantic model as a tool for structured output."""
		schema = output_format.model_json_schema()

		# Convert Pydantic schema to Bedrock tool format
		properties = {}
		required = []

		for prop_name, prop_info in schema.get('properties', {}).items():
			properties[prop_name] = {
				'type': prop_info.get('type', 'string'),
				'description': prop_info.get('description', ''),
			}

		# Add required fields
		required = schema.get('required', [])

		return [
			{
				'toolSpec': {
					'name': f'extract_{output_format.__name__.lower()}',
					'description': f'Extract information in the format of {output_format.__name__}',
					'inputSchema': {'json': {'type': 'object', 'properties': properties, 'required': required}},
				}
			}
		]

	def _get_usage(self, response: dict[str, Any]) -> ChatInvokeUsage | None:
		"""Extract usage information from the response."""
		if 'usage' not in response:
			return None

		usage_data = response['usage']
		return ChatInvokeUsage(
			prompt_tokens=usage_data.get('inputTokens', 0),
			completion_tokens=usage_data.get('outputTokens', 0),
			total_tokens=usage_data.get('totalTokens', 0),
			prompt_cached_tokens=None,  # Bedrock doesn't provide this
			prompt_cache_creation_tokens=None,
			prompt_image_tokens=None,
		)

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: None = None) -> ChatInvokeCompletion[str]: ...

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: type[T]) -> ChatInvokeCompletion[T]: ...

	async def ainvoke(
		self, messages: list[BaseMessage], output_format: type[T] | None = None
	) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
		"""
		Invoke the AWS Bedrock model with the given messages.

		Args:
			messages: List of chat messages
			output_format: Optional Pydantic model class for structured output

		Returns:
			Either a string response or an instance of output_format
		"""
		try:
			from botocore.exceptions import ClientError  # type: ignore
		except ImportError:
			raise ImportError(
				'`boto3` not installed. Please install using `pip install browser-use[aws] or pip install browser-use[all]`'
			)

		bedrock_messages, system_message = AWSBedrockMessageSerializer.serialize_messages(messages)

		try:
			# Prepare the request body
			body: dict[str, Any] = {}

			if system_message:
				body['system'] = system_message

			inference_config = self._get_inference_config()
			if inference_config:
				body['inferenceConfig'] = inference_config

			# Handle structured output via tool calling
			if output_format is not None:
				tools = self._format_tools_for_request(output_format)
				body['toolConfig'] = {'tools': tools}

			# Add any additional request parameters
			if self.request_params:
				body.update(self.request_params)

			# Filter out None values
			body = {k: v for k, v in body.items() if v is not None}

			# Make the API call
			client = self._get_client()
			response = client.converse(modelId=self.model, messages=bedrock_messages, **body)

			usage = self._get_usage(response)

			# Extract the response content
			if 'output' in response and 'message' in response['output']:
				message = response['output']['message']
				content = message.get('content', [])

				if output_format is None:
					# Return text response
					text_content = []
					for item in content:
						if 'text' in item:
							text_content.append(item['text'])

					response_text = '\n'.join(text_content) if text_content else ''
					return ChatInvokeCompletion(
						completion=response_text,
						usage=usage,
					)
				else:
					# Handle structured output from tool calls
					for item in content:
						if 'toolUse' in item:
							tool_use = item['toolUse']
							tool_input = tool_use.get('input', {})

							try:
								# Validate and return the structured output
								return ChatInvokeCompletion(
									completion=output_format.model_validate(tool_input),
									usage=usage,
								)
							except Exception as e:
								# If validation fails, try to parse as JSON first
								if isinstance(tool_input, str):
									try:
										data = json.loads(tool_input)
										return ChatInvokeCompletion(
											completion=output_format.model_validate(data),
											usage=usage,
										)
									except json.JSONDecodeError:
										pass
								raise ModelProviderError(
									message=f'Failed to validate structured output: {str(e)}',
									model=self.name,
								) from e

					# If no tool use found but output_format was requested
					raise ModelProviderError(
						message='Expected structured output but no tool use found in response',
						model=self.name,
					)

			# If no valid content found
			if output_format is None:
				return ChatInvokeCompletion(
					completion='',
					usage=usage,
				)
			else:
				raise ModelProviderError(
					message='No valid content found in response',
					model=self.name,
				)

		except ClientError as e:
			error_code = e.response.get('Error', {}).get('Code', 'Unknown')
			error_message = e.response.get('Error', {}).get('Message', str(e))

			if error_code in ['ThrottlingException', 'TooManyRequestsException']:
				raise ModelRateLimitError(message=error_message, model=self.name) from e
			else:
				raise ModelProviderError(message=error_message, model=self.name) from e
		except Exception as e:
			raise ModelProviderError(message=str(e), model=self.name) from e
