"""Tests for domain provenance tracking and departure signals."""

from browser_use.agent.service import Agent
from browser_use.agent.views import ActionResult, AgentHistory
from browser_use.browser.views import BrowserStateHistory
from browser_use.llm.messages import UserMessage
from tests.ci.conftest import create_mock_llm


def _get_context_messages(agent: Agent) -> list[str]:
	"""Extract text content from the agent's context messages."""
	msgs = agent._message_manager.state.history.context_messages
	return [m.content for m in msgs if isinstance(m, UserMessage) and isinstance(m.content, str)]


# ---------------------------------------------------------------------------
# 1. target_domain extracted from task URL
# ---------------------------------------------------------------------------


async def test_target_domain_extracted_from_task_url():
	"""target_domain should be set when the task contains a URL."""
	llm = create_mock_llm()
	agent = Agent(task='Go to https://example.com/products and find the price', llm=llm)

	assert agent.state.target_domain == 'example.com'


# ---------------------------------------------------------------------------
# 2. target_domain is None when task has no URL
# ---------------------------------------------------------------------------


async def test_target_domain_none_when_no_url():
	"""target_domain should be None when the task has no URL."""
	llm = create_mock_llm()
	agent = Agent(task='Tell me the meaning of life', llm=llm)

	assert agent.state.target_domain is None


# ---------------------------------------------------------------------------
# 3. Departure signal injected on different domain
# ---------------------------------------------------------------------------


async def test_departure_signal_on_different_domain():
	"""Context message with DOMAIN NOTE should be injected when on a different domain."""
	llm = create_mock_llm()
	agent = Agent(task='Go to https://example.com and find info', llm=llm)

	agent._inject_domain_departure_signal('https://other-site.org/page')

	messages = _get_context_messages(agent)
	assert len(messages) == 1
	msg = messages[0]
	assert 'DOMAIN NOTE' in msg
	assert 'now on other-site.org' in msg
	assert 'target domain (example.com)' in msg


# ---------------------------------------------------------------------------
# 4. No departure signal on target domain
# ---------------------------------------------------------------------------


async def test_no_departure_signal_on_target_domain():
	"""No context message when still on the target domain."""
	llm = create_mock_llm()
	agent = Agent(task='Go to https://example.com and find info', llm=llm)

	agent._inject_domain_departure_signal('https://example.com/products/123')

	messages = _get_context_messages(agent)
	assert len(messages) == 0


# ---------------------------------------------------------------------------
# 5. Search engine identified in departure signal
# ---------------------------------------------------------------------------


async def test_departure_signal_identifies_search_engine():
	"""Departure signal should specifically mention 'search engine' for google.com etc."""
	llm = create_mock_llm()
	agent = Agent(task='Go to https://example.com and find info', llm=llm)

	agent._inject_domain_departure_signal('https://www.google.com/search?q=example')

	messages = _get_context_messages(agent)
	assert len(messages) == 1
	msg = messages[0]
	assert 'search engine' in msg
	assert 'search engine (www.google.com)' in msg


# ---------------------------------------------------------------------------
# 6. No departure signal when no target domain
# ---------------------------------------------------------------------------


async def test_no_departure_signal_when_no_target():
	"""No-op when target_domain is None (task has no URL)."""
	llm = create_mock_llm()
	agent = Agent(task='Do something without a URL', llm=llm)
	assert agent.state.target_domain is None

	agent._inject_domain_departure_signal('https://google.com/search')

	messages = _get_context_messages(agent)
	assert len(messages) == 0


# ---------------------------------------------------------------------------
# 7. domains_visited tracked
# ---------------------------------------------------------------------------


async def test_domains_visited_tracked():
	"""domains_visited should accumulate hostnames as the agent navigates."""
	llm = create_mock_llm()
	agent = Agent(task='Go to https://example.com and find info', llm=llm)

	agent._inject_domain_departure_signal('https://example.com/page1')
	agent._inject_domain_departure_signal('https://google.com/search')
	agent._inject_domain_departure_signal('https://other.org/page')
	agent._inject_domain_departure_signal('https://example.com/page2')

	assert 'example.com' in agent.state.domains_visited
	assert 'google.com' in agent.state.domains_visited
	assert 'other.org' in agent.state.domains_visited


# ---------------------------------------------------------------------------
# 8. www prefix normalization
# ---------------------------------------------------------------------------


async def test_www_prefix_normalization():
	"""www.example.com should be treated as same domain as example.com for departure."""
	llm = create_mock_llm()
	agent = Agent(task='Go to https://www.example.com and find info', llm=llm)

	# Should NOT trigger departure signal because www.example.com normalizes to example.com
	agent._inject_domain_departure_signal('https://example.com/page')

	messages = _get_context_messages(agent)
	assert len(messages) == 0


# ---------------------------------------------------------------------------
# 9. _normalize_domain static method
# ---------------------------------------------------------------------------


async def test_normalize_domain():
	"""_normalize_domain should strip www. prefix correctly."""
	assert Agent._normalize_domain('www.example.com') == 'example.com'
	assert Agent._normalize_domain('example.com') == 'example.com'
	assert Agent._normalize_domain('www.google.com') == 'google.com'
	assert Agent._normalize_domain(None) is None
	assert Agent._normalize_domain('wwwexample.com') == 'wwwexample.com'


# ---------------------------------------------------------------------------
# 10. Provenance tagging on done result
# ---------------------------------------------------------------------------


