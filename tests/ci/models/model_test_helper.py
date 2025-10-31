"""Shared test helper for LLM model tests."""

import os

import pytest

from browser_use.agent.service import Agent
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession


async def run_model_button_click_test(
	model_class,
	model_name: str,
	api_key_env: str | None,
	extra_kwargs: dict,
	httpserver,
):
	"""Test that an LLM model can click a button.

	This test verifies:
	1. Model can be initialized with API key
	2. Agent can navigate and click a button
	3. Button click is verified by checking page state change
	4. Completes within max 2 steps
	"""
	# Handle API key validation - skip test if not available
	if api_key_env is not None:
		api_key = os.getenv(api_key_env)
		if not api_key:
			pytest.skip(f'{api_key_env} not set - skipping test')
	else:
		api_key = None

	# Handle Azure-specific endpoint validation
	from browser_use.llm.azure.chat import ChatAzureOpenAI

	if model_class is ChatAzureOpenAI:
		azure_endpoint = os.getenv('AZURE_OPENAI_ENDPOINT')
		if not azure_endpoint:
			pytest.skip('AZURE_OPENAI_ENDPOINT not set - skipping test')
		# Add the azure_endpoint to extra_kwargs
		extra_kwargs = {**extra_kwargs, 'azure_endpoint': azure_endpoint}

	# Create HTML page with a button that changes page content when clicked
	html = """
	<!DOCTYPE html>
	<html>
	<head><title>Button Test</title></head>
	<body>
		<h1>Button Click Test</h1>
		<button id="test-button" onclick="document.getElementById('result').innerText='SUCCESS'">
			Click Me
		</button>
		<div id="result">NOT_CLICKED</div>
	</body>
	</html>
	"""
	httpserver.expect_request('/').respond_with_data(html, content_type='text/html')

	# Create LLM instance with extra kwargs if provided
	llm_kwargs = {'model': model_name}
	if api_key is not None:
		llm_kwargs['api_key'] = api_key
	llm_kwargs.update(extra_kwargs)
	llm = model_class(**llm_kwargs)  # type: ignore[arg-type]

	# Create browser session
	browser = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,  # Use temporary directory
		)
	)

	try:
		# Start browser
		await browser.start()

		# Create agent with button click task (URL in task triggers auto-navigation)
		test_url = httpserver.url_for('/')
		agent = Agent(
			task=f'{test_url} - Click the button',
			llm=llm,
			browser_session=browser,
			max_steps=2,  # Max 2 steps as per requirements
		)

		# Run the agent
		result = await agent.run()

		# Verify task completed
		assert result is not None
		assert len(result.history) > 0

		# Verify button was clicked by checking page state across any step
		button_clicked = False
		for step in result.history:
			# Check state_message which contains browser state with page text
			if step.state_message and 'SUCCESS' in step.state_message:
				button_clicked = True
				break

		# Check if SUCCESS appears in any step (indicating button was clicked)
		assert button_clicked, 'Button was not clicked - SUCCESS not found in any page state'

	finally:
		# Clean up browser session
		await browser.kill()
