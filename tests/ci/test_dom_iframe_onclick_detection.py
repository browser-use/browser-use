"""Elements inside same-origin iframes must be scanned for click handlers.

Regression test for #5471: the listener-detection script in `_get_all_trees()`
collected its candidates with `document.querySelectorAll('*')`, which does not
descend into the `contentDocument` of same-origin iframes. Cross-origin
iframes are covered by the per-target OOPIF traversal in `get_dom_tree()`, but
same-origin iframes fell into neither path, so a clickable element inside one
was never assigned an [index] and the agent saw it as plain text — it then
burned steps clicking a neighbouring element or fell back to `evaluate`.

Same-origin iframes are the norm in payment/SDK widgets that need to share
cookies with the host page, and mobile H5 component libraries commonly bind
handlers at runtime via `el.onclick = fn`, which is the case pinned down here.

Scope note: `getEventListeners()` is a DevTools Console utility that only
reports listeners for the execution context it is called from, so for an
element inside an iframe it returns `{}` even when that iframe is same-origin.
Reading the DOM0 `el.onclick` property works across contexts, so that is the
signal the fix falls back to inside frames. Handlers registered inside an
iframe with `addEventListener()` therefore remain undetected; that is a
separate improvement and is deliberately not asserted here.
"""

import asyncio

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser.events import NavigateToUrlEvent

HOST_PAGE = """<!DOCTYPE html>
<html><head><title>Same-origin iframe handler</title></head>
<body>
	<button id="plain">Plain button</button>
	<iframe id="frame" src="/frame" width="400" height="200"></iframe>
</body></html>"""

FRAME_PAGE = """<!DOCTYPE html>
<html><head><title>Frame</title></head>
<body>
	<div id="inframe">Pay now</div>
	<script>
		document.getElementById('inframe').onclick = function () { window.__inframeClicked = true; };
	</script>
</body></html>"""


@pytest.fixture(scope='module')
def http_server():
	server = HTTPServer()
	server.start()
	server.expect_request('/host').respond_with_data(HOST_PAGE, content_type='text/html')
	server.expect_request('/frame').respond_with_data(FRAME_PAGE, content_type='text/html')
	yield server
	server.stop()


async def _indexed_ids(browser_session) -> set[str]:
	"""Return the ids of elements the agent can actually click (i.e. that got an [index])."""
	state = await browser_session.get_browser_state_summary(include_screenshot=False)
	return {
		node.attributes['id'] for node in state.dom_state.selector_map.values() if node.attributes and 'id' in node.attributes
	}


async def test_handler_inside_same_origin_iframe_is_detected(browser_session, http_server):
	"""A handler bound inside a same-origin iframe must make its element clickable."""
	event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=http_server.url_for('/host')))
	await event
	await event.event_result(raise_if_any=True, raise_if_none=False)
	await asyncio.sleep(2)  # give the iframe time to load before snapshotting

	ids = await _indexed_ids(browser_session)

	assert 'plain' in ids, 'a plain <button> must always be indexed'
	assert 'inframe' in ids, 'a handler inside a same-origin iframe must be detected (#5471)'
