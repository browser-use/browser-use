# test_granular_memory.py

import pytest
import pytest_asyncio  # Required for async fixtures
import uuid
from unittest.mock import AsyncMock, MagicMock

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.outputs import ChatGeneration, LLMResult
from langchain_core.messages import AIMessage

from browser_use.agent.memory.service import Memory
from browser_use.agent.memory.views import MemoryConfig, GranularMemoryEntry
from browser_use.agent.message_manager.service import MessageManager, MessageManagerSettings  # Assuming default config
from browser_use.controller.service import Controller
from browser_use.browser import BrowserSession  # For type hinting mock
from browser_use.agent.views import ActionResult
from browser_use.controller.views import SaveFactToMemoryAction, QueryLongTermMemoryAction


# --- Mocks & Fixtures ---


class MockChatModel(BaseChatModel):
	model_name: str = 'mock-chat-model-for-testing'  # Required by MemoryConfig/mem0

	def _generate(self, messages, stop=None, run_manager=None, **kwargs):
		# Required for synchronous calls if any; mem0 might use sync internally for some paths
		content = 'Mocked LLM response'
		message = AIMessage(content=content)
		generation = ChatGeneration(message=message)
		return LLMResult(generations=[[generation]])

	async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
		# Required for asynchronous calls
		content = 'Mocked async LLM response'
		message = AIMessage(content=content)
		generation = ChatGeneration(message=message)
		return LLMResult(generations=[[generation]])

	@property
	def _llm_type(self) -> str:
		return 'mock-chat-model'


@pytest.fixture(scope='session')  # Can be session-scoped if llm_instance is stateless
def mock_llm_instance():
	return MockChatModel()


@pytest_asyncio.fixture(scope='function')
async def mock_browser_session_fixture():
	session = AsyncMock(spec=BrowserSession)
	page_mock = AsyncMock()
	page_mock.url = 'https://example.com/default-testpage'
	session.get_current_page = AsyncMock(return_value=page_mock)
	return session


@pytest.fixture(scope='function')
def memory_config_instance(mock_llm_instance):
	# agent_id is unique per test function run for isolation.
	# granular_memory_collection_name is also unique to prevent test interference.
	agent_id = f'test_agent_{uuid.uuid4().hex[:6]}'
	collection_name = f'test_granular_coll_{uuid.uuid4().hex[:6]}'
	return MemoryConfig(
		agent_id=agent_id,
		embedder_provider='huggingface',
		embedder_model='sentence-transformers/all-MiniLM-L6-v2',  # Small, local, no API keys
		embedder_dims=384,
		vector_store_provider='faiss',
		llm_instance=mock_llm_instance,  # mem0 needs this for its config
		memory_interval=99,  # Effectively disable procedural memory summarization
		granular_memory_collection_name=collection_name,
	)


@pytest.fixture(scope='function')
def agent_memory_service_instance(memory_config_instance, mock_llm_instance):
	# MessageManager is a dependency for Memory
	mock_mm_state = MagicMock()
	mock_mm_state.history.messages = []

	mock_message_manager = MagicMock(spec=MessageManager)
	mock_message_manager.state = mock_mm_state
	mock_message_manager.settings = MessageManagerSettings()
	mock_message_manager._count_tokens = MagicMock(return_value=10)  # Mock token counting

	memory_service = Memory(message_manager=mock_message_manager, llm=mock_llm_instance, config=memory_config_instance)
	assert memory_service.granular_mem_store is not None, 'Granular memory store failed to initialize'
	return memory_service


@pytest.fixture(scope='function')
def controller_instance_for_mem_tests():
	# Controller registers memory actions by default.
	return Controller()


@pytest.fixture(scope='function')
def current_test_run_id():
	return f'test_run_{uuid.uuid4().hex[:6]}'


