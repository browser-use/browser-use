"""Each chat instance must reuse one SDK client instead of a pool per call (issue #5565)."""

from browser_use.llm.anthropic.chat import ChatAnthropic
from browser_use.llm.groq.chat import ChatGroq
from browser_use.llm.openai.chat import ChatOpenAI


def test_openai_client_is_cached():
	llm = ChatOpenAI(model='gpt-4o', api_key='sk-test')
	assert llm.get_client() is llm.get_client()


def test_anthropic_client_is_cached():
	llm = ChatAnthropic(model='claude-sonnet-4-5-20250929', api_key='sk-test')
	assert llm.get_client() is llm.get_client()


def test_groq_client_is_cached():
	llm = ChatGroq(model='moonshotai/kimi-k2-instruct', api_key='sk-test')
	assert llm.get_client() is llm.get_client()


def test_fifty_step_run_uses_single_httpx_pool():
	"""The issue #5565 repro: 50 get_client() calls must not allocate 50 httpx pools."""
	llm = ChatOpenAI(model='gpt-4o', api_key='sk-test')
	pools = {id(client._client) for client in (llm.get_client() for _ in range(50))}
	assert len(pools) == 1
