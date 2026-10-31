"""Each chat instance must reuse one SDK client per event loop instead of a pool per call (issue #5565)."""

import asyncio

import pytest

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


CHAT_INSTANCES = [
	pytest.param(lambda: ChatOpenAI(model='gpt-4o', api_key='sk-test'), id='openai'),
	pytest.param(lambda: ChatAnthropic(model='claude-sonnet-4-5-20250929', api_key='sk-test'), id='anthropic'),
	pytest.param(lambda: ChatGroq(model='moonshotai/kimi-k2-instruct', api_key='sk-test'), id='groq'),
]


def _two_clients_in_one_loop(llm):
	async def collect():
		return llm.get_client(), llm.get_client()

	return asyncio.run(collect())


def _client_in_a_fresh_loop(llm):
	async def collect():
		return llm.get_client()

	return asyncio.run(collect())


@pytest.mark.parametrize('make_llm', CHAT_INSTANCES)
def test_client_is_reused_within_one_event_loop(make_llm):
	"""Keying the cache by loop must not undo #5565: a loop still gets one client, not one per call."""
	llm = make_llm()
	first, second = _two_clients_in_one_loop(llm)
	assert first is second


@pytest.mark.parametrize('make_llm', CHAT_INSTANCES)
def test_client_is_not_reused_after_its_loop_closed(make_llm):
	"""`Agent.run_sync()` calls `asyncio.run()`, so a cached client can outlive the loop that opened its pool."""
	llm = make_llm()
	assert _client_in_a_fresh_loop(llm) is not _client_in_a_fresh_loop(llm)


def test_consecutive_sync_runs_each_get_their_own_client():
	llm = ChatOpenAI(model='gpt-4o', api_key='sk-test')
	clients = [_client_in_a_fresh_loop(llm) for _ in range(3)]  # keep them referenced so id() stays unique
	assert len({id(client) for client in clients}) == 3


@pytest.mark.parametrize('make_llm', CHAT_INSTANCES)
def test_clients_are_reused_across_alternating_live_loops(make_llm):
	llm = make_llm()
	first_loop, second_loop = asyncio.new_event_loop(), asyncio.new_event_loop()
	clients = []

	async def collect():
		client = llm.get_client()
		clients.append((asyncio.get_running_loop(), client))
		return client

	try:
		first = first_loop.run_until_complete(collect())
		second = second_loop.run_until_complete(collect())
		assert first is not second
		assert first_loop.run_until_complete(collect()) is first
		assert second_loop.run_until_complete(collect()) is second
	finally:
		for loop, client in clients:
			loop.run_until_complete(client.close())
		first_loop.close()
		second_loop.close()


@pytest.mark.parametrize('make_llm', CHAT_INSTANCES)
def test_aclose_releases_only_the_current_loops_client(make_llm):
	llm = make_llm()
	first_loop, second_loop = asyncio.new_event_loop(), asyncio.new_event_loop()
	sync_client = llm.get_client()
	clients = [(first_loop, sync_client)]

	async def collect():
		client = llm.get_client()
		clients.append((asyncio.get_running_loop(), client))
		return client

	try:
		first = first_loop.run_until_complete(collect())
		second = second_loop.run_until_complete(collect())
		first_loop.run_until_complete(llm.aclose())
		assert first.is_closed()
		assert sync_client.is_closed()
		assert not second.is_closed()
		replacement = first_loop.run_until_complete(collect())
		assert replacement is not first
		assert not replacement.is_closed()
		first_loop.run_until_complete(llm.aclose())
		first_loop.run_until_complete(llm.aclose())
		assert replacement.is_closed()
		second_loop.run_until_complete(llm.aclose())
		assert second.is_closed()
	finally:
		for loop, client in clients:
			loop.run_until_complete(client.close())
		first_loop.close()
		second_loop.close()
