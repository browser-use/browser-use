from types import SimpleNamespace
from typing import cast

import pytest

from browser_use.actor.page import Page
from browser_use.browser.session import BrowserSession

STALE_NODE_ERROR = {
	'code': -32000,
	'message': 'Could not find node with given id',
}


async def test_css_selector_reacquires_document_after_stale_root() -> None:
	"""A navigation may invalidate the document root between CDP calls."""

	class FakeDOM:
		def __init__(self) -> None:
			self.document_calls = 0
			self.query_calls = 0

		async def getDocument(self, *, session_id: str) -> dict[str, object]:
			self.document_calls += 1

			# Return the original document root first, then a fresh root on retry.
			return {
				'root': {
					'nodeId': self.document_calls,
				}
			}

		async def querySelectorAll(
			self,
			params: dict[str, object],
			*,
			session_id: str,
		) -> dict[str, object]:
			self.query_calls += 1

			if self.query_calls == 1:
				# Simulate navigation invalidating the root returned by getDocument().
				raise RuntimeError(STALE_NODE_ERROR)

			# The retry must reacquire the document,
			# so this lookup should use the new root nodeId=2.
			assert params['nodeId'] == 2

			return {'nodeIds': []}

	dom = FakeDOM()

	browser_session = cast(
		BrowserSession,
		SimpleNamespace(
			cdp_client=SimpleNamespace(
				send=SimpleNamespace(DOM=dom),
			)
		),
	)

	page = Page(
		browser_session,
		target_id='target',
		session_id='session',
	)

	assert await page.get_elements_by_css_selector('#submit') == []

	assert dom.document_calls == 2
	assert dom.query_calls == 2


async def test_css_selector_does_not_retry_unrelated_cdp_error() -> None:
	"""Only stale-node failures should trigger document reacquisition."""

	class FakeDOM:
		def __init__(self) -> None:
			self.document_calls = 0
			self.query_calls = 0

		async def getDocument(self, *, session_id: str) -> dict[str, object]:
			self.document_calls += 1
			return {'root': {'nodeId': 1}}

		async def querySelectorAll(
			self,
			params: dict[str, object],
			*,
			session_id: str,
		) -> dict[str, object]:
			self.query_calls += 1

			raise RuntimeError(
				{
					'code': -32000,
					'message': 'Some unrelated CDP error',
				}
			)

	dom = FakeDOM()

	browser_session = cast(
		BrowserSession,
		SimpleNamespace(
			cdp_client=SimpleNamespace(
				send=SimpleNamespace(DOM=dom),
			)
		),
	)

	page = Page(
		browser_session,
		target_id='target',
		session_id='session',
	)

	with pytest.raises(RuntimeError):
		await page.get_elements_by_css_selector('#submit')

	# Non-stale-node errors should not be swallowed or retried.
	assert dom.document_calls == 1
	assert dom.query_calls == 1


async def test_css_selector_stale_root_retry_is_bounded() -> None:
	"""Repeated stale-root failures should stop after the bounded retry budget."""

	class FakeDOM:
		def __init__(self) -> None:
			self.document_calls = 0
			self.query_calls = 0

		async def getDocument(self, *, session_id: str) -> dict[str, object]:
			self.document_calls += 1
			return {'root': {'nodeId': self.document_calls}}

		async def querySelectorAll(
			self,
			params: dict[str, object],
			*,
			session_id: str,
		) -> dict[str, object]:
			self.query_calls += 1
			raise RuntimeError(STALE_NODE_ERROR)

	dom = FakeDOM()

	browser_session = cast(
		BrowserSession,
		SimpleNamespace(
			cdp_client=SimpleNamespace(
				send=SimpleNamespace(DOM=dom),
			)
		),
	)

	page = Page(
		browser_session,
		target_id='target',
		session_id='session',
	)

	with pytest.raises(RuntimeError):
		await page.get_elements_by_css_selector('#submit')

	assert dom.document_calls == 3
	assert dom.query_calls == 3
