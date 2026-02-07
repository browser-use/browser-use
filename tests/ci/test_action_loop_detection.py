"""Tests for action loop detection — behavioral cycle breaking (PR #4)."""

from browser_use.agent.service import Agent
from browser_use.agent.views import (
	ActionLoopDetector,
	PageFingerprint,
	compute_action_hash,
)
from browser_use.llm.messages import UserMessage
from tests.ci.conftest import create_mock_llm


def _get_context_messages(agent: Agent) -> list[str]:
	"""Extract text content from the agent's context messages."""
	msgs = agent._message_manager.state.history.context_messages
	return [m.content for m in msgs if isinstance(m, UserMessage) and isinstance(m.content, str)]


# ─── Action hash normalization tests ─────────────────────────────────────────


def test_search_normalization_ignores_keyword_order():
	"""Two searches with the same keywords in different order should produce the same hash."""
	h1 = compute_action_hash('search', {'query': 'site:example.com answers votes'})
	h2 = compute_action_hash('search', {'query': 'votes answers site:example.com'})
	assert h1 == h2


def test_search_normalization_ignores_case():
	"""Search normalization is case-insensitive."""
	h1 = compute_action_hash('search', {'query': 'Python Tutorial'})
	h2 = compute_action_hash('search', {'query': 'python tutorial'})
	assert h1 == h2


def test_search_normalization_ignores_punctuation():
	"""Search normalization strips punctuation."""
	h1 = compute_action_hash('search', {'query': 'site:hinative.com "answers" votes'})
	h2 = compute_action_hash('search', {'query': 'site:hinative.com answers, votes'})
	assert h1 == h2


def test_search_normalization_deduplicates_tokens():
	"""Duplicate tokens in a search query produce the same hash as single tokens."""
	h1 = compute_action_hash('search', {'query': 'python python tutorial'})
	h2 = compute_action_hash('search', {'query': 'python tutorial'})
	assert h1 == h2


def test_search_different_queries_produce_different_hashes():
	"""Fundamentally different search queries should NOT match."""
	h1 = compute_action_hash('search', {'query': 'python web scraping'})
	h2 = compute_action_hash('search', {'query': 'javascript testing framework'})
	assert h1 != h2


def test_click_same_index_same_hash():
	"""Clicking the same element index produces the same hash."""
	h1 = compute_action_hash('click', {'index': 5})
	h2 = compute_action_hash('click', {'index': 5})
	assert h1 == h2


def test_click_different_index_different_hash():
	"""Clicking different element indices produces different hashes."""
	h1 = compute_action_hash('click', {'index': 5})
	h2 = compute_action_hash('click', {'index': 12})
	assert h1 != h2


def test_input_same_element_same_text():
	"""Same element + same text = same hash."""
	h1 = compute_action_hash('input', {'index': 3, 'text': 'hello world', 'clear': True})
	h2 = compute_action_hash('input', {'index': 3, 'text': 'hello world', 'clear': False})
	assert h1 == h2  # clear flag doesn't affect hash


def test_input_different_text_different_hash():
	"""Same element but different text = different hash."""
	h1 = compute_action_hash('input', {'index': 3, 'text': 'hello'})
	h2 = compute_action_hash('input', {'index': 3, 'text': 'goodbye'})
	assert h1 != h2


def test_navigate_same_url_same_hash():
	"""Navigating to the exact same URL produces the same hash."""
	h1 = compute_action_hash('navigate', {'url': 'https://example.com/page1'})
	h2 = compute_action_hash('navigate', {'url': 'https://example.com/page1'})
	assert h1 == h2


def test_navigate_different_paths_different_hash():
	"""Navigating to different paths on the same domain produces different hashes — this is genuine exploration."""
	h1 = compute_action_hash('navigate', {'url': 'https://example.com/page1'})
	h2 = compute_action_hash('navigate', {'url': 'https://example.com/page2'})
	assert h1 != h2


