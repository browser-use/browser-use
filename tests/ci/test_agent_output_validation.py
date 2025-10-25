"""Test agent output validation feature"""
import asyncio

import pytest
from langchain_core.messages import AIMessage

from browser_use import Agent, BrowserProfile
from browser_use.agent.views import ActionResult, AgentOutput
from browser_use.llm.base import BaseLLMResponse
from tests.conftest import FakeLLM


@pytest.fixture
def browser_profile():
	"""Return a browser profile for testing"""
	return BrowserProfile(headless=True, disable_security=True, extra_chromium_args=['--no-sandbox'])


async def test_validation_when_output_unsatisfactory(setup_html_server, browser_profile):
	"""Test that validation triggers continuation when output is unsatisfactory"""
	
	# Set up test page
	server = setup_html_server
	html_content = """
	<html>
		<body>
			<h1>Test Page</h1>
			<p>Simple test content</p>
		</body>
	</html>
	"""
	server.expect_request('/test').respond_with_data(html_content, content_type='text/html')
	test_url = server.url_for('/test')
	
	# Track how many times LLM is called
	call_count = {'count': 0}
	validation_call_count = {'count': 0}
	
	async def fake_llm_output(messages, **kwargs):
		"""Generate fake LLM responses"""
		call_count['count'] += 1
		
		# Check if this is a validation call by looking at message content
		last_message = messages[-1].content if messages else ''
		if 'validating an AI agent' in str(last_message).lower():
			validation_call_count['count'] += 1
			# First validation: say user is NOT satisfied
			if validation_call_count['count'] == 1:
				return BaseLLMResponse(
					completion={
						'satisfied': False,
						'reason': 'The output is incomplete and missing key information'
					},
					raw_message=AIMessage(content='validation response'),
				)
			# Second validation after extra step: say satisfied
			else:
				return BaseLLMResponse(
					completion={
						'satisfied': True,
						'reason': 'The output now looks complete'
					},
					raw_message=AIMessage(content='validation response'),
				)
		
		# Regular agent steps
		if call_count['count'] == 1:
			# First step: navigate
			action = [{'navigate': {'url': test_url, 'new_tab': False}}]
		elif call_count['count'] == 2:
			# Second step: done with incomplete result
			action = [{'done': {'success': True, 'text': 'Incomplete result'}}]
		else:
			# Third step (after validation): done with complete result
			action = [{'done': {'success': True, 'text': 'Complete result with all details'}}]
		
		return BaseLLMResponse(
			completion=AgentOutput(
				evaluation_previous_goal='Making progress',
				memory='Working on task',
				next_goal='Complete the task',
				action=action,
			),
			raw_message=AIMessage(content='test response'),
		)
	
	# Create agent with fake LLM
	llm = FakeLLM(fake_llm_output)
	agent = Agent(
		task='Get information from the test page',
		llm=llm,
		browser_profile=browser_profile,
	)
	
	# Run agent with max 2 steps
	history = await agent.run(max_steps=2)
	
	# Verify validation was called
	assert validation_call_count['count'] >= 1, 'Validation should have been called at least once'
	
	# Verify that agent took more than 2 steps due to validation
	assert len(history.history) >= 2, 'Agent should have executed at least 2 steps'
	
	# Verify validation_attempted flag was set
	assert agent.state.validation_attempted is True, 'validation_attempted should be True'
	
	await agent.close()