@pytest.fixture(scope='function')
def action_execution_context(
	agent_memory_service_instance, memory_config_instance, current_test_run_id, mock_browser_session_fixture
):
	return {
		'agent_memory': agent_memory_service_instance,
		'agent_id': memory_config_instance.agent_id,
		'agent_run_id': current_test_run_id,
		'browser_session': mock_browser_session_fixture,
	}


# --- Test Cases ---


@pytest.mark.asyncio
async def test_controller_save_fact_to_memory(
	controller_instance_for_mem_tests: Controller,
	action_execution_context: dict,
	memory_config_instance,  # For agent_id verification
):
	params_model = SaveFactToMemoryAction(
		fact_content='User prefers dark mode for UI.',
		fact_type='user_preference',
		source_url='https://example.com/settings',
		keywords=['ui', 'preference', 'dark_mode'],
		confidence=0.95,
	)
	# Get the dynamically generated ActionModel type from the controller instance
	DynamicActionModel = controller_instance_for_mem_tests.registry.create_action_model()
	# Construct the action payload using the dynamic model
	agent_action_model_instance = DynamicActionModel(save_fact_to_memory=params_model)

	result: ActionResult = await controller_instance_for_mem_tests.act(
		action=agent_action_model_instance,  # Pass the instance of the dynamic model
		browser_session=action_execution_context['browser_session'],
		context=action_execution_context,
	)

	assert not result.error, f'Action failed: {result.error}'
	assert result.extracted_content is not None

	expected_substring_in_result = "Fact 'User prefers dark mode for UI....' of type 'user_preference' saved to LTM"
	assert expected_substring_in_result in result.extracted_content, (
		f"Expected substring '{expected_substring_in_result}' not found in '{result.extracted_content}'"
	)

	assert 'ID:' in result.extracted_content
	assert not result.include_in_memory  # Action result (confirmation message) should not be re-saved

	# Verify it's in the memory store by searching
	mem_service: Memory = action_execution_context['agent_memory']
	search_results = mem_service.search_granular_facts(
		query='dark mode preference',
		agent_id=memory_config_instance.agent_id,  # Use the agent_id from the config
	)
	assert len(search_results) > 0, 'Fact not found in memory after saving'
	# mem0 search returns a dict with 'memory' and 'metadata'
	# 'memory' field is "Fact Type: <type>. Details: <content>"
	assert search_results[0]['memory'] == 'Fact Type: user_preference. Details: User prefers dark mode for UI.'
	assert search_results[0]['metadata']['source_url'] == 'https://example.com/settings'


@pytest.mark.asyncio
async def test_controller_save_fact_uses_current_url_by_default(
	controller_instance_for_mem_tests: Controller, action_execution_context: dict, memory_config_instance
):
	# Override the default mock_browser_session URL for this test
	specific_page_mock = AsyncMock()
	specific_page_mock.url = 'https://example.com/page_where_fact_originated'
	action_execution_context['browser_session'].get_current_page = AsyncMock(return_value=specific_page_mock)

	params_model = SaveFactToMemoryAction(
		fact_content='This fact should use the current page URL as source.',
		fact_type='key_finding',
		# source_url is deliberately omitted to test default behavior
	)
	DynamicActionModel = controller_instance_for_mem_tests.registry.create_action_model()
	agent_action_model_instance = DynamicActionModel(save_fact_to_memory=params_model)

	await controller_instance_for_mem_tests.act(
		action=agent_action_model_instance,
		browser_session=action_execution_context['browser_session'],
		context=action_execution_context,
	)

	mem_service: Memory = action_execution_context['agent_memory']
	search_results = mem_service.search_granular_facts(query='fact current page URL', agent_id=memory_config_instance.agent_id)
	assert len(search_results) > 0, 'Fact not found'
	assert search_results[0]['metadata']['source_url'] == 'https://example.com/page_where_fact_originated'