def test_navigate_different_domain_different_hash():
	"""Navigate to different domains produces different hashes."""
	h1 = compute_action_hash('navigate', {'url': 'https://example.com/page1'})
	h2 = compute_action_hash('navigate', {'url': 'https://other.com/page1'})
	assert h1 != h2


def test_scroll_direction_matters():
	"""Scroll up and scroll down are different actions."""
	h1 = compute_action_hash('scroll', {'down': True, 'index': None})
	h2 = compute_action_hash('scroll', {'down': False, 'index': None})
	assert h1 != h2


def test_scroll_different_elements_different_hash():
	"""Scrolling different elements produces different hashes."""
	h1 = compute_action_hash('scroll', {'down': True, 'index': 5})
	h2 = compute_action_hash('scroll', {'down': True, 'index': 10})
	assert h1 != h2


def test_scroll_same_element_same_hash():
	"""Scrolling the same element in the same direction produces the same hash."""
	h1 = compute_action_hash('scroll', {'down': True, 'index': 5})
	h2 = compute_action_hash('scroll', {'down': True, 'index': 5})
	assert h1 == h2


def test_different_action_types_different_hashes():
	"""Different action types always produce different hashes."""
	h1 = compute_action_hash('click', {'index': 5})
	h2 = compute_action_hash('scroll', {'down': True, 'index': None})
	h3 = compute_action_hash('search', {'query': 'test'})
	assert len({h1, h2, h3}) == 3


# ─── ActionLoopDetector unit tests ───────────────────────────────────────────


def test_detector_no_nudge_for_diverse_actions():
	"""No nudge when actions are all different."""
	detector = ActionLoopDetector(window_size=20)
	detector.record_action('click', {'index': 1})
	detector.record_action('scroll', {'down': True, 'index': None})
	detector.record_action('click', {'index': 2})
	detector.record_action('search', {'query': 'something'})
	detector.record_action('navigate', {'url': 'https://example.com'})
	assert detector.get_nudge_message() is None


def test_detector_nudge_at_5_repeats():
	"""Nudge triggers at 5 repetitions of the same action."""
	detector = ActionLoopDetector(window_size=20)
	for _ in range(5):
		detector.record_action('search', {'query': 'site:hinative.com answers votes'})
	msg = detector.get_nudge_message()
	assert msg is not None
	assert 'repeated a similar action' in msg
	assert '5 times' in msg


def test_detector_no_nudge_at_4_repeats():
	"""No nudge at only 4 repetitions (below threshold)."""
	detector = ActionLoopDetector(window_size=20)
	for _ in range(4):
		detector.record_action('search', {'query': 'site:hinative.com answers votes'})
	assert detector.get_nudge_message() is None


def test_detector_nudge_escalates_at_8_repeats():
	"""Stronger nudge at 8 repetitions."""
	detector = ActionLoopDetector(window_size=20)
	for _ in range(8):
		detector.record_action('search', {'query': 'site:hinative.com answers votes'})
	msg = detector.get_nudge_message()
	assert msg is not None
	assert 'still making progress' in msg
	assert '8 times' in msg


def test_detector_nudge_escalates_at_12_repeats():
	"""Most urgent nudge at 12 repetitions."""
	detector = ActionLoopDetector(window_size=20)
	for _ in range(12):
		detector.record_action('search', {'query': 'site:hinative.com answers votes'})
	msg = detector.get_nudge_message()
	assert msg is not None
	assert 'making progress with each repetition' in msg
	assert '12 times' in msg


def test_detector_critical_message_no_done_directive():
	"""Critical nudge should NOT tell the agent to call done — just a gentle heads up."""
	detector = ActionLoopDetector(window_size=20)
	for _ in range(12):
		detector.record_action('search', {'query': 'site:hinative.com answers votes'})
	msg = detector.get_nudge_message()
	assert msg is not None
	assert 'done action' not in msg
	assert 'different approach' in msg