async def test_provenance_tagging_on_done_result():
	"""_tag_result_with_provenance should annotate the final result when off-domain visits exist."""
	llm = create_mock_llm()
	agent = Agent(task='Go to https://example.com and find info', llm=llm)

	# Simulate visited domains
	agent.state.domains_visited = {'example.com', 'google.com', 'other.org'}

	# Add a done result to history
	done_result = ActionResult(is_done=True, success=True, extracted_content='The answer is 42')
	agent.history.history.append(
		AgentHistory(
			model_output=None,
			result=[done_result],
			state=BrowserStateHistory(url='https://example.com', title='Example', tabs=[], interacted_element=[]),
		)
	)

	agent._tag_result_with_provenance()

	assert done_result.source_domain == 'example.com'
	assert done_result.extracted_content is not None
	# Check provenance annotation format: [Provenance: target=<domain>; ...]
	assert done_result.extracted_content.startswith('The answer is 42')
	provenance_part = done_result.extracted_content.split('[Provenance:')[1]
	assert provenance_part.startswith(' target=example.com;')


# ---------------------------------------------------------------------------
# 11. No provenance tagging when only target domain visited
# ---------------------------------------------------------------------------


async def test_no_provenance_when_only_target_visited():
	"""No provenance annotation when the agent stayed on the target domain."""
	llm = create_mock_llm()
	agent = Agent(task='Go to https://example.com and find info', llm=llm)

	agent.state.domains_visited = {'example.com', 'www.example.com'}

	done_result = ActionResult(is_done=True, success=True, extracted_content='The answer is 42')
	agent.history.history.append(
		AgentHistory(
			model_output=None,
			result=[done_result],
			state=BrowserStateHistory(url='https://example.com', title='Example', tabs=[], interacted_element=[]),
		)
	)

	agent._tag_result_with_provenance()

	# No provenance annotation since all visited domains normalize to the target
	assert done_result.source_domain is None
	assert done_result.extracted_content == 'The answer is 42'


# ---------------------------------------------------------------------------
# 12. No provenance tagging without target domain
# ---------------------------------------------------------------------------


async def test_no_provenance_without_target():
	"""No provenance tagging when target_domain is None."""
	llm = create_mock_llm()
	agent = Agent(task='Do something without a URL', llm=llm)

	agent.state.domains_visited = {'google.com', 'other.org'}

	done_result = ActionResult(is_done=True, success=True, extracted_content='Done')
	agent.history.history.append(
		AgentHistory(
			model_output=None,
			result=[done_result],
			state=BrowserStateHistory(url='https://google.com', title='Google', tabs=[], interacted_element=[]),
		)
	)

	agent._tag_result_with_provenance()

	assert done_result.source_domain is None
	assert done_result.extracted_content == 'Done'


# ---------------------------------------------------------------------------
# 13. Provenance stored in metadata for structured output
# ---------------------------------------------------------------------------


async def test_provenance_in_metadata_for_structured_output():
	"""When output_model_schema is set, provenance should go into metadata, not extracted_content."""
	from pydantic import BaseModel

	class FakeOutputModel(BaseModel):
		answer: str

	llm = create_mock_llm()
	agent = Agent(task='Go to https://example.com and find info', llm=llm)
	agent.output_model_schema = FakeOutputModel  # type: ignore[assignment]

	agent.state.domains_visited = {'example.com', 'google.com'}

	done_result = ActionResult(is_done=True, success=True, extracted_content='{"answer": "42"}')
	agent.history.history.append(
		AgentHistory(
			model_output=None,
			result=[done_result],
			state=BrowserStateHistory(url='https://example.com', title='Example', tabs=[], interacted_element=[]),
		)
	)

	agent._tag_result_with_provenance()

	# extracted_content should NOT be modified
	assert done_result.extracted_content == '{"answer": "42"}'
	# provenance should be in metadata
	assert done_result.metadata is not None
	assert 'provenance' in done_result.metadata
	provenance = done_result.metadata['provenance']
	assert provenance.startswith('[Provenance: target=example.com;')
	assert 'search engines visited:' in provenance


# ---------------------------------------------------------------------------
# 14. Search engine categorized in provenance note
# ---------------------------------------------------------------------------


async def test_provenance_categorizes_search_engines():
	"""Provenance note should separately categorize search engines and other domains."""
	llm = create_mock_llm()
	agent = Agent(task='Go to https://example.com and find info', llm=llm)

	agent.state.domains_visited = {'example.com', 'www.google.com', 'other-site.org'}

	done_result = ActionResult(is_done=True, success=True, extracted_content='Result')
	agent.history.history.append(
		AgentHistory(
			model_output=None,
			result=[done_result],
			state=BrowserStateHistory(url='https://example.com', title='Example', tabs=[], interacted_element=[]),
		)
	)

	agent._tag_result_with_provenance()

	assert done_result.extracted_content is not None
	# Parse the provenance annotation and validate both categories are present
	provenance_part = done_result.extracted_content.split('[Provenance:')[1].rstrip(']')
	assert 'search engines visited:' in provenance_part
	assert 'other domains visited:' in provenance_part
	# Validate specific domains appear in the correct category
	search_section = provenance_part.split('search engines visited:')[1].split(';')[0].strip()
	other_section = provenance_part.split('other domains visited:')[1].split(';')[0].strip().rstrip(']')
	assert 'www.google.com' in search_section.split(', ')
	assert 'other-site.org' in other_section.split(', ')


# ---------------------------------------------------------------------------
# 15. No departure signal on None/empty URL
# ---------------------------------------------------------------------------


async def test_no_departure_signal_on_empty_url():
	"""No-op when current_url is None or empty."""
	llm = create_mock_llm()
	agent = Agent(task='Go to https://example.com and find info', llm=llm)

	agent._inject_domain_departure_signal(None)
	agent._inject_domain_departure_signal('')

	messages = _get_context_messages(agent)
	assert len(messages) == 0