@pytest.mark.asyncio
async def test_controller_query_long_term_memory_various_filters(
	controller_instance_for_mem_tests: Controller,
	action_execution_context: dict,
	memory_config_instance,  # for agent_id
	current_test_run_id,  # for run_id
):
	mem_service: Memory = action_execution_context['agent_memory']
	agent_id = memory_config_instance.agent_id

	DynamicActionModel = controller_instance_for_mem_tests.registry.create_action_model()

	# Save some facts directly for a controlled test environment
	fact1_content = 'The sky is often blue due to Rayleigh scattering.'
	f1 = GranularMemoryEntry(
		agent_id=agent_id,
		run_id=current_test_run_id,
		type='key_finding',
		content=fact1_content,
		source_url='science.com/sky',
		keywords=['physics', 'sky'],
	)
	mem_service.add_granular_fact(f1)

	fact2_content = 'Earth orbits the Sun, taking approximately 365.25 days.'
	f2 = GranularMemoryEntry(
		agent_id=agent_id,
		run_id=current_test_run_id,
		type='key_finding',
		content=fact2_content,
		source_url='spacepedia.org/earth',
		keywords=['astronomy', 'orbit'],
	)
	mem_service.add_granular_fact(f2)

	fact3_content = 'The user expressed a preference for concise summaries.'
	f3 = GranularMemoryEntry(
		agent_id=agent_id,
		run_id=current_test_run_id,
		type='user_preference',
		content=fact3_content,
		keywords=['summary', 'preference'],
	)  # No URL
	mem_service.add_granular_fact(f3)

	# Test 1: Query for "sky"
	query_params_sky_model = QueryLongTermMemoryAction(query_text='information about the sky', max_results=1)
	action_sky = DynamicActionModel(query_long_term_memory=query_params_sky_model)
	result_sky: ActionResult = await controller_instance_for_mem_tests.act(
		action=action_sky,
		browser_session=action_execution_context['browser_session'],
		context=action_execution_context,
	)
	assert not result_sky.error
	assert fact1_content in result_sky.extracted_content
	assert 'Source: science.com/sky' in result_sky.extracted_content
	assert fact2_content not in result_sky.extracted_content

	# Test 2: Query by fact_type "user_preference"
	query_params_pref_model = QueryLongTermMemoryAction(query_text='user preferences', fact_types=['user_preference'])
	action_pref = DynamicActionModel(query_long_term_memory=query_params_pref_model)
	result_pref: ActionResult = await controller_instance_for_mem_tests.act(
		action=action_pref,
		browser_session=action_execution_context['browser_session'],
		context=action_execution_context,
	)
	assert not result_pref.error
	assert fact3_content in result_pref.extracted_content
	assert fact1_content not in result_pref.extracted_content

	# Test 3: Query relevant to a specific URL
	query_params_url_model = QueryLongTermMemoryAction(query_text='earth details', relevant_to_url='spacepedia.org/earth')
	action_url = DynamicActionModel(query_long_term_memory=query_params_url_model)
	result_url: ActionResult = await controller_instance_for_mem_tests.act(
		action=action_url,
		browser_session=action_execution_context['browser_session'],
		context=action_execution_context,
	)
	assert not result_url.error
	assert fact2_content in result_url.extracted_content

	# Test 4: Query with max_results = 1
	query_params_max_model = QueryLongTermMemoryAction(query_text='any scientific fact', max_results=1)
	action_max = DynamicActionModel(query_long_term_memory=query_params_max_model)
	result_max: ActionResult = await controller_instance_for_mem_tests.act(
		action=action_max,
		browser_session=action_execution_context['browser_session'],
		context=action_execution_context,
	)
	assert not result_max.error
	# Extracted content is a string, one fact per line.
	assert len(result_max.extracted_content.strip().splitlines()) == 1

	# Test 5: Query yielding no results
	query_params_none_model = QueryLongTermMemoryAction(query_text='fictional_topic_xyzab_123')
	action_none = DynamicActionModel(query_long_term_memory=query_params_none_model)
	result_none: ActionResult = await controller_instance_for_mem_tests.act(
		action=action_none,
		browser_session=action_execution_context['browser_session'],
		context=action_execution_context,
	)
	assert not result_none.error
	assert 'No relevant facts found in long-term memory.' in result_none.extracted_content