def test_detector_first_nudge_no_cannot_complete():
	"""First nudge should NOT say task 'cannot be completed' — just raise awareness."""
	detector = ActionLoopDetector(window_size=20)
	for _ in range(5):
		detector.record_action('search', {'query': 'site:hinative.com answers votes'})
	msg = detector.get_nudge_message()
	assert msg is not None
	assert 'cannot be completed' not in msg
	assert 'reconsidering your approach' in msg


def test_detector_window_slides():
	"""Old actions fall out of the window."""
	detector = ActionLoopDetector(window_size=10)
	# Fill window with repeated actions
	for _ in range(5):
		detector.record_action('click', {'index': 7})
	assert detector.max_repetition_count == 5

	# Push them out with diverse actions
	for i in range(10):
		detector.record_action('click', {'index': 100 + i})
	# The 5 old repeated actions should have been pushed out
	assert detector.max_repetition_count < 5
	assert detector.get_nudge_message() is None


def test_detector_search_variations_detected_as_same():
	"""Minor variations of the same search (the hinative pattern) are detected as repetition."""
	detector = ActionLoopDetector(window_size=20)
	# These are the kind of variations the agent produces
	queries = [
		'site:hinative.com answers votes questions',
		'site:hinative.com questions answers votes',
		'site:hinative.com votes answers questions',
		'site:hinative.com questions votes answers',
		'site:hinative.com answers questions votes',
	]
	for q in queries:
		detector.record_action('search', {'query': q})
	assert detector.max_repetition_count == 5
	assert detector.get_nudge_message() is not None


# ─── Page stagnation detection tests ─────────────────────────────────────────


def test_page_stagnation_no_nudge_when_pages_change():
	"""No stagnation nudge when page content changes each step."""
	detector = ActionLoopDetector(window_size=20)
	detector.record_page_state('https://example.com', 'page content 1', 50)
	detector.record_page_state('https://example.com', 'page content 2', 55)
	detector.record_page_state('https://example.com', 'page content 3', 60)
	assert detector.consecutive_stagnant_pages == 0
	assert detector.get_nudge_message() is None


def test_page_stagnation_nudge_at_5_identical_pages():
	"""Stagnation nudge fires after 5 consecutive identical page states."""
	detector = ActionLoopDetector(window_size=20)
	# First recording establishes baseline (doesn't count as stagnant)
	for _ in range(6):
		detector.record_page_state('https://example.com', 'same content', 50)
	assert detector.consecutive_stagnant_pages >= 5
	msg = detector.get_nudge_message()
	assert msg is not None
	assert 'page content has not changed' in msg


def test_page_stagnation_no_nudge_at_4_identical_pages():
	"""No stagnation nudge at only 4 consecutive identical pages (below threshold)."""
	detector = ActionLoopDetector(window_size=20)
	# First recording establishes baseline, then 4 stagnant = 5 total recordings
	for _ in range(5):
		detector.record_page_state('https://example.com', 'same content', 50)
	assert detector.consecutive_stagnant_pages == 4
	assert detector.get_nudge_message() is None


def test_page_stagnation_resets_on_change():
	"""Stagnation counter resets when page content changes."""
	detector = ActionLoopDetector(window_size=20)
	detector.record_page_state('https://example.com', 'same content', 50)
	detector.record_page_state('https://example.com', 'same content', 50)
	detector.record_page_state('https://example.com', 'same content', 50)
	assert detector.consecutive_stagnant_pages == 2
	# Page changes
	detector.record_page_state('https://example.com', 'different content', 55)
	assert detector.consecutive_stagnant_pages == 0


