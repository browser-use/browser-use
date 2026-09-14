"""
Simplified tests for URL shortening functionality in Agent service.

Four focused areas:
1. Input message processing with URL shortening
2. Output processing with custom actions and URL restoration
3. End-to-end pipeline test
4. Restoration surviving a second LLM call over the same, already shortened messages
"""

import json
from typing import cast
from unittest.mock import AsyncMock

import pytest

from browser_use.agent.service import Agent
from browser_use.agent.views import AgentOutput
from browser_use.llm.base import BaseChatModel
from browser_use.llm.exceptions import ModelRateLimitError
from browser_use.llm.messages import AssistantMessage, BaseMessage, UserMessage

# Super long URL to reuse across tests - much longer than the 25 character limit
# Includes both query params (?...) and fragment params (#...)
SUPER_LONG_URL = 'https://documentation.example-company.com/api/v3/enterprise/user-management/endpoints/administration/create-new-user-account-with-permissions/advanced-settings?format=detailed-json&version=3.2.1&timestamp=1699123456789&session_id=abc123def456ghi789&authentication_token=very_long_authentication_token_string_here&include_metadata=true&expand_relationships=user_groups,permissions,roles&sort_by=created_at&order=desc&page_size=100&include_deprecated_fields=false&api_key=super_long_api_key_that_exceeds_normal_limits#section=user_management&tab=advanced&view=detailed&scroll_to=permissions_table&highlight=admin_settings&filter=active_users&expand_all=true&debug_mode=enabled'


@pytest.fixture
def agent():
	"""Create an agent instance for testing URL shortening functionality."""
	from tests.ci.conftest import create_mock_llm

	return Agent(task='Test URL shortening', llm=create_mock_llm(), url_shortening_limit=25)


class TestUrlShorteningInputProcessing:
	"""Test URL shortening for input messages."""

	def test_process_input_messages_with_url_shortening(self, agent: Agent):
		"""Test that long URLs in input messages are shortened and mappings stored."""
		original_content = f'Please visit {SUPER_LONG_URL} and extract information'

		messages: list[BaseMessage] = [UserMessage(content=original_content)]

		# Process messages (modifies messages in-place and returns URL mappings)
		url_mappings = agent._process_messsages_and_replace_long_urls_shorter_ones(messages)

		# Verify URL was shortened in the message (modified in-place)
		processed_content = messages[0].content or ''
		assert processed_content != original_content
		assert 'https://documentation.example-company.com' in processed_content
		assert len(processed_content) < len(original_content)

		# Verify URL mapping was returned
		assert len(url_mappings) == 1
		shortened_url = next(iter(url_mappings.keys()))
		assert url_mappings[shortened_url] == SUPER_LONG_URL

	def test_process_user_and_assistant_messages_with_url_shortening(self, agent: Agent):
		"""Test URL shortening in both UserMessage and AssistantMessage."""
		user_content = f'I need to access {SUPER_LONG_URL} for the API documentation'
		assistant_content = f'I will help you navigate to {SUPER_LONG_URL} to retrieve the documentation'

		messages: list[BaseMessage] = [UserMessage(content=user_content), AssistantMessage(content=assistant_content)]

		# Process messages (modifies messages in-place and returns URL mappings)
		url_mappings = agent._process_messsages_and_replace_long_urls_shorter_ones(messages)

		# Verify URL was shortened in both messages
		user_processed_content = messages[0].content or ''
		assistant_processed_content = messages[1].content or ''

		assert user_processed_content != user_content
		assert assistant_processed_content != assistant_content
		assert 'https://documentation.example-company.com' in user_processed_content
		assert 'https://documentation.example-company.com' in assistant_processed_content
		assert len(user_processed_content) < len(user_content)
		assert len(assistant_processed_content) < len(assistant_content)

		# Verify URL mapping was returned (should be same shortened URL for both occurrences)
		assert len(url_mappings) == 1
		shortened_url = next(iter(url_mappings.keys()))
		assert url_mappings[shortened_url] == SUPER_LONG_URL