@pytest.mark.asyncio
async def test_controller_memory_actions_fail_gracefully_if_no_service(
	controller_instance_for_mem_tests: Controller, action_execution_context: dict
):
	# Create a context copy without the agent_memory service
	context_no_mem = action_execution_context.copy()
	context_no_mem['agent_memory'] = None

	# Get the dynamically generated ActionModel type from the controller instance
	DynamicActionModel = controller_instance_for_mem_tests.registry.create_action_model()

	# Test save_fact_to_memory
	save_params_model = SaveFactToMemoryAction(fact_content='Test fact', fact_type='raw_text')
	# Construct the action payload using the dynamic model
	# Note: Pydantic models expect model instances for nested models, not dicts, unless parsing from dict.
	save_action_instance = DynamicActionModel(save_fact_to_memory=save_params_model)
	save_result: ActionResult = await controller_instance_for_mem_tests.act(
		action=save_action_instance,  # Pass the instance of the dynamic model
		browser_session=context_no_mem['browser_session'],
		context=context_no_mem,
	)
	assert save_result.error is not None
	assert 'Memory service or agent/run ID not available' in save_result.error

	# Test query_long_term_memory
	query_params_model = QueryLongTermMemoryAction(query_text='Test query')
	# Construct the action payload using the dynamic model
	query_action_instance = DynamicActionModel(query_long_term_memory=query_params_model)
	query_result: ActionResult = await controller_instance_for_mem_tests.act(
		action=query_action_instance,  # Pass the instance of the dynamic model
		browser_session=context_no_mem['browser_session'],
		context=context_no_mem,
	)
	assert query_result.error is not None, f'Expected an error, got None. Result: {query_result}'
	assert 'Memory service or agent ID not available' in query_result.error, f'Error message mismatch. Got: {query_result.error}'


# --- Test Memory Class Directly ---


def test_granular_memory_entry_serialization_to_mem0_metadata():
	entry_uuid = str(uuid.uuid4())
	agent_id_val = 'test_agent_for_metadata'
	run_id_val = 'test_run_for_metadata'

	entry = GranularMemoryEntry(
		id=entry_uuid,
		type='action_taken',
		content='Clicked the submit button.',
		agent_id=agent_id_val,
		run_id=run_id_val,
		source_url='https://example.com/form',
		source_element_xpath="//button[@id='submit']",
		keywords=['form', 'submit', 'action'],
		associated_action={'click_element_by_index': {'index': 5}},
		confidence=1.0,
	)
	metadata = entry.to_mem0_metadata()

	assert metadata['entry_id'] == entry_uuid
	assert metadata['entry_type'] == 'action_taken'
	assert metadata['source_url'] == 'https://example.com/form'
	assert metadata['source_element_xpath'] == "//button[@id='submit']"
	assert metadata['keywords'] == ['form', 'submit', 'action']
	assert metadata['associated_action'] == {'click_element_by_index': {'index': 5}}
	assert metadata['confidence'] == 1.0
	assert metadata['agent_id'] == agent_id_val  # agent_id is also in metadata
	assert metadata['run_id'] == run_id_val
	assert 'timestamp' in metadata  # Should be an ISO format string
	assert metadata.get('relevance_score') is None  # Not set in this entry