def test_combined_loop_and_stagnation():
	"""Both action loop and page stagnation messages appear together."""
	detector = ActionLoopDetector(window_size=20)
	# Create action repetition (8 for STRONG LOOP WARNING)
	for _ in range(8):
		detector.record_action('click', {'index': 7})
	# Create page stagnation (need 5 consecutive stagnant)
	detector.record_page_state('https://example.com', 'same', 50)
	for _ in range(5):
		detector.record_page_state('https://example.com', 'same', 50)
	msg = detector.get_nudge_message()
	assert msg is not None
	assert 'still making progress' in msg
	assert 'page content has not changed' in msg


# ─── PageFingerprint tests ───────────────────────────────────────────────────


def test_page_fingerprint_same_content_equal():
	"""Same content produces equal fingerprints."""
	fp1 = PageFingerprint.from_browser_state('https://example.com', 'hello world', 50)
	fp2 = PageFingerprint.from_browser_state('https://example.com', 'hello world', 50)
	assert fp1 == fp2


def test_page_fingerprint_different_content_not_equal():
	"""Different content produces different fingerprints."""
	fp1 = PageFingerprint.from_browser_state('https://example.com', 'hello world', 50)
	fp2 = PageFingerprint.from_browser_state('https://example.com', 'goodbye world', 50)
	assert fp1 != fp2


def test_page_fingerprint_different_url_not_equal():
	"""Different URL produces different fingerprint even with same content."""
	fp1 = PageFingerprint.from_browser_state('https://example.com', 'hello world', 50)
	fp2 = PageFingerprint.from_browser_state('https://other.com', 'hello world', 50)
	assert fp1 != fp2


def test_page_fingerprint_different_element_count_not_equal():
	"""Different element count produces different fingerprint."""
	fp1 = PageFingerprint.from_browser_state('https://example.com', 'hello world', 50)
	fp2 = PageFingerprint.from_browser_state('https://example.com', 'hello world', 51)
	assert fp1 != fp2


# ─── Agent integration tests ─────────────────────────────────────────────────


async def test_loop_nudge_injected_into_context():
	"""Loop detection nudge is injected as a context message in the agent."""
	llm = create_mock_llm()
	agent = Agent(task='Test task', llm=llm)

	# Simulate 5 repeated actions (new threshold)
	for _ in range(5):
		agent.state.loop_detector.record_action('search', {'query': 'site:example.com answers'})

	agent._inject_loop_detection_nudge()

	messages = _get_context_messages(agent)
	assert len(messages) == 1
	assert 'repeated a similar action' in messages[0]


async def test_no_loop_nudge_when_disabled():
	"""No loop nudge when loop_detection_enabled is False."""
	llm = create_mock_llm()
	agent = Agent(
		task='Test task',
		llm=llm,
		loop_detection_enabled=False,
	)

	# Simulate 8 repeated actions
	for _ in range(8):
		agent.state.loop_detector.record_action('search', {'query': 'site:example.com answers'})

	agent._inject_loop_detection_nudge()

	messages = _get_context_messages(agent)
	assert len(messages) == 0


async def test_no_loop_nudge_for_diverse_actions():
	"""No loop nudge when actions are diverse."""
	llm = create_mock_llm()
	agent = Agent(task='Test task', llm=llm)

	agent.state.loop_detector.record_action('click', {'index': 1})
	agent.state.loop_detector.record_action('scroll', {'down': True, 'index': None})
	agent.state.loop_detector.record_action('click', {'index': 2})

	agent._inject_loop_detection_nudge()

	messages = _get_context_messages(agent)
	assert len(messages) == 0


async def test_loop_detector_initialized_from_settings():
	"""Loop detector window size is set from agent settings."""
	llm = create_mock_llm()
	agent = Agent(task='Test task', llm=llm, loop_detection_window=30)
	assert agent.state.loop_detector.window_size == 30


async def test_loop_detector_default_window_size():
	"""Loop detection default window size is 20."""
	llm = create_mock_llm()
	agent = Agent(task='Test task', llm=llm)
	assert agent.settings.loop_detection_enabled is True
	assert agent.state.loop_detector.window_size == 20
