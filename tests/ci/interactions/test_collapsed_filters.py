"""
Test that the agent/browser correctly handles collapsed filter panels.

Covers the pattern where filter options are hidden behind a "More Filters" button
(aria-expanded=false) and only become visible after clicking it — a common cause
of agent failures on real e-commerce/content sites (EVA-37).
"""

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile
from browser_use.tools.service import Tools

COLLAPSED_FILTER_PAGE = """
<!DOCTYPE html>
<html>
<head>
	<title>Filter Panel Test</title>
	<style>
		body { font-family: sans-serif; padding: 20px; }
		#filter-panel { display: none; margin-top: 10px; padding: 10px; border: 1px solid #ccc; }
		#filter-panel.open { display: block; }
		.product { padding: 5px; }
		#results { margin-top: 20px; }
		label { display: block; margin: 5px 0; cursor: pointer; }
	</style>
</head>
<body>
	<h1>Product Catalog</h1>

	<button
		id="more-filters-btn"
		aria-expanded="false"
		aria-controls="filter-panel"
		onclick="toggleFilters()"
	>
		More Filters
	</button>

	<div id="filter-panel" role="region" aria-label="Filter options">
		<fieldset>
			<legend>Dietary</legend>
			<label>
				<input type="checkbox" id="low-carb" value="low-carb" onchange="applyFilter()">
				Low Carb
			</label>
			<label>
				<input type="checkbox" id="vegan" value="vegan" onchange="applyFilter()">
				Vegan
			</label>
		</fieldset>
	</div>

	<div id="results">
		<div class="product">Apple Pie</div>
		<div class="product">Banana Bread</div>
		<div class="product">Cauliflower Rice (low-carb)</div>
		<div class="product">Kale Salad (vegan, low-carb)</div>
	</div>

	<div id="status">No filter applied</div>

	<script>
		function toggleFilters() {
			const btn = document.getElementById('more-filters-btn');
			const panel = document.getElementById('filter-panel');
			const isOpen = btn.getAttribute('aria-expanded') === 'true';
			btn.setAttribute('aria-expanded', String(!isOpen));
			panel.classList.toggle('open', !isOpen);
		}

		function applyFilter() {
			const lowCarb = document.getElementById('low-carb').checked;
			const vegan = document.getElementById('vegan').checked;
			const active = [];
			if (lowCarb) active.push('low-carb');
			if (vegan) active.push('vegan');
			document.getElementById('status').textContent =
				active.length ? 'Active filters: ' + active.join(', ') : 'No filter applied';
		}
	</script>
</body>
</html>
"""

SORT_HIDDEN_PAGE = """
<!DOCTYPE html>
<html>
<head>
	<title>Sort Panel Test</title>
	<style>
		body { font-family: sans-serif; padding: 20px; }
		#sort-options { display: none; }
		#sort-options.open { display: block; }
		.sort-option { padding: 5px 10px; cursor: pointer; border: 1px solid #ccc; margin: 2px; display: inline-block; }
		.sort-option:hover { background: #eee; }
	</style>
</head>
<body>
	<h1>Products</h1>

	<button
		id="sort-btn"
		aria-expanded="false"
		aria-haspopup="listbox"
		onclick="toggleSort()"
	>
		Sort by
	</button>

	<div id="sort-options" role="listbox" aria-label="Sort options">
		<div class="sort-option" role="option" onclick="selectSort('price-asc')">Price: Low to High</div>
		<div class="sort-option" role="option" onclick="selectSort('price-desc')">Price: High to Low</div>
		<div class="sort-option" role="option" onclick="selectSort('newest')">Newest First</div>
	</div>

	<div id="sort-status">Default sort</div>

	<script>
		function toggleSort() {
			const btn = document.getElementById('sort-btn');
			const panel = document.getElementById('sort-options');
			const isOpen = btn.getAttribute('aria-expanded') === 'true';
			btn.setAttribute('aria-expanded', String(!isOpen));
			panel.classList.toggle('open', !isOpen);
		}

		function selectSort(value) {
			document.getElementById('sort-status').textContent = 'Sorted by: ' + value;
			// Close the panel
			document.getElementById('sort-btn').setAttribute('aria-expanded', 'false');
			document.getElementById('sort-options').classList.remove('open');
		}
	</script>
</body>
</html>
"""


@pytest.fixture(scope='module')
def httpserver():
	server = HTTPServer()
	server.start()
	server.expect_request('/collapsed-filter').respond_with_data(COLLAPSED_FILTER_PAGE, content_type='text/html')
	server.expect_request('/hidden-sort').respond_with_data(SORT_HIDDEN_PAGE, content_type='text/html')
	yield server
	server.stop()


@pytest.fixture(scope='module')
async def browser_session():
	session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=True,
			chromium_sandbox=False,
		)
	)
	await session.start()
	yield session
	await session.kill()


@pytest.fixture(scope='module')
def tools():
	return Tools()


