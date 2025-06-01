import asyncio
import json
import logging
import re
import time
from dataclasses import asdict, dataclass
from threading import Thread
from typing import Any, Literal, get_args

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

logger = logging.getLogger(__name__)

FRANCE_CAPITAL_QUESTION = 'What is the capital of France? Respond with just the city name in lowercase.'
FRANCE_CAPITAL_EXPECTED_ANSWER = 'paris'
SMALL_RED_IMAGE = 'data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEASABIAAD/4QAiRXhpZgAATU0AKgAAAAgAAQESAAMAAAABAAEAAAAAAAD/2wBDAAYEBQYFBAYGBQYHBwYIChAKCgkJChQODwwQFxQYGBcUFhYaHSUfGhsjHBYWICwgIyYnKSopGR8tMC0oMCUoKSj/2wBDAQcHBwoIChMKChMoGhYaKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCj/wAARCAACAAQDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDzOiiivlj95P/Z'

ToolCallingMethod = Literal['function_calling', 'tools', 'json_mode', 'raw']


class LLMCapabilityError(Exception):
	"""Custom LLM capability error."""

	pass


@dataclass
class LLMCapabilities:
	"""Dataclass to hold LLM capabilities."""

	success: bool
	response_time: int
	error: str | None
	passed_iq_test: bool
	supports_image_input: bool
	supported_tool_calling_method: ToolCallingMethod | None
	supports_multiple_human_msgs: bool

	def to_dict(self) -> dict[str, Any]:
		"""Converts the capabilities to a dictionary."""
		return asdict(self)

	def log(self) -> None:
		"""Logs the capabilities."""
		logger.info('LLM Capabilities: ')
		logger.info(f'  Success: {self.success}')
		logger.info(f'  Response Time: {self.response_time} ms')
		logger.info(f'  Error: {self.error if self.error else "None"}')
		logger.info(f'  Passed IQ Test: {self.passed_iq_test}')
		logger.info(f'  Supports Image Input: {self.supports_image_input}')
		logger.info(
			f'  Supported Tool Calling Method: {self.supported_tool_calling_method if self.supported_tool_calling_method else "None"}'
		)
		logger.info(f'  Supports Multiple Human Messages: {self.supports_multiple_human_msgs}')


def get_llm_capabilities(
	llm: BaseChatModel, tool_calling_method: ToolCallingMethod | None = None, use_cache: bool = True
) -> LLMCapabilities:
	"""Tests and returns the capabilities of the given LLM, caching it if needed."""
	if use_cache and hasattr(llm, '_capability_cache') and llm._capability_cache:
		return LLMCapabilities(**llm._capability_cache)

	logger.info('🔍 Starting LLM Capability Assessment')
	start_time = time.time()

	capabilities = LLMCapabilities(
		success=False,
		response_time=0,
		error=None,
		passed_iq_test=False,
		supports_image_input=False,
		supported_tool_calling_method=None,
		supports_multiple_human_msgs=False,
	)

	try:
		logger.info('🔍 Testing LLM Basic IQ')
		capabilities.passed_iq_test = _test_basic_iq(llm)
		if not capabilities.passed_iq_test:
			raise LLMCapabilityError('LLM Failed Basic IQ Test')
		capabilities.response_time = int((time.time() - start_time) * 1000)
		capabilities.success = True
		logger.info('✅ LLM Basic IQ Test Passed')

		logger.info('🔍 Testing LLM Tool Calling Method')
		capabilities.supported_tool_calling_method = _get_supported_tool_calling_method(llm, tool_calling_method)
		logger.info(
			f'✅ LLM Tool Calling Method Supported: {capabilities.supported_tool_calling_method if capabilities.supported_tool_calling_method else "None"}'
		)

		logger.info('🔍 Testing LLM Vision Support')
		capabilities.supports_image_input = _test_vision_support(llm)
		logger.info(f'✅ LLM Vision Support: {capabilities.supports_image_input}')

		logger.info('🔍 Testing LLM Multiple Human Messages Support')
		capabilities.supports_multiple_human_msgs = _test_multiple_human_msgs(llm)
		logger.info(f'✅ LLM Supports Multiple Human Messages: {capabilities.supports_multiple_human_msgs}')
		logger.info('✅ LLM Capability Assessment Completed Successfully')
	except LLMCapabilityError as e:
		logger.error(f'❌ {e}')
	except Exception as e:
		error = str(e)
		logger.error(f'💥 Unexpected Error During Capability Assessment: {error}')
		capabilities.error = error

	return _cache_and_return(llm, capabilities)


