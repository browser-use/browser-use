import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass
from threading import Thread
from typing import Any, Literal, get_args

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

logger = logging.getLogger(__name__)

FRANCE_CAPITAL_QUESTION = 'What is the capital of France? Respond with just the city name in lowercase.'
FRANCE_CAPITAL_EXPECTED_ANSWER = 'paris'

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
		capabilities.passed_iq_test = _test_basic_iq(llm)
		if not capabilities.passed_iq_test:
			raise LLMCapabilityError('LLM Failed Basic IQ Test')
		capabilities.response_time = int((time.time() - start_time) * 1000)

		capabilities.supported_tool_calling_method = _get_supported_tool_calling_method(llm, tool_calling_method)
		capabilities.success = True

		capabilities.supports_image_input = _test_vision_support(llm)
		capabilities.supports_multiple_human_msgs = _test_multiple_human_msgs(llm)
		logger.info('✅ LLM Capability Assessment Completed Successfully')
	except LLMCapabilityError as e:
		error = str(e)
		logger.error(f'❌ {error}')
		capabilities.error = error
	except Exception as e:
		error = str(e)
		logger.error(f'💥 Unexpected Error Ruring Capability Assessment: {error}')
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

	class FranceCapitalResponse(BaseModel):
		answer: str

	try:
		structured_llm = llm.with_structured_output(FranceCapitalResponse, include_raw=True, method=method)

		response = structured_llm.invoke([HumanMessage(content=FRANCE_CAPITAL_QUESTION)])

		if not response:
			return False

		parsed_response = _extract_parsed_response(response)

		if not isinstance(parsed_response, FranceCapitalResponse):
			return False

		if not parsed_response.answer or FRANCE_CAPITAL_EXPECTED_ANSWER not in parsed_response.answer.lower():
			return False

		return True

	except Exception as e:
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
			return False

		return True

	except (json.JSONDecodeError, AttributeError, TypeError) as e:
		return False


def _extract_parsed_response(response: Any) -> Any | None:
	"""Extracts the parsed response from the LLM response."""
	if isinstance(response, dict):
		return response.get('parsed')
	return getattr(response, 'parsed', None)


def _get_supported_tool_calling_method(llm: BaseChatModel, preferred: ToolCallingMethod | None) -> ToolCallingMethod | None:
	"""Determines the supported tool calling method for the LLM."""
	methods = []
	if preferred:
		methods.append(preferred)

	for method in get_args(ToolCallingMethod):
		if method not in methods:
			methods.append(method)

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
				return method
	except Exception as e:
		for method in methods:
			if _test_tool_calling_method(method):
				return method

	return None


def _test_vision_support(llm: BaseChatModel) -> bool:
	"""Tests if the LLM supports vision by asking it."""
	try:
		messages = [HumanMessage(content='Do you support vision? Respond with "yes" or "no".')]

		response = llm.invoke(messages)

		if response and hasattr(response, 'content') and 'yes' in response.content.lower():
			return True
		else:
			return False
	except Exception as e:
		print(e)
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
