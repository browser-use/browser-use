"""
Test retry logic with exponential backoff for LLM clients.
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


class TestChatBrowserUseRetries:
	"""Test retry logic for ChatBrowserUse."""

	@pytest.fixture
	def mock_env(self, monkeypatch):
		"""Set up environment for ChatBrowserUse."""
		monkeypatch.setenv('BROWSER_USE_API_KEY', 'test-api-key')

	@pytest.mark.asyncio
	async def test_retries_on_503_with_exponential_backoff(self, mock_env):
		"""Test that 503 errors trigger retries with exponential backoff."""
		from browser_use.llm.browser_use.chat import ChatBrowserUse
		from browser_use.llm.messages import UserMessage

		# Track timing of each attempt
		attempt_times: list[float] = []
		attempt_count = 0

		async def mock_post(*args, **kwargs):
			nonlocal attempt_count
			attempt_times.append(time.monotonic())
			attempt_count += 1

			if attempt_count < 3:
				# First 2 attempts fail with 503
				response = MagicMock()
				response.status_code = 503
				response.json.return_value = {'detail': 'Service temporarily unavailable'}
				raise httpx.HTTPStatusError('503', request=MagicMock(), response=response)
			else:
				# Third attempt succeeds
				response = MagicMock()
				response.json.return_value = {
					'completion': 'Success!',
					'usage': {
						'prompt_tokens': 10,
						'completion_tokens': 5,
						'total_tokens': 15,
						'prompt_cached_tokens': None,
						'prompt_cache_creation_tokens': None,
						'prompt_image_tokens': None,
					},
				}
				response.raise_for_status = MagicMock()
				return response

		with patch('httpx.AsyncClient') as mock_client_class:
			mock_client = AsyncMock()
			mock_client.post = mock_post
			mock_client.__aenter__ = AsyncMock(return_value=mock_client)
			mock_client.__aexit__ = AsyncMock(return_value=None)
			mock_client_class.return_value = mock_client

			# Use short delays for testing
			client = ChatBrowserUse(retry_base_delay=0.1, retry_max_delay=1.0)
			result = await client.ainvoke([UserMessage(content='test')])

		# Should have made 3 attempts
		assert attempt_count == 3
		assert result.completion == 'Success!'

		# Verify exponential backoff timing (with some tolerance for test execution)
		# First retry: ~0.1s, Second retry: ~0.2s
		delay_1 = attempt_times[1] - attempt_times[0]
		delay_2 = attempt_times[2] - attempt_times[1]

		# Allow 50% tolerance for timing
		assert 0.05 <= delay_1 <= 0.2, f'First delay {delay_1:.3f}s not in expected range'
		assert 0.1 <= delay_2 <= 0.4, f'Second delay {delay_2:.3f}s not in expected range'
		# Second delay should be roughly 2x the first (exponential)
		assert delay_2 > delay_1, 'Second delay should be longer than first (exponential backoff)'

	@pytest.mark.asyncio
	async def test_no_retry_on_401(self, mock_env):
		"""Test that 401 errors do NOT trigger retries."""
		from browser_use.llm.browser_use.chat import ChatBrowserUse
		from browser_use.llm.messages import UserMessage

		attempt_count = 0

		async def mock_post(*args, **kwargs):
			nonlocal attempt_count
			attempt_count += 1
			response = MagicMock()
			response.status_code = 401
			response.json.return_value = {'detail': 'Invalid API key'}
			raise httpx.HTTPStatusError('401', request=MagicMock(), response=response)

		with patch('httpx.AsyncClient') as mock_client_class:
			mock_client = AsyncMock()
			mock_client.post = mock_post
			mock_client.__aenter__ = AsyncMock(return_value=mock_client)
			mock_client.__aexit__ = AsyncMock(return_value=None)
			mock_client_class.return_value = mock_client

			client = ChatBrowserUse(retry_base_delay=0.01)

			with pytest.raises(ValueError, match='Invalid API key'):
				await client.ainvoke([UserMessage(content='test')])

		# Should only attempt once (no retries for 401)
		assert attempt_count == 1

	@pytest.mark.asyncio
	async def test_retries_on_timeout(self, mock_env):
		"""Test that timeouts trigger retries."""
		from browser_use.llm.browser_use.chat import ChatBrowserUse
		from browser_use.llm.messages import UserMessage

		attempt_count = 0

		async def mock_post(*args, **kwargs):
			nonlocal attempt_count
			attempt_count += 1
			if attempt_count < 2:
				raise httpx.TimeoutException('Request timed out')
			# Second attempt succeeds (with no usage data to test None handling)
			response = MagicMock()
			response.json.return_value = {'completion': 'Success after timeout!', 'usage': None}
			response.raise_for_status = MagicMock()
			return response

		with patch('httpx.AsyncClient') as mock_client_class:
			mock_client = AsyncMock()
			mock_client.post = mock_post
			mock_client.__aenter__ = AsyncMock(return_value=mock_client)
			mock_client.__aexit__ = AsyncMock(return_value=None)
			mock_client_class.return_value = mock_client

			client = ChatBrowserUse(retry_base_delay=0.01)
			result = await client.ainvoke([UserMessage(content='test')])

		assert attempt_count == 2
		assert result.completion == 'Success after timeout!'

	@pytest.mark.asyncio
	async def test_max_retries_exhausted(self, mock_env):
		"""Test that error is raised after max retries exhausted."""
		from browser_use.llm.browser_use.chat import ChatBrowserUse
		from browser_use.llm.messages import UserMessage

		attempt_count = 0

		async def mock_post(*args, **kwargs):
			nonlocal attempt_count
			attempt_count += 1
			response = MagicMock()
			response.status_code = 503
			response.json.return_value = {'detail': 'Service unavailable'}
			raise httpx.HTTPStatusError('503', request=MagicMock(), response=response)

		with patch('httpx.AsyncClient') as mock_client_class:
			mock_client = AsyncMock()
			mock_client.post = mock_post
			mock_client.__aenter__ = AsyncMock(return_value=mock_client)
			mock_client.__aexit__ = AsyncMock(return_value=None)
			mock_client_class.return_value = mock_client

			client = ChatBrowserUse(max_retries=3, retry_base_delay=0.01)

			with pytest.raises(ValueError, match='API request failed'):
				await client.ainvoke([UserMessage(content='test')])

		# Should have attempted max_retries times
		assert attempt_count == 3


class TestChatGoogleRetries:
	"""Test retry logic for ChatGoogle."""

	@pytest.fixture
	def mock_env(self, monkeypatch):
		"""Set up environment for ChatGoogle."""
		monkeypatch.setenv('GOOGLE_API_KEY', 'test-api-key')

	@pytest.mark.asyncio
	async def test_retries_on_503_with_exponential_backoff(self, mock_env):
		"""Test that 503 errors trigger retries with exponential backoff."""
		from browser_use.llm.exceptions import ModelProviderError
		from browser_use.llm.google.chat import ChatGoogle
		from browser_use.llm.messages import UserMessage

		attempt_times: list[float] = []
		attempt_count = 0

		# Mock the genai client
		with patch('browser_use.llm.google.chat.genai') as mock_genai:
			mock_client = MagicMock()
			mock_genai.Client.return_value = mock_client

			async def mock_generate(*args, **kwargs):
				nonlocal attempt_count
				attempt_times.append(time.monotonic())
				attempt_count += 1

				if attempt_count < 3:
					raise ModelProviderError(message='Service unavailable', status_code=503, model='gemini-2.0-flash')
				else:
					# Success on third attempt
					mock_response = MagicMock()
					mock_response.text = 'Success!'
					mock_response.usage_metadata = MagicMock(
						prompt_token_count=10, candidates_token_count=5, total_token_count=15, cached_content_token_count=0
					)
					mock_response.candidates = [MagicMock(content=MagicMock(parts=[MagicMock(text='Success!')]))]
					return mock_response

			# Mock the aio.models.generate_content path
			mock_client.aio.models.generate_content = mock_generate

			client = ChatGoogle(model='gemini-2.0-flash', api_key='test', retry_base_delay=0.1, retry_max_delay=1.0)
			result = await client.ainvoke([UserMessage(content='test')])

		assert attempt_count == 3
		assert result.completion == 'Success!'

		# Verify exponential backoff
		delay_1 = attempt_times[1] - attempt_times[0]
		delay_2 = attempt_times[2] - attempt_times[1]

		assert 0.05 <= delay_1 <= 0.2, f'First delay {delay_1:.3f}s not in expected range'
		assert 0.1 <= delay_2 <= 0.4, f'Second delay {delay_2:.3f}s not in expected range'
		assert delay_2 > delay_1, 'Second delay should be longer than first'

	@pytest.mark.asyncio
	async def test_no_retry_on_400(self, mock_env):
		"""Test that 400 errors do NOT trigger retries."""
		from browser_use.llm.exceptions import ModelProviderError
		from browser_use.llm.google.chat import ChatGoogle
		from browser_use.llm.messages import UserMessage

		attempt_count = 0

		with patch('browser_use.llm.google.chat.genai') as mock_genai:
			mock_client = MagicMock()
			mock_genai.Client.return_value = mock_client

			async def mock_generate(*args, **kwargs):
				nonlocal attempt_count
				attempt_count += 1
				raise ModelProviderError(message='Bad request', status_code=400, model='gemini-2.0-flash')

			mock_client.aio.models.generate_content = mock_generate

			client = ChatGoogle(model='gemini-2.0-flash', api_key='test', retry_base_delay=0.01)

			with pytest.raises(ModelProviderError):
				await client.ainvoke([UserMessage(content='test')])

		# Should only attempt once (400 is not retryable)
		assert attempt_count == 1

	@pytest.mark.asyncio
	async def test_retries_on_429_rate_limit(self, mock_env):
		"""Test that 429 rate limit errors trigger retries."""
		from browser_use.llm.exceptions import ModelProviderError
		from browser_use.llm.google.chat import ChatGoogle
		from browser_use.llm.messages import UserMessage

		attempt_count = 0

		with patch('browser_use.llm.google.chat.genai') as mock_genai:
			mock_client = MagicMock()
			mock_genai.Client.return_value = mock_client

			async def mock_generate(*args, **kwargs):
				nonlocal attempt_count
				attempt_count += 1

				if attempt_count < 2:
					raise ModelProviderError(message='Rate limit exceeded', status_code=429, model='gemini-2.0-flash')
				else:
					mock_response = MagicMock()
					mock_response.text = 'Success after rate limit!'
					mock_response.usage_metadata = MagicMock(
						prompt_token_count=10, candidates_token_count=5, total_token_count=15, cached_content_token_count=0
					)
					mock_response.candidates = [MagicMock(content=MagicMock(parts=[MagicMock(text='Success after rate limit!')]))]
					return mock_response

			mock_client.aio.models.generate_content = mock_generate

			client = ChatGoogle(model='gemini-2.0-flash', api_key='test', retry_base_delay=0.01)
			result = await client.ainvoke([UserMessage(content='test')])

		assert attempt_count == 2
		assert result.completion == 'Success after rate limit!'


if __name__ == '__main__':
	pytest.main([__file__, '-v'])