def _cache_and_return(
	llm: BaseChatModel,
	capabilities: LLMCapabilities,
) -> LLMCapabilities:
	"""Caches the capabilities to the LLM instance and returns them."""
	llm._capability_cache = capabilities.to_dict()
	return capabilities


def _test_basic_iq(llm: BaseChatModel) -> bool:
	"""Tests the LLM's basic IQ by asking a simple question."""
	try:
		response = llm.invoke([HumanMessage(content=FRANCE_CAPITAL_QUESTION)])

		if not response or not hasattr(response, 'content') or not response.content:
			return False

		answer = response.content.lower().strip(' .')

		if FRANCE_CAPITAL_EXPECTED_ANSWER not in answer:
			return False

		return True

	except Exception as e:
		logger.error(f'❌ Error During Basic IQ Test: {e}.')
		return False


def _test_tool_calling_method(llm: BaseChatModel, method: ToolCallingMethod) -> bool:
	"""Tests the LLM's tool calling method by asking a question and checking the response."""
	try:
		if method == 'raw':
			return _test_raw_json_method(llm)
		else:
			return _test_structured_output_method(llm, method)

	except Exception:
		return False


async def _test_tool_calling_method_async(llm, method: str) -> tuple[str, bool]:
	"""Asynchronously tests the LLM's tool calling method."""
	loop = asyncio.get_event_loop()
	result = await loop.run_in_executor(None, _test_tool_calling_method, llm, method)
	return (method, result)


def _test_raw_json_method(llm: BaseChatModel) -> bool:
	"""Tests the LLM's raw JSON response capability by asking a question."""
	prompt = f"""{FRANCE_CAPITAL_QUESTION}
        Respond with a JSON object like: {{"answer": "city_name_in_lowercase"}}"""

	response = llm.invoke([prompt])

	if not response or not hasattr(response, 'content') or not response.content:
		return False

	return _validate_raw_json_response(response.content, FRANCE_CAPITAL_EXPECTED_ANSWER)


def _test_structured_output_method(llm: BaseChatModel, method: ToolCallingMethod) -> bool:
	"""Tests the LLM's structured output capability by asking a question."""

	class CapitalResponse(BaseModel):
		answer: str

	try:
		structured_llm = llm.with_structured_output(CapitalResponse, include_raw=True, method=method)

		response = structured_llm.invoke([HumanMessage(content=FRANCE_CAPITAL_QUESTION)])

		if not response:
			logger.debug(f'🛠️  Tool calling method {method} failed: empty response')
			return False

		parsed_response = _extract_parsed_response(response)

		if not isinstance(parsed_response, CapitalResponse):
			logger.debug(f'️🛠️  Tool calling method {method} failed: LLM responded with invalid JSON')
			return False

		if FRANCE_CAPITAL_EXPECTED_ANSWER not in parsed_response.answer.lower():
			logger.debug(f'🛠️  Tool calling method {method} failed: LLM failed to answer test question correctly')
			return False

		return True

	except Exception as e:
		logger.debug(f"🛠️  Tool calling method '{method}' test failed: {type(e).__name__}: {str(e)}")
		return False