async def test_validation_when_output_satisfactory(setup_html_server, browser_profile):
	"""Test that validation doesn't trigger continuation when output is good"""
	
	# Set up test page
	server = setup_html_server
	html_content = """
	<html>
		<body>
			<h1>Test Page</h1>
			<p>Simple test content</p>
		</body>
	</html>
	"""
	server.expect_request('/test').respond_with_data(html_content, content_type='text/html')
	test_url = server.url_for('/test')
	
	# Track how many times LLM is called
	call_count = {'count': 0}
	validation_call_count = {'count': 0}
	
	async def fake_llm_output(messages, **kwargs):
		"""Generate fake LLM responses"""
		call_count['count'] += 1
		
		# Check if this is a validation call
		last_message = messages[-1].content if messages else ''
		if 'validating an AI agent' in str(last_message).lower():
			validation_call_count['count'] += 1
			# Say user IS satisfied
			return BaseLLMResponse(
				completion={
					'satisfied': True,
					'reason': 'The output is complete and satisfactory'
				},
				raw_message=AIMessage(content='validation response'),
			)
		
		# Regular agent steps
		if call_count['count'] == 1:
			# First step: navigate
			action = [{'navigate': {'url': test_url, 'new_tab': False}}]
		else:
			# Second step: done with good result
			action = [{'done': {'success': True, 'text': 'Complete result with all the required details'}}]
		
		return BaseLLMResponse(
			completion=AgentOutput(
				evaluation_previous_goal='Making progress',
				memory='Working on task',
				next_goal='Complete the task',
				action=action,
			),
			raw_message=AIMessage(content='test response'),
		)
	
	# Create agent with fake LLM
	llm = FakeLLM(fake_llm_output)
	agent = Agent(
		task='Get information from the test page',
		llm=llm,
		browser_profile=browser_profile,
	)
	
	# Run agent with max 2 steps
	history = await agent.run(max_steps=2)
	
	# Verify validation was called
	assert validation_call_count['count'] == 1, 'Validation should have been called once'
	
	# Verify that agent took exactly 2 steps (no extra step from validation)
	assert len(history.history) == 2, 'Agent should have executed exactly 2 steps'
	
	# Verify validation_attempted flag was set
	assert agent.state.validation_attempted is True, 'validation_attempted should be True'
	
	await agent.close()


async def test_validation_not_triggered_on_failure(setup_html_server, browser_profile):
	"""Test that validation is skipped when agent reports failure"""
	
	# Set up test page
	server = setup_html_server
	html_content = """
	<html>
		<body>
			<h1>Test Page</h1>
		</body>
	</html>
	"""
	server.expect_request('/test').respond_with_data(html_content, content_type='text/html')
	test_url = server.url_for('/test')
	
	# Track how many times LLM is called
	call_count = {'count': 0}
	validation_call_count = {'count': 0}
	
	async def fake_llm_output(messages, **kwargs):
		"""Generate fake LLM responses"""
		call_count['count'] += 1
		
		# Check if this is a validation call
		last_message = messages[-1].content if messages else ''
		if 'validating an AI agent' in str(last_message).lower():
			validation_call_count['count'] += 1
			return BaseLLMResponse(
				completion={
					'satisfied': False,
					'reason': 'Should not be called'
				},
				raw_message=AIMessage(content='validation response'),
			)
		
		# Regular agent steps
		if call_count['count'] == 1:
			# First step: navigate
			action = [{'navigate': {'url': test_url, 'new_tab': False}}]
		else:
			# Second step: done with FAILURE
			action = [{'done': {'success': False, 'text': 'Task failed'}}]
		
		return BaseLLMResponse(
			completion=AgentOutput(
				evaluation_previous_goal='Making progress',
				memory='Working on task',
				next_goal='Complete the task',
				action=action,
			),
			raw_message=AIMessage(content='test response'),
		)
	
	# Create agent with fake LLM
	llm = FakeLLM(fake_llm_output)
	agent = Agent(
		task='Get information from the test page',
		llm=llm,
		browser_profile=browser_profile,
	)
	
	# Run agent
	history = await agent.run(max_steps=2)
	
	# Verify validation was NOT called (we skip validation on failure)
	assert validation_call_count['count'] == 0, 'Validation should not be called when agent reports failure'
	
	# Verify validation_attempted flag was set
	assert agent.state.validation_attempted is True, 'validation_attempted should be True'
	
	await agent.close()