def test_memory_class_add_granular_fact(
	agent_memory_service_instance: Memory,
	memory_config_instance,  # for agent_id
	current_test_run_id,
):
	agent_id = memory_config_instance.agent_id
	fact_content = 'A fact added directly via Memory class.'
	fact_entry = GranularMemoryEntry(
		agent_id=agent_id,
		run_id=current_test_run_id,
		type='agent_reflection',
		content=fact_content,
		source_url='internal_reflection_source',
		keywords=['direct_add_test'],
	)

	# Call the method under test
	mem_id_from_add = agent_memory_service_instance.add_granular_fact(fact_entry)

	assert mem_id_from_add is not None, 'add_granular_fact did not return a memory ID'
	assert isinstance(mem_id_from_add, str)

	# Verify by searching (mem0 search returns list of dicts)
	results = agent_memory_service_instance.search_granular_facts(query='directly via Memory class', agent_id=agent_id)
	assert len(results) > 0, 'Fact not found after direct add'

	# Check content and metadata of the search result
	# The 'memory' field from mem0 search result is: "Fact Type: <type>. Details: <content>"
	assert results[0]['memory'] == f'Fact Type: agent_reflection. Details: {fact_content}'
	assert results[0]['metadata']['entry_id'] == fact_entry.id  # Our original ID should be in metadata
	assert results[0]['metadata']['source_url'] == 'internal_reflection_source'
	assert results[0]['metadata']['keywords'] == ['direct_add_test']
	# mem0 stores the 'type' as a category for filtering
	assert results[0]['metadata']['categories'] == ['agent_reflection']


def test_memory_class_search_granular_facts_with_filters(
	agent_memory_service_instance: Memory,  # Main agent's memory service
	memory_config_instance,  # Main agent's config
	current_test_run_id,
	mock_llm_instance,  # For creating other Memory instances
):
	main_agent_id = memory_config_instance.agent_id

	# Facts for the main agent
	fact_tea = GranularMemoryEntry(
		agent_id=main_agent_id,
		run_id=current_test_run_id,
		type='user_preference',
		content='Prefers Earl Grey tea.',
		source_url='flavors.com/tea',
		keywords=['beverage', 'tea', 'earl_grey'],
	)
	fact_deadline = GranularMemoryEntry(
		agent_id=main_agent_id,
		run_id=current_test_run_id,
		type='key_finding',
		content='Project Alpha deadline is EOD Monday.',
		source_url='tracker.com/alpha',
		keywords=['project', 'deadline', 'alpha'],
	)

	# Fact for the same agent but different run_id
	fact_old_run = GranularMemoryEntry(
		agent_id=main_agent_id,
		run_id='old_run_123',
		type='key_finding',
		content='Archived data from Project Beta.',
		source_url='archive.com/beta',
	)

	agent_memory_service_instance.add_granular_fact(fact_tea)
	agent_memory_service_instance.add_granular_fact(fact_deadline)
	agent_memory_service_instance.add_granular_fact(fact_old_run)

	# Fact for a different agent, needs its own Memory service instance
	# but pointing to the SAME underlying mem0 collection for this test to work.
	other_agent_id = f'other_test_agent_{uuid.uuid4().hex[:6]}'

	# Create a MemoryConfig for the other agent that shares the collection name
	other_agent_config = memory_config_instance.model_copy(deep=True)
	other_agent_config.agent_id = other_agent_id
	# granular_memory_collection_name is already unique per memory_config_instance fixture call,
	# so other_agent_config will naturally point to a *different* collection unless we align them.
	# For this test, we need them to use the *same* mem0 collection.
	shared_collection_name = memory_config_instance.granular_memory_collection_name
	other_agent_config.granular_memory_collection_name = shared_collection_name

	other_agent_memory_service = Memory(
		agent_memory_service_instance.message_manager,  # Can reuse mock message_manager
		mock_llm_instance,
		other_agent_config,
	)
	fact_other_agent_content = 'Critical data for the other agent.'
	fact_other_agent = GranularMemoryEntry(
		agent_id=other_agent_id, run_id=current_test_run_id, type='raw_text', content=fact_other_agent_content
	)
	other_agent_memory_service.add_granular_fact(fact_other_agent)

	# 1. Search by query (main agent)
	results_query = agent_memory_service_instance.search_granular_facts(query='tea preference', agent_id=main_agent_id)
	assert len(results_query) >= 1
	assert fact_tea.content in results_query[0]['memory']

	# 2. Search by fact_type (mem0 category) (main agent)
	results_type = agent_memory_service_instance.search_granular_facts(
		query='project deadlines', agent_id=main_agent_id, fact_types=['key_finding']
	)
	assert len(results_type) >= 1  # Should find fact_deadline and fact_old_run
	assert any(fact_deadline.content in res['memory'] for res in results_type)

	# 3. Search by source_url (main agent)
	results_url = agent_memory_service_instance.search_granular_facts(
		query='alpha project', agent_id=main_agent_id, source_url='tracker.com/alpha'
	)
	assert len(results_url) == 1
	assert fact_deadline.content in results_url[0]['memory']

	# 4. Search by keywords (main agent)
	results_keywords = agent_memory_service_instance.search_granular_facts(
		query='alpha info', agent_id=main_agent_id, keywords=['alpha', 'deadline']
	)
	assert len(results_keywords) >= 1
	assert fact_deadline.content in results_keywords[0]['memory']

	# 5. Search by run_id (main agent) - should only get facts from current_test_run_id
	results_run_id = agent_memory_service_instance.search_granular_facts(
		query='any data', agent_id=main_agent_id, run_id=current_test_run_id
	)
	assert len(results_run_id) >= 1
	assert any(fact_tea.content in res['memory'] for res in results_run_id)
	assert any(fact_deadline.content in res['memory'] for res in results_run_id)
	assert not any(fact_old_run.content in res['memory'] for res in results_run_id)  # Belongs to different run_id

	# 6. Search with limit (main agent)
	results_limit = agent_memory_service_instance.search_granular_facts(
		query='any content for main agent', agent_id=main_agent_id, limit=1
	)
	assert len(results_limit) == 1

	# 7. Search for fact from other_agent_id (using its dedicated service or by specifying agent_id in search)
	#    This search uses the main agent's service but queries for the other agent's ID.
	results_for_other_agent_via_main_service = agent_memory_service_instance.search_granular_facts(
		query='critical data',
		agent_id=other_agent_id,  # Querying for the other agent's data
	)
	assert len(results_for_other_agent_via_main_service) == 1, "Could not find other agent's fact when searching by its ID."
	assert fact_other_agent_content in results_for_other_agent_via_main_service[0]['memory']

	# 8. Ensure searching main agent's store for its own ID doesn't find other_agent's fact
	results_main_agent_search = agent_memory_service_instance.search_granular_facts(
		query='critical data for other agent',  # Query text that matches other agent's fact
		agent_id=main_agent_id,  # But searching within main agent's user_id scope
	)
	assert len(results_main_agent_search) == 0, "Main agent search unexpectedly found other agent's fact."


