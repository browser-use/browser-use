"""
Integration tests for the interpret_audio action.

Tests audio extraction and transcription from real web pages.
"""

import os

import pytest

from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.tools.service import Tools


@pytest.fixture
async def browser_session():
	"""Create and provide a Browser instance with security disabled."""
	browser_session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=True,
		)
	)
	await browser_session.start()
	yield browser_session
	await browser_session.kill()


@pytest.fixture
def skip_if_no_openai_key():
	"""Skip test if OPENAI_API_KEY is not set."""
	if not os.getenv('OPENAI_API_KEY'):
		pytest.skip('OPENAI_API_KEY not set - skipping audio transcription test')


class TestInterpretAudio:
	"""Integration tests for audio interpretation using real websites."""

	@pytest.mark.asyncio
	async def test_archive_org_audio_extraction(self, browser_session, skip_if_no_openai_key):
		"""
		Test audio extraction and transcription from archive.org.

		Uses: https://archive.org/details/testmp3testfile
		This is a small test MP3 file hosted on archive.org.
		"""
		from browser_use.llm import ChatOpenAI

		# Navigate to the archive.org test audio page
		page = await browser_session.get_current_page()
		await page.goto('https://archive.org/details/testmp3testfile')

		# Give page a moment to load
		import asyncio

		await asyncio.sleep(2)

		# Create tools instance
		llm = ChatOpenAI(model='gpt-4o')
		tools = Tools()

		# Execute interpret_audio action (index=None will search for audio on the page)
		result = await tools.interpret_audio(
			index=None, summarize=False, browser_session=browser_session, page_extraction_llm=llm
		)

		# Verify the result
		assert result.error is None, f'Audio interpretation failed: {result.error}'
		assert result.extracted_content is not None, 'No transcription content returned'
		assert len(result.extracted_content) > 0, 'Transcription is empty'

		# The test MP3 should contain some audio content
		# We can't predict exact transcription, but it should have something
		print(f'✅ Transcription successful: {result.extracted_content[:200]}...')

	@pytest.mark.asyncio
	async def test_interpret_audio_api_key_validation(self, browser_session):
		"""Test that interpret_audio validates OpenAI API key before attempting transcription."""

		# Temporarily remove the API key
		original_key = os.environ.pop('OPENAI_API_KEY', None)

		try:
			# Navigate to a page with audio
			page = await browser_session.get_current_page()
			await page.goto('https://archive.org/details/testmp3testfile')

			# Give page a moment to load
			import asyncio

			await asyncio.sleep(2)

			# Create tool service with a non-OpenAI LLM to force API key check
			from unittest.mock import AsyncMock

			from browser_use.llm import BaseChatModel

			mock_llm = AsyncMock(spec=BaseChatModel)
			mock_llm.model = 'mock-llm'
			mock_llm.provider = 'mock'

			tools = Tools()

			# Execute interpret_audio - should fail with API key error
			result = await tools.interpret_audio(
				index=None, summarize=False, browser_session=browser_session, page_extraction_llm=mock_llm
			)

			# Verify it failed with the correct error message
			assert result.error is not None, 'Should have error message'
			assert 'OPENAI_API_KEY' in result.error, f'Error message should mention API key: {result.error}'
			assert result.extracted_content is None, 'Should not have extracted content on failure'

		finally:
			# Restore the API key
			if original_key:
				os.environ['OPENAI_API_KEY'] = original_key

	@pytest.mark.asyncio
	async def test_interpret_audio_element_not_found(self, browser_session, skip_if_no_openai_key):
		"""Test that interpret_audio handles missing audio elements gracefully."""
		from browser_use.llm import ChatOpenAI

		# Navigate to a page without audio
		page = await browser_session.get_current_page()
		await page.goto('https://example.com')

		# Create tools instance
		llm = ChatOpenAI(model='gpt-4o')
		tools = Tools()

		# Try to interpret audio that doesn't exist
		result = await tools.interpret_audio(
			index=None, summarize=False, browser_session=browser_session, page_extraction_llm=llm
		)

		# Verify it failed gracefully
		assert result.error is not None, 'Should have error message'
		assert 'No audio' in result.error or 'not found' in result.error.lower(), (
			f'Error should mention missing audio: {result.error}'
		)
		assert result.extracted_content is None, 'Should not have extracted content when no audio found'

	@pytest.mark.asyncio
	async def test_interpret_audio_registry(self):
		"""Test that interpret_audio is registered in the tools registry."""
		from browser_use.tools.service import Tools

		tools = Tools()

		# Check that interpret_audio is registered
		assert 'interpret_audio' in tools.registry.registry.actions, 'interpret_audio should be registered in tools registry'

		# Get the action info
		action_info = tools.registry.registry.actions['interpret_audio']

		# Verify it has the expected fields (it's a RegisteredAction object)
		assert hasattr(action_info, 'description'), 'interpret_audio should have description'
		assert hasattr(action_info, 'param_model'), 'interpret_audio should have param_model'
		assert action_info.description, 'Description should not be empty'

		# Check the parameter model
		param_model = action_info.param_model
		assert hasattr(param_model, 'model_fields'), 'param_model should be a Pydantic model'

		# Verify expected parameters
		fields = param_model.model_fields
		assert 'index' in fields, 'Should have index parameter'
		assert 'summarize' in fields, 'Should have summarize parameter'