class TestUrlShorteningOutputProcessing:
	"""Test URL restoration for output processing with custom actions."""

	def test_process_output_with_custom_actions_and_url_restoration(self, agent: Agent):
		"""Test that shortened URLs in AgentOutput with custom actions are restored."""
		# Set up URL mapping (simulating previous shortening)
		shortened_url: str = agent._replace_urls_in_text(SUPER_LONG_URL)[0]
		url_mappings = {shortened_url: SUPER_LONG_URL}

		# Create AgentOutput with shortened URLs using JSON parsing
		output_json = {
			'thinking': f'I need to navigate to {shortened_url} for documentation',
			'evaluation_previous_goal': 'Successfully processed the request',
			'memory': f'Found useful info at {shortened_url}',
			'next_goal': 'Complete the documentation review',
			'action': [{'navigate': {'url': shortened_url, 'new_tab': False}}],
		}

		# Create properly typed AgentOutput with custom actions
		tools = agent.tools
		ActionModel = tools.registry.create_action_model()
		AgentOutputWithActions = AgentOutput.type_with_custom_actions(ActionModel)
		agent_output = AgentOutputWithActions.model_validate_json(json.dumps(output_json))

		# Process the output to restore URLs (modifies agent_output in-place)
		agent._recursive_process_all_strings_inside_pydantic_model(agent_output, url_mappings)

		# Verify URLs were restored in all locations
		assert SUPER_LONG_URL in (agent_output.thinking or '')
		assert SUPER_LONG_URL in (agent_output.memory or '')
		action_data = agent_output.action[0].model_dump()
		assert action_data['navigate']['url'] == SUPER_LONG_URL


class TestUrlShorteningEndToEnd:
	"""Test complete URL shortening pipeline end-to-end."""

	def test_complete_url_shortening_pipeline(self, agent: Agent):
		"""Test the complete pipeline: input shortening -> processing -> output restoration."""

		# Step 1: Input processing with URL shortening
		original_content = f'Navigate to {SUPER_LONG_URL} and extract the API documentation'

		messages: list[BaseMessage] = [UserMessage(content=original_content)]

		url_mappings = agent._process_messsages_and_replace_long_urls_shorter_ones(messages)

		# Verify URL was shortened in input
		assert len(url_mappings) == 1
		shortened_url = next(iter(url_mappings.keys()))
		assert url_mappings[shortened_url] == SUPER_LONG_URL
		assert shortened_url in (messages[0].content or '')

		# Step 2: Simulate agent output with shortened URL
		output_json = {
			'thinking': f'I will navigate to {shortened_url} to get the documentation',
			'evaluation_previous_goal': 'Starting documentation extraction',
			'memory': f'Target URL: {shortened_url}',
			'next_goal': 'Extract API documentation',
			'action': [{'navigate': {'url': shortened_url, 'new_tab': True}}],
		}

		# Create AgentOutput with custom actions
		tools = agent.tools
		ActionModel = tools.registry.create_action_model()
		AgentOutputWithActions = AgentOutput.type_with_custom_actions(ActionModel)
		agent_output = AgentOutputWithActions.model_validate_json(json.dumps(output_json))

		# Step 3: Output processing with URL restoration (modifies agent_output in-place)
		agent._recursive_process_all_strings_inside_pydantic_model(agent_output, url_mappings)

		# Verify complete pipeline worked correctly
		assert SUPER_LONG_URL in (agent_output.thinking or '')
		assert SUPER_LONG_URL in (agent_output.memory or '')
		action_data = agent_output.action[0].model_dump()
		assert action_data['navigate']['url'] == SUPER_LONG_URL
		assert action_data['navigate']['new_tab'] is True

		# Verify original shortened content is no longer present
		assert shortened_url not in (agent_output.thinking or '')
		assert shortened_url not in (agent_output.memory or '')