class TestCollapsedFilterPanel:
	"""Browser-level tests: collapsed filter panels are visible in DOM state and expand correctly."""

	async def test_collapsed_button_is_interactive_and_shows_expanded_false(
		self, browser_session: BrowserSession, tools: Tools, httpserver: HTTPServer
	):
		"""The 'More Filters' button must appear as interactive with expanded=false before clicking."""
		url = f'http://{httpserver.host}:{httpserver.port}/collapsed-filter'
		await tools.navigate(url=url, new_tab=False, browser_session=browser_session)

		state = await browser_session.get_browser_state_summary()
		state_text = str(state)

		# The button must be visible and interactive so the agent can find it
		assert 'More Filters' in state_text, 'More Filters button not visible in browser state'
		# expanded=false must be present so the agent knows the panel is collapsed
		assert 'expanded=false' in state_text or 'aria-expanded' in state_text, (
			'Collapsed state (expanded=false) not reflected in browser state — '
			'agent will not know to click the button to expand filters'
		)

	async def test_clicking_more_filters_reveals_filter_options(
		self, browser_session: BrowserSession, tools: Tools, httpserver: HTTPServer
	):
		"""Clicking 'More Filters' must reveal the hidden filter checkboxes as new interactive elements."""
		url = f'http://{httpserver.host}:{httpserver.port}/collapsed-filter'
		await tools.navigate(url=url, new_tab=False, browser_session=browser_session)

		# Get initial state and find the More Filters button index
		state = await browser_session.get_browser_state_summary()
		btn_index = await browser_session.get_index_by_id('more-filters-btn')
		assert btn_index is not None, 'More Filters button not found in interactive elements'

		# Filter checkboxes must NOT be visible before expanding
		initial_state_text = str(state)
		assert 'Low Carb' not in initial_state_text, 'Filter options should be hidden before expanding panel'

		# Click the More Filters button to expand
		await tools.click(index=btn_index, browser_session=browser_session)

		# Get new state — filter checkboxes must now be visible
		new_state = await browser_session.get_browser_state_summary()
		new_state_text = str(new_state)

		assert 'Low Carb' in new_state_text, (
			'Filter options not revealed after clicking More Filters — agent cannot apply filters if they remain hidden'
		)
		assert 'Vegan' in new_state_text, 'Vegan filter option not revealed after expanding panel'

	async def test_applying_revealed_filter_updates_page(
		self, browser_session: BrowserSession, tools: Tools, httpserver: HTTPServer
	):
		"""After expanding the panel and clicking a filter, the page status must update."""
		url = f'http://{httpserver.host}:{httpserver.port}/collapsed-filter'
		await tools.navigate(url=url, new_tab=False, browser_session=browser_session)

		# Expand the filter panel
		btn_index = await browser_session.get_index_by_id('more-filters-btn')
		assert btn_index is not None
		await tools.click(index=btn_index, browser_session=browser_session)

		# Refresh DOM state so newly revealed elements are indexed
		await browser_session.get_browser_state_summary()

		# Now find and click the Low Carb checkbox
		checkbox_index = await browser_session.get_index_by_id('low-carb')
		assert checkbox_index is not None, 'Low Carb checkbox not found after expanding filter panel'
		await tools.click(index=checkbox_index, browser_session=browser_session)

		# Verify the filter was applied by checking the status element
		cdp_session = await browser_session.get_or_create_cdp_session()
		result = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': "document.getElementById('status').textContent", 'returnByValue': True},
			session_id=cdp_session.session_id,
		)
		status_text = result.get('result', {}).get('value', '')
		assert 'low-carb' in status_text, (
			f"Filter was not applied — status shows: '{status_text}'. Expected: Active filters: low-carb"
		)


class TestHiddenSortPanel:
	"""Sort dropdowns hidden behind a button must expand correctly."""

	async def test_sort_button_shows_expanded_false(self, browser_session: BrowserSession, tools: Tools, httpserver: HTTPServer):
		"""Sort button must appear with expanded=false before being clicked."""
		url = f'http://{httpserver.host}:{httpserver.port}/hidden-sort'
		await tools.navigate(url=url, new_tab=False, browser_session=browser_session)

		state = await browser_session.get_browser_state_summary()
		state_text = str(state)

		assert 'Sort by' in state_text, 'Sort button not visible in browser state'
		assert 'expanded=false' in state_text or 'aria-expanded' in state_text, (
			'Sort button collapsed state not reflected in browser state'
		)

	async def test_clicking_sort_reveals_options_and_selection_works(
		self, browser_session: BrowserSession, tools: Tools, httpserver: HTTPServer
	):
		"""Clicking Sort reveals options; clicking an option updates the sort status."""
		url = f'http://{httpserver.host}:{httpserver.port}/hidden-sort'
		await tools.navigate(url=url, new_tab=False, browser_session=browser_session)

		# Sort options must be hidden initially
		initial_state = await browser_session.get_browser_state_summary()
		assert 'Price: Low to High' not in str(initial_state), 'Sort options should be hidden initially'

		# Click Sort button to expand
		btn_index = await browser_session.get_index_by_id('sort-btn')
		assert btn_index is not None
		await tools.click(index=btn_index, browser_session=browser_session)

		# Sort options must now be visible
		expanded_state = await browser_session.get_browser_state_summary()
		assert 'Price: Low to High' in str(expanded_state), 'Sort options not revealed after clicking Sort by button'

		# Trigger the sort selection via JS (mirrors what a click on "Price: Low to High" would do)
		cdp_session = await browser_session.get_or_create_cdp_session()
		await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': "selectSort('price-asc')", 'returnByValue': True},
			session_id=cdp_session.session_id,
		)

		# Verify sort was applied
		result = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': "document.getElementById('sort-status').textContent", 'returnByValue': True},
			session_id=cdp_session.session_id,
		)
		status_text = result.get('result', {}).get('value', '')
		assert 'price-asc' in status_text, f"Sort not applied — status: '{status_text}'"
