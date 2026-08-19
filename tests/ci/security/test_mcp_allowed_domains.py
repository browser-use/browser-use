"""Tests for MCP server allowed_domains dispatch (GHSA-vfcm-843v-w6v3).

The MCP `retry_with_browser_use_agent` tool used to default `allowed_domains` to
`[]` when the client omitted the argument. That value was then forwarded to
`BrowserProfile(allowed_domains=[])`, which `SecurityWatchdog` interprets as
"no allowlist configured — allow every URL", silently disabling any
admin-configured restrictions on the underlying profile.

The fix is to default to `None` so the admin-configured profile defaults are
preserved when the client omits the argument.
"""

from typing import Any

import pytest

from browser_use.mcp.server import BrowserUseServer


@pytest.fixture
def server() -> BrowserUseServer:
	return BrowserUseServer()


async def test_dispatch_passes_none_when_allowed_domains_omitted(server: BrowserUseServer) -> None:
	"""Client omits `allowed_domains` → dispatcher must pass `None` to the agent runner."""
	captured: dict[str, Any] = {}

	async def recording_stub(**kwargs: Any) -> str:
		captured.update(kwargs)
		return 'ok'

	server._retry_with_browser_use_agent = recording_stub  # type: ignore[method-assign]
	await server._execute_tool('retry_with_browser_use_agent', {'task': 'noop'})

	assert 'allowed_domains' in captured, 'dispatcher must forward the allowed_domains kwarg'
	assert captured['allowed_domains'] is None, (
		f'Expected None to preserve admin-configured profile defaults; '
		f'got {captured["allowed_domains"]!r} which would disable SecurityWatchdog '
		f'when passed as BrowserProfile(allowed_domains=...).'
	)


async def test_dispatch_forwards_explicit_list(server: BrowserUseServer) -> None:
	"""Explicit non-empty list from client must reach the agent runner unchanged."""
	captured: dict[str, Any] = {}

	async def recording_stub(**kwargs: Any) -> str:
		captured.update(kwargs)
		return 'ok'

	server._retry_with_browser_use_agent = recording_stub  # type: ignore[method-assign]
	await server._execute_tool(
		'retry_with_browser_use_agent',
		{'task': 'noop', 'allowed_domains': ['example.test']},
	)
	assert captured['allowed_domains'] == ['example.test']


async def test_explicit_empty_list_does_not_override_profile_defaults(server: BrowserUseServer) -> None:
	"""Defense in depth: even when a client explicitly sends `allowed_domains=[]`,
	`_retry_with_browser_use_agent` must NOT wipe profile defaults — empty list is
	semantically equivalent to "no override" for the security boundary."""
	# Patch the boundary just below the override decision: the BrowserProfile constructor.
	# We capture the resolved allowed_domains and short-circuit before LLM/agent setup.
	captured_profile_kwargs: dict[str, Any] = {}

	from browser_use.mcp import server as server_module

	original_browser_profile = server_module.BrowserProfile

	class CapturingBrowserProfile:
		def __init__(self, **kwargs: Any) -> None:
			captured_profile_kwargs.update(kwargs)
			raise _StopAgentSetup('captured')

	server_module.BrowserProfile = CapturingBrowserProfile  # type: ignore[misc]

	# Stub out the LLM construction path so we don't need real credentials —
	# the override decision happens before BrowserProfile() is called regardless,
	# but we need _retry_with_browser_use_agent to reach that point.
	try:
		with pytest.raises(_StopAgentSetup):
			await server._retry_with_browser_use_agent(
				task='noop',
				allowed_domains=[],
			)
	finally:
		server_module.BrowserProfile = original_browser_profile  # type: ignore[misc]

	# The profile dict should NOT have allowed_domains overridden to [] —
	# either the key is absent (profile defaults apply) or it carries whatever
	# the admin-configured default was. Either way: not [].
	assert captured_profile_kwargs.get('allowed_domains') != [], (
		'Empty list from client wiped profile defaults — SecurityWatchdog would be disabled.'
	)


class _StopAgentSetup(Exception):
	"""Marker exception used to short-circuit agent construction during testing."""