class TestUrlShorteningAcrossRepeatedModelCalls:
	"""URL restoration must survive a second LLM call that re-sends the same, already shortened messages.

	get_model_output shortens the input messages in place. A second pass over them finds nothing
	left to shorten, so unless the mapping from the first pass is carried over there is nothing to
	restore the model's output with. Both production paths that re-send messages are driven here.
	"""

	@staticmethod
	def _navigate_response(url: str) -> str:
		return json.dumps(
			{
				'evaluation_previous_goal': 'Retried after an empty action',
				'memory': 'Target URL captured',
				'next_goal': 'Open the documentation',
				'action': [{'navigate': {'url': url, 'new_tab': False}}],
			}
		)

	EMPTY_ACTION_RESPONSE = json.dumps(
		{
			'evaluation_previous_goal': 'Thinking',
			'memory': 'Nothing yet',
			'next_goal': 'Decide what to do',
			'action': [],
		}
	)

	async def test_empty_action_retry_restores_urls_in_the_retried_output(self, agent: Agent):
		"""_get_model_output_with_retry re-sends input_messages plus a clarification after an empty action."""
		from tests.ci.conftest import create_mock_llm

		shortened_url: str = agent._replace_urls_in_text(SUPER_LONG_URL)[0]
		# First call: no action. Second call (the retry): the model echoes the shortened URL it was shown.
		agent.llm = create_mock_llm([self.EMPTY_ACTION_RESPONSE, self._navigate_response(shortened_url)])
		messages: list[BaseMessage] = [UserMessage(content=f'Navigate to {SUPER_LONG_URL}')]

		model_output = await agent._get_model_output_with_retry(messages)

		ainvoke = cast(AsyncMock, agent.llm.ainvoke)
		assert ainvoke.await_count == 2
		# The retry sent the already shortened text, not the original ...
		retry_messages = ainvoke.await_args_list[1].args[0]
		assert retry_messages[0].content == f'Navigate to {shortened_url}'
		# ... and the retried output was still restored to the original URL.
		assert model_output.action[0].model_dump(exclude_unset=True)['navigate']['url'] == SUPER_LONG_URL

	async def test_fallback_llm_retry_restores_urls_in_the_fallback_output(self, agent: Agent):
		"""get_model_output recurses on the same messages after switching to the fallback LLM."""
		from tests.ci.conftest import create_mock_llm

		shortened_url: str = agent._replace_urls_in_text(SUPER_LONG_URL)[0]

		primary = AsyncMock(spec=BaseChatModel)
		primary.model = primary.name = primary.model_name = 'primary-model'
		primary.provider = 'mock'
		primary._verified_api_keys = True
		primary.ainvoke.side_effect = ModelRateLimitError(message='Rate limit exceeded', status_code=429, model='primary-model')

		fallback = create_mock_llm([self._navigate_response(shortened_url)])
		agent.llm = agent._original_llm = primary
		agent._fallback_llm = fallback
		messages: list[BaseMessage] = [UserMessage(content=f'Navigate to {SUPER_LONG_URL}')]

		model_output = await agent.get_model_output(messages)

		assert agent.llm is fallback
		assert model_output.action[0].model_dump(exclude_unset=True)['navigate']['url'] == SUPER_LONG_URL

	async def test_independent_calls_do_not_share_a_mapping(self, agent: Agent):
		"""Each direct get_model_output call starts from an empty mapping; only an explicit hand-over carries one."""
		from tests.ci.conftest import create_mock_llm

		shortened_url: str = agent._replace_urls_in_text(SUPER_LONG_URL)[0]
		agent.llm = create_mock_llm([self._navigate_response(shortened_url), self._navigate_response(shortened_url)])

		first = await agent.get_model_output([UserMessage(content=f'Navigate to {SUPER_LONG_URL}')])
		assert first.action[0].model_dump(exclude_unset=True)['navigate']['url'] == SUPER_LONG_URL

		# A later, unrelated call never saw the long URL, so nothing carries over and the text stays as the model wrote it.
		second = await agent.get_model_output([UserMessage(content='Unrelated prompt')])
		assert second.action[0].model_dump(exclude_unset=True)['navigate']['url'] == shortened_url