@pytest.mark.asyncio
async def test_memory_add_fact_logs_warning_on_agent_id_mismatch(
	agent_memory_service_instance: Memory,
	memory_config_instance,
	current_test_run_id,
	caplog,  # Pytest fixture to capture logs
):
	fact_with_different_agent_id = GranularMemoryEntry(
		agent_id='completely_different_agent_id_999',  # This ID is different from memory_config_instance.agent_id
		run_id=current_test_run_id,
		type='raw_text',
		content="Content intended for a different agent's mem0 user_id.",
	)

	# The Memory.add_granular_fact uses fact.agent_id as user_id for mem0.
	# It should log a warning if fact.agent_id differs from self.config.agent_id.
	agent_memory_service_instance.add_granular_fact(fact_with_different_agent_id)

	assert (
		f"Mismatch: Fact agent_id '{fact_with_different_agent_id.agent_id}' differs from MemoryConfig agent_id '{memory_config_instance.agent_id}'"
		in caplog.text
	), 'Warning for agent_id mismatch was not logged.'

	# Verify it was indeed stored under the fact's agent_id in mem0
	search_results = agent_memory_service_instance.search_granular_facts(
		query='Content intended for a different agent',
		agent_id='completely_different_agent_id_999',  # Search using the fact's specific agent_id
	)
	assert len(search_results) == 1, 'Fact not found when searching by its specific agent_id'
	assert search_results[0]['memory'].endswith("Content intended for a different agent's mem0 user_id.")
