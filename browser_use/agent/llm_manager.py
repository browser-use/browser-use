# @file purpose: Manages LLM setup, including tool-calling detection and verification.
import asyncio
import json
import logging
import os
import time
from threading import Thread
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from browser_use.agent.message_manager.utils import is_model_without_tool_support

logger = logging.getLogger(__name__)

SKIP_LLM_API_KEY_VERIFICATION = os.environ.get('SKIP_LLM_API_KEY_VERIFICATION', 'false').lower().startswith(('t', 'y', '1'))


class LLMManager:
    def __init__(self, llm: BaseChatModel, agent_logger: logging.Logger, agent_settings):
        self.llm = llm
        self.logger = agent_logger
        self.settings = agent_settings
        self.model_name = self._get_model_name()
        self.chat_model_library = self.llm.__class__.__name__

    def _get_model_name(self) -> str:
        if hasattr(self.llm, 'model_name'):
            model = self.llm.model_name
            return model if model is not None else 'Unknown'
        if hasattr(self.llm, 'model'):
            model = self.llm.model
            return model if model is not None else 'Unknown'
        return 'Unknown'

    def verify_and_setup_llm(self) -> str:
        """
        Verify that the LLM API keys are setup and the LLM API is responding properly.
        Also handles tool calling method detection if in auto mode.
        """
        tool_calling_method = self._set_tool_calling_method()

        # Skip verification if already done
        if getattr(self.llm, '_verified_api_keys', None) is True or SKIP_LLM_API_KEY_VERIFICATION:
            setattr(self.llm, '_verified_api_keys', True)
            return tool_calling_method
        return tool_calling_method


    def _set_tool_calling_method(self) -> str | None:
        """Determine the best tool calling method to use with the current LLM."""
        if self.settings.tool_calling_method != 'auto':
            if not self._test_tool_calling_method(self.settings.tool_calling_method):
                if self.settings.tool_calling_method == 'raw':
                    raise ConnectionError('Failed to connect to LLM. Please check your API key and network connection.')
                else:
                    raise RuntimeError(
                        f"Configured tool calling method '{self.settings.tool_calling_method}' "
                        'is not supported by the current LLM.'
                    )
            setattr(self.llm, '_verified_tool_calling_method', self.settings.tool_calling_method)
            return self.settings.tool_calling_method

        if hasattr(self.llm, '_verified_tool_calling_method'):
            self.logger.debug(
                f'🛠️ Using cached tool calling method for {self.chat_model_library}/{self.model_name}: [{getattr(self.llm, "_verified_tool_calling_method")}]'
            )
            return getattr(self.llm, '_verified_tool_calling_method')

        known_method = self._get_known_tool_calling_method()
        if known_method is not None:
            if self._test_tool_calling_method(known_method):
                setattr(self.llm, '_verified_tool_calling_method', known_method)
                return known_method
            self.logger.debug(
                f'Known method {known_method} failed for {self.chat_model_library}/{self.model_name}, falling back to detection'
            )

        return self._detect_best_tool_calling_method()

    def _get_known_tool_calling_method(self) -> str | None:
        """Get known tool calling method for common model/library combinations."""
        model_lower = self.model_name.lower()
        if self.chat_model_library == 'ChatOpenAI':
            if any(m in model_lower for m in ['gpt-4', 'gpt-3.5']):
                return 'function_calling'
            if any(m in model_lower for m in ['llama']):
                return 'json_mode'
        elif self.chat_model_library == 'AzureChatOpenAI':
            return 'tools' if 'gpt-4-' in model_lower else 'function_calling'
        elif self.chat_model_library == 'ChatGoogleGenerativeAI':
            return None
        elif self.chat_model_library in ['ChatAnthropic', 'AnthropicChat']:
            if any(m in model_lower for m in ['claude-3', 'claude-2']):
                return 'tools'
        elif is_model_without_tool_support(self.model_name):
            return 'raw'
        return None

    def _detect_best_tool_calling_method(self) -> str:
        """Detect the best supported tool calling method by testing each one."""
        start_time = time.time()
        methods_to_try = ['function_calling', 'tools', 'json_mode', 'raw']

        async def test_all_methods():
            tasks = [self._test_tool_calling_method_async(method) for method in methods_to_try]
            return await asyncio.gather(*tasks, return_exceptions=True)

        try:
            loop = asyncio.get_running_loop()
            result = {}
            def run_in_thread():
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    result['value'] = new_loop.run_until_complete(test_all_methods())
                finally:
                    new_loop.close()
            t = Thread(target=run_in_thread)
            t.start()
            t.join()
            results = result.get('value', [])
        except RuntimeError:
            results = asyncio.run(test_all_methods())

        for i, method in enumerate(methods_to_try):
            if isinstance(results, list) and i < len(results):
                ith_result = results[i]
                if isinstance(ith_result, tuple) and ith_result[1]:
                    setattr(self.llm, '_verified_api_keys', True)
                    setattr(self.llm, '_verified_tool_calling_method', method)
                    elapsed = time.time() - start_time
                    self.logger.debug(f'🛠️ Tested LLM in parallel and chose tool calling method: [{method}] in {elapsed:.2f}s')
                    return method

        for method in methods_to_try:
            if self._test_tool_calling_method(method):
                setattr(self.llm, '_verified_api_keys', True)
                setattr(self.llm, '_verified_tool_calling_method', method)
                elapsed = time.time() - start_time
                self.logger.debug(f'🛠️ Tested LLM and chose tool calling method: [{method}] in {elapsed:.2f}s')
                return method

        raise ConnectionError('Failed to connect to LLM. Please check your API key and network connection.')

    async def _test_tool_calling_method_async(self, method: str) -> tuple[str, bool]:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, self._test_tool_calling_method, method)
        return (method, result)

    def _test_tool_calling_method(self, method: str | None) -> bool:
        """Test if a specific tool calling method works with the current LLM."""
        try:
            CAPITAL_QUESTION = 'What is the capital of France? Respond with just the city name in lowercase.'
            EXPECTED_ANSWER = 'paris'

            class CapitalResponse(BaseModel):
                answer: str

            def is_valid_raw_response(response, expected_answer: str) -> bool:
                content = getattr(response, 'content', '').strip()
                if content.startswith('```json') and content.endswith('```'):
                    content = content[7:-3].strip()
                elif content.startswith('```') and content.endswith('```'):
                    content = content[3:-3].strip()
                try:
                    result = json.loads(content)
                    answer = str(result.get('answer', '')).strip().lower().strip(' .')
                    if expected_answer.lower() not in answer:
                        self.logger.debug(f"🛠️ Tool calling method {method} failed: expected '{expected_answer}', got '{answer}'")
                        return False
                    return True
                except (json.JSONDecodeError, AttributeError, TypeError) as e:
                    self.logger.debug(f'🛠️ Tool calling method {method} failed: Failed to parse JSON content: {e}')
                    return False

            if method == 'raw' or method == 'json_mode':
                test_prompt = f'{CAPITAL_QUESTION}\nRespond with a json object like: {{"answer": "city_name_in_lowercase"}}'
                response = self.llm.invoke([test_prompt])
                if not response or not hasattr(response, 'content'):
                    return False
                return is_valid_raw_response(response, EXPECTED_ANSWER)
            else:
                structured_llm = self.llm.with_structured_output(CapitalResponse, include_raw=True, method=method)
                response = structured_llm.invoke([HumanMessage(content=CAPITAL_QUESTION)])

                if not response:
                    self.logger.debug(f'🛠️ Tool calling method {method} failed: empty response')
                    return False

                parsed = response.get('parsed') if isinstance(response, dict) else getattr(response, 'parsed', None)

                if not isinstance(parsed, CapitalResponse):
                    self.logger.debug(f'🛠️ Tool calling method {method} failed: LLM responded with invalid JSON')
                    return False

                if EXPECTED_ANSWER not in parsed.answer.lower():
                    self.logger.debug(f'🛠️ Tool calling method {method} failed: LLM failed to answer test question correctly')
                    return False
                return True
        except Exception as e:
            self.logger.debug(f"🛠️ Tool calling method '{method}' test failed: {type(e).__name__}: {str(e)}")
            return False 