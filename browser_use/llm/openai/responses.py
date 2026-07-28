"""Shared request and response handling for the OpenAI Responses API."""

from typing import Any, TypeVar

from openai.types.responses import Response
from pydantic import BaseModel, ValidationError

from browser_use.llm.exceptions import ModelOutputTruncatedError, ModelProviderError, ModelRateLimitError
from browser_use.llm.messages import BaseMessage
from browser_use.llm.openai.responses_serializer import ResponsesAPIMessageSerializer
from browser_use.llm.schema import SchemaOptimizer
from browser_use.llm.views import ChatInvokeCompletion, ChatInvokeUsage

T = TypeVar('T', bound=BaseModel)


def build_responses_request(
	*,
	model: str,
	messages: list[BaseMessage],
	output_format: type[BaseModel] | None,
	temperature: float | None,
	max_output_tokens: int | None,
	top_p: float | None,
	service_tier: str | None,
	reasoning_effort: str | None,
	is_reasoning_model: bool,
	add_schema_to_system_prompt: bool,
	dont_force_structured_output: bool,
	remove_min_items_from_schema: bool,
	remove_defaults_from_schema: bool,
) -> dict[str, Any]:
	"""Build a transport-neutral Responses API request body."""
	input_messages = ResponsesAPIMessageSerializer.serialize_messages(messages)
	request: dict[str, Any] = {'model': model, 'input': input_messages}

	if temperature is not None:
		request['temperature'] = temperature
	if max_output_tokens is not None:
		request['max_output_tokens'] = max_output_tokens
	if top_p is not None:
		request['top_p'] = top_p
	if service_tier is not None:
		request['service_tier'] = service_tier
	if is_reasoning_model and reasoning_effort is not None:
		request['reasoning'] = {'effort': reasoning_effort}
		request.pop('temperature', None)

	if output_format is not None:
		json_schema = SchemaOptimizer.create_optimized_json_schema(
			output_format,
			remove_min_items=remove_min_items_from_schema,
			remove_defaults=remove_defaults_from_schema,
		)
		if not dont_force_structured_output:
			request['text'] = {
				'format': {
					'type': 'json_schema',
					'name': 'agent_output',
					'strict': True,
					'schema': json_schema,
				}
			}

		if add_schema_to_system_prompt and input_messages and input_messages[0].get('role') == 'system':
			schema_text = f'\n<json_schema>\n{json_schema}\n</json_schema>'
			content = input_messages[0].get('content', '')
			if isinstance(content, str):
				input_messages[0]['content'] = content + schema_text
			elif isinstance(content, list):
				input_messages[0]['content'] = list(content) + [{'type': 'input_text', 'text': schema_text}]

	return request


def get_responses_usage(response: Response) -> ChatInvokeUsage | None:
	"""Convert Responses API usage into Browser Use usage accounting."""
	if response.usage is None:
		return None

	cached_tokens = None
	if response.usage.input_tokens_details is not None:
		cached_tokens = getattr(response.usage.input_tokens_details, 'cached_tokens', None)

	return ChatInvokeUsage(
		prompt_tokens=response.usage.input_tokens,
		prompt_cached_tokens=cached_tokens,
		prompt_cache_creation_tokens=None,
		prompt_image_tokens=None,
		completion_tokens=response.usage.output_tokens,
		total_tokens=response.usage.total_tokens,
	)


def parse_responses_completion(
	response: Response,
	output_format: type[T] | None,
	*,
	model: str,
	max_output_tokens: int | None,
) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
	"""Validate a terminal Response and convert it to the common completion type."""
	if response.status == 'failed':
		error = response.error
		message = error.message if error is not None else 'OpenAI Responses API request failed'
		if error is not None and error.code in {'rate_limit_exceeded', 'rate_limit_error'}:
			raise ModelRateLimitError(message=message, model=model)
		raise ModelProviderError(message=message, status_code=502, model=model)

	if response.status == 'incomplete':
		reason = response.incomplete_details.reason if response.incomplete_details is not None else None
		if reason == 'max_output_tokens':
			cap = f'max_output_tokens={max_output_tokens}' if max_output_tokens is not None else "the model's output token limit"
			raise ModelOutputTruncatedError(
				message=f'Model output was truncated at {cap}; the response is incomplete.',
				model=model,
			)
		raise ModelProviderError(
			message=f'OpenAI Responses API returned an incomplete response (reason={reason or "unknown"})',
			status_code=502,
			model=model,
		)
	if response.status != 'completed':
		raise ModelProviderError(
			message=f'OpenAI Responses API returned unexpected status: {response.status or "unknown"}',
			status_code=502,
			model=model,
		)

	usage = get_responses_usage(response)
	if output_format is None:
		return ChatInvokeCompletion(
			completion=response.output_text or '',
			usage=usage,
			stop_reason=response.status,
		)

	if not response.output_text:
		raise ModelProviderError(
			message='Failed to parse structured output from model response',
			status_code=500,
			model=model,
		)

	try:
		completion = output_format.model_validate_json(response.output_text)
	except ValidationError as exc:
		raise ModelProviderError(
			message=str(exc),
			status_code=500,
			model=model,
		) from exc

	return ChatInvokeCompletion(
		completion=completion,
		usage=usage,
		stop_reason=response.status,
	)
