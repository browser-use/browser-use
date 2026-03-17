"""
Test that paint-order filtering never suppresses <a> or <button> elements.

Regression test for: ASP.NET-style pagination where the active-page indicator
(a solid-background element with high z-index / paint-order) covers the bounds of
the immediately-adjacent page link, causing it to be silently dropped from the
agent's interactive-element index.

See: browser_use/dom/serializer/paint_order.py
"""

import re

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile, ViewportSize

# Pagination page: a full-viewport fixed overlay (high z-index, solid white bg)
# sits on top of all pagination <a> links.  Before the fix, those links would be
# marked ignored_by_paint_order and silently disappear from the selector_map.
PAGINATION_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body { margin: 0; padding: 20px; font-family: sans-serif; }

  /* Full-viewport fixed overlay — solid white background, highest paint order.
     pointer-events:none so clicks still reach links underneath. */
  #overlay {
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background: white;
    z-index: 100;
    pointer-events: none;
  }

  /* Pagination sits in normal flow, z-index below overlay */
  #pagination {
    position: relative;
    z-index: 1;
    display: flex;
    gap: 4px;
    padding: 10px 0;
  }

  /* Active-page indicator: solid coloured background, higher z-index */
  .page-current {
    display: inline-block;
    padding: 6px 12px;
    background: #005a8b;
    color: white;
    font-weight: bold;
    position: relative;
    z-index: 10;
  }

  .page-link {
    display: inline-block;
    padding: 6px 12px;
    color: #005a8b;
    text-decoration: none;
    border: 1px solid #005a8b;
  }

  /* A plain div sitting in the same area — should still be filterable */
  #non-interactive {
    position: relative;
    z-index: 1;
    padding: 10px;
    background: transparent;
  }
</style>
</head>
<body>
  <!-- High-paint-order overlay covers everything below it -->
  <div id="overlay"></div>

  <!-- Pagination: active "1" indicator followed by linked pages 2-5 -->
  <div id="pagination">
    <span class="page-current" id="page-1-current">1</span>
    <a class="page-link" id="page-2-link" href="#page2">2</a>
    <a class="page-link" id="page-3-link" href="#page3">3</a>
    <a class="page-link" id="page-4-link" href="#page4">4</a>
    <a class="page-link" id="page-5-link" href="#page5">5</a>
  </div>

  <!-- Button element — must also survive paint-order filtering -->
  <button id="submit-btn" style="position:relative;z-index:1;">Submit</button>

  <div id="non-interactive">Non-interactive content</div>
</body>
</html>"""


@pytest.fixture(scope='module')
def pagination_server():
	server = HTTPServer()
	server.start()
	server.expect_request('/pagination').respond_with_data(PAGINATION_HTML, content_type='text/html')
	yield server
	server.stop()


@pytest.fixture
async def browser_session():
	session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=True,
			window_size=ViewportSize(width=1280, height=800),
		)
	)
	await session.start()
	yield session
	await session.kill()


async def test_pagination_links_survive_paint_order_filtering(browser_session, pagination_server):
	"""
	<a> and <button> elements must retain their interactive index even when a
	high-paint-order solid-background element (e.g. a fixed overlay or active-page
	indicator) fully covers their bounding rect.

	Before the fix: all five links + button were silently removed from selector_map.
	After the fix:  all of them must appear as interactive elements.
	"""
	from browser_use.tools.service import Tools

	tools = Tools()
	url = f'http://{pagination_server.host}:{pagination_server.port}/pagination'
	await tools.navigate(url=url, new_tab=False, browser_session=browser_session)

	import asyncio

	await asyncio.sleep(0.5)

	state = await browser_session.get_browser_state_summary(
		include_screenshot=False,
		include_recent_events=False,
	)

	assert state is not None
	assert state.dom_state is not None

	selector_map = state.dom_state.selector_map
	serialized = state.dom_state.llm_representation()

	# Collect every [index] that appears in the serialized output — these are the
	# elements the LLM can actually click.
	visible_indices = {int(i) for i in re.findall(r'\[(\d+)\]', serialized)}

	# Every interactive element in selector_map must also appear in the serialized text.
	for idx in selector_map:
		assert idx in visible_indices, (
			f'Element {idx} ({selector_map[idx].tag_name} id={getattr(selector_map[idx], "attributes", {}).get("id", "?")}) '
			f'is in selector_map but missing from serialized DOM — likely suppressed by paint-order filtering'
		)

	# The four page links (2-5) must all be present and interactive.
	link_ids = {'page-2-link', 'page-3-link', 'page-4-link', 'page-5-link'}
	found_ids: set[str] = set()
	for idx, node in selector_map.items():
		attrs = getattr(node, 'attributes', {}) or {}
		node_id = attrs.get('id', '')
		if node_id in link_ids:
			found_ids.add(node_id)

	missing = link_ids - found_ids
	assert not missing, (
		f'Pagination links missing from selector_map (suppressed by paint-order filter): {missing}\n'
		f'selector_map ids: {[getattr(n, "attributes", {}).get("id") for n in selector_map.values()]}'
	)

	# The <button> must also survive.
	button_ids = {attrs.get('id') for _, n in selector_map.items() if (attrs := getattr(n, 'attributes', {}) or {})}
	assert 'submit-btn' in button_ids, '<button id="submit-btn"> missing from selector_map — suppressed by paint-order filter'