def _validate_raw_json_response(content: str, expected_answer: str) -> bool:
	"""Validates the raw JSON response from the LLM."""
	content = content.strip()

	if content.startswith('```json') and content.endswith('```'):
		content = content[7:-3].strip()
	elif content.startswith('```') and content.endswith('```'):
		content = content[3:-3].strip()

	try:
		result = json.loads(content)
		answer = str(result.get('answer', '')).strip().lower().strip(' .')

		if expected_answer not in answer:
			logger.debug(f"🛠️  Tool calling method 'raw' failed: expected '{expected_answer}', got '{answer}'")
			return False

		return True

	except (json.JSONDecodeError, AttributeError, TypeError) as e:
		logger.debug(f"🛠️  Tool calling method 'raw' failed: Failed to parse JSON content: {e}")
		return False


def _extract_parsed_response(response: Any) -> Any | None:
	"""Extracts the parsed response from the LLM response."""
	if isinstance(response, dict):
		return response.get('parsed')
	return getattr(response, 'parsed', None)


def _get_supported_tool_calling_method(llm: BaseChatModel, preferred: ToolCallingMethod | None) -> ToolCallingMethod | None:
	"""Determines the supported tool calling method for the LLM."""

	if preferred:
		if _test_tool_calling_method(llm, preferred):
			return preferred

	methods = []
	for method in get_args(ToolCallingMethod):
		if method != preferred:
			methods.append(method)

	start_time = time.time()
	try:

		async def test_all_methods():
			tasks = [_test_tool_calling_method_async(llm, method) for method in methods]
			results = await asyncio.gather(*tasks, return_exceptions=True)
			return results

		try:
			loop = asyncio.get_running_loop()
			result = {}

			def run_in_thread():
				new_loop = asyncio.new_event_loop()
				asyncio.set_event_loop(new_loop)
				try:
					result['value'] = new_loop.run_until_complete(test_all_methods())
				except Exception as e:
					result['error'] = e
				finally:
					new_loop.close()

			t = Thread(target=run_in_thread)
			t.start()
			t.join()
			if 'error' in result:
				raise result['error']
			results = result['value']
		except RuntimeError as e:
			if 'no running event loop' in str(e):
				results = asyncio.run(test_all_methods())
			else:
				raise

		for i, method in enumerate(methods):
			if isinstance(results[i], tuple) and results[i][1]:
				elapsed = time.time() - start_time
				logger.debug(f'🛠️  Tested LLM in parallel and chose tool calling method: [{method}] in {elapsed:.2f}s')
				return method
	except Exception as e:
		logger.debug(f'🛠️  Parallel testing failed: {e}, falling back to sequential')
		for method in methods:
			if _test_tool_calling_method(method):
				elapsed = time.time() - start_time
				logger.debug(f'🛠️  Tested LLM and chose tool calling method: [{method}] in {elapsed:.2f}s')
				return method

	return None


def _test_vision_support(llm: BaseChatModel) -> bool:
	"""Tests if the LLM supports vision by detecting inability indicators."""
	try:
		messages = [
			SystemMessage(content='You are a model that can see and analyze images.'),
			HumanMessage(
				content=[
					{
						'type': 'text',
						'text': 'Please analyze the image below and respond with just the color name in lowercase. If you cannot see the image, respond with "I cannot see the image."',
					},
					{'type': 'image_url', 'image_url': {'url': SMALL_RED_IMAGE}},
				]
			),
		]

		response = llm.invoke(messages)

		if not response or not hasattr(response, 'content'):
			return False

		content = response.content.lower()

		if len(content) > 200 or 'cannot see' in content:
			return False

		if re.search(r'\bred\b', content):
			return True

		return False

	except Exception as e:
		return False


def _test_multiple_human_msgs(llm: BaseChatModel) -> bool:
	"""Tests if the LLM supports multiple human messages in a row."""
	try:
		messages = [
			HumanMessage(content='Hello'),
			HumanMessage(content='How are you?'),
			HumanMessage(content='Please respond to my greeting.'),
		]

		response = llm.invoke(messages)

		if response and hasattr(response, 'content') and response.content:
			return True
		else:
			return False

	except Exception as e:
		return False
