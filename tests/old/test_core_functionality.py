import pytest
from langchain_openai import ChatOpenAI
from pytest_httpserver import HTTPServer

from browser_use import setup_logging

setup_logging()

from browser_use.agent.service import Agent
from browser_use.agent.views import AgentHistoryList
from browser_use.browser import BrowserSession


class TestCoreFunctionality:
	"""Tests for core functionality of the Agent using real browser instances."""

	@pytest.fixture(scope='session')
	def http_server(self):
		"""Create and provide a test HTTP server that serves static content."""
		server = HTTPServer()
		server.start()

		# Add routes for common test pages
		server.expect_request('/').respond_with_data(
			'<html><head><title>Test Home Page</title></head><body><h1>Test Home Page</h1><p>Welcome to the test site</p></body></html>',
			content_type='text/html',
		)

		server.expect_request('/page1').respond_with_data(
			'<html><head><title>Test Page 1</title></head><body><h1>Test Page 1</h1><p>This is test page 1</p><a href="/page2">Link to Page 2</a></body></html>',
			content_type='text/html',
		)

		server.expect_request('/page2').respond_with_data(
			'<html><head><title>Test Page 2</title></head><body><h1>Test Page 2</h1><p>This is test page 2</p><a href="/page1">Back to Page 1</a></body></html>',
			content_type='text/html',
		)

		server.expect_request('/search').respond_with_data(
			"""
            <html>
            <head><title>Search Results</title></head>
            <body>
                <h1>Search Results</h1>
                <form>
                    <input type="text" id="search-box" placeholder="Search...">
                    <button type="submit">Search</button>
                </form>
                <div class="results">
                    <div class="result">Result 1</div>
                    <div class="result">Result 2</div>
                    <div class="result">Result 3</div>
                </div>
            </body>
            </html>
            """,
			content_type='text/html',
		)

		yield server
		server.stop()

	@pytest.fixture(scope='session')
	def base_url(self, http_server):
		"""Return the base URL for the test HTTP server."""
		return f'http://{http_server.host}:{http_server.port}'

	@pytest.fixture(scope='module')
	async def browser_session(self):
		"""Create and provide a BrowserSession instance with security disabled."""
		from browser_use.browser.profile import BrowserProfile

		profile = BrowserProfile(headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=profile)
		yield browser_session
		await browser_session.kill()

	@pytest.fixture(scope='module')
	def llm(self):
		"""Initialize language model for testing with minimal settings."""
		return ChatOpenAI(
			model='gpt-4o',
			temperature=0.0,
		)

	async def test_search_google(self, llm, browser_session, base_url):
		"""Test 'Search Google' action using a mock search page."""
		agent = Agent(
			task=f"Go to '{base_url}/search' and search for 'OpenAI'.",
			llm=llm,
			browser_session=browser_session,
		)
		history: AgentHistoryList = await agent.run(max_steps=3)
		action_names = history.action_names()
		assert 'go_to_url' in action_names
		assert any('input_text' in action or 'click_element_by_index' in action for action in action_names)

	async def test_go_to_url(self, llm, browser_session, base_url):
		"""Test 'Navigate to URL' action."""
		agent = Agent(
			task=f"Navigate to '{base_url}/page1'.",
			llm=llm,
			browser_session=browser_session,
		)
		history = await agent.run(max_steps=2)
		action_names = history.action_names()
		assert 'go_to_url' in action_names

		# Verify we're on the correct page
		page = await browser_session.get_current_page()
		assert f'{base_url}/page1' in page.url

	async def test_go_back(self, llm, browser_session, base_url):
		"""Test 'Go back' action."""
		# First navigate to page1, then to page2, then go back
		agent = Agent(
			task=f"Go to '{base_url}/page1', then go to '{base_url}/page2', then go back.",
			llm=llm,
			browser_session=browser_session,
		)
		history = await agent.run(max_steps=4)
		action_names = history.action_names()
		assert 'go_to_url' in action_names
		assert 'go_back' in action_names

		# Verify we're back on page1
		page = await browser_session.get_current_page()
		assert f'{base_url}/page1' in page.url

	async def test_click_element(self, llm, browser_session, base_url):
		"""Test 'Click element' action."""
		agent = Agent(
			task=f"Go to '{base_url}/page1' and click on the link to Page 2.",
			llm=llm,
			browser_session=browser_session,
		)
		history = await agent.run(max_steps=3)
		action_names = history.action_names()
		assert 'go_to_url' in action_names
		assert 'click_element_by_index' in action_names

		# Verify we're now on page2 after clicking the link
		page = await browser_session.get_current_page()
		assert f'{base_url}/page2' in page.url

	async def test_input_text(self, llm, browser_session, base_url):
		"""Test 'Input text' action."""
		agent = Agent(
			task=f"Go to '{base_url}/search' and input 'OpenAI' into the search box.",
			llm=llm,
			browser_session=browser_session,
		)
		history = await agent.run(max_steps=3)
		action_names = history.action_names()
		assert 'go_to_url' in action_names
		assert 'input_text' in action_names

		# Verify text was entered in the search box
		page = await browser_session.get_current_page()
		search_value = await page.evaluate("document.getElementById('search-box').value")
		assert 'OpenAI' in search_value

	async def test_switch_tab(self, llm, browser_session, base_url):
		"""Test 'Switch tab' action."""
		agent = Agent(
			task=f"Open '{base_url}/page1' in the current tab, then open a new tab with '{base_url}/page2', then switch back to the first tab.",
			llm=llm,
			browser_session=browser_session,
		)
		history = await agent.run(max_steps=4)
		action_names = history.action_names()
		assert 'go_to_url' in action_names
		assert 'open_tab' in action_names
		assert 'switch_tab' in action_names

		# Verify we're back on the first tab with page1
		page = await browser_session.get_current_page()
		assert f'{base_url}/page1' in page.url

	async def test_open_new_tab(self, llm, browser_session, base_url):
		"""Test 'Open new tab' action."""
		agent = Agent(
			task=f"Open a new tab and go to '{base_url}/page2'.",
			llm=llm,
			browser_session=browser_session,
		)
		history = await agent.run(max_steps=2)
		action_names = history.action_names()
		assert 'open_tab' in action_names

		# Verify we have at least two tabs
		tabs_info = await browser_session.get_tabs_info()
		assert len(tabs_info) >= 2

		# Verify the current page is page2
		page = await browser_session.get_current_page()
		assert f'{base_url}/page2' in page.url

	async def test_extract_page_content(self, llm, browser_session, base_url):
		"""Test 'Extract page content' action."""
		agent = Agent(
			task=f"Go to '{base_url}/page1' and extract the page content.",
			llm=llm,
			browser_session=browser_session,
		)
		history = await agent.run(max_steps=3)
		action_names = history.action_names()
		assert 'go_to_url' in action_names
		assert 'extract_content' in action_names

		# Verify the extracted content includes some expected text
		extracted_content = None
		for action_result in history.history[-1].result:
			if action_result.extracted_content and 'This is test page 1' in action_result.extracted_content:
				extracted_content = action_result.extracted_content
				break

		assert extracted_content is not None, 'Expected content not found in extraction'

	async def test_done_action(self, llm, browser_session, base_url):
		"""Test 'Complete task' action."""
		agent = Agent(
			task=f"Navigate to '{base_url}/page1' and signal that the task is done.",
			llm=llm,
			browser_session=browser_session,
		)
		history = await agent.run(max_steps=3)
		action_names = history.action_names()
		assert 'go_to_url' in action_names
		assert 'done' in action_names

		# Verify the task was marked as successful
		assert history.is_successful()

	async def test_scroll_down(self, llm, browser_session, base_url, http_server):
		"""Test 'Scroll down' action and validate that the page actually scrolled."""
		# Create a test page with scrollable content
		http_server.expect_request('/scroll-test').respond_with_data(
			"""
            <html>
            <head><title>Scroll Test</title>
            <style>
                body { height: 3000px; }
                .marker { position: absolute; }
                #top { top: 0; }
                #middle { top: 1000px; }
                #bottom { top: 2000px; }
            </style>
            </head>
            <body>
                <div id="top" class="marker">Top of the page</div>
                <div id="middle" class="marker">Middle of the page</div>
                <div id="bottom" class="marker">Bottom of the page</div>
            </body>
            </html>
            """,
			content_type='text/html',
		)

		agent = Agent(
			task=f"Go to '{base_url}/scroll-test' and scroll down the page.",
			llm=llm,
			browser_session=browser_session,
		)

		# First go to the page
		await agent.run(max_steps=1)
		page = await browser_session.get_current_page()

		# Get initial scroll position
		initial_scroll_position = await page.evaluate('window.scrollY')

		# Execute a few more steps to allow for scrolling
		await agent.run(max_steps=2)

		# Get final scroll position
		final_scroll_position = await page.evaluate('window.scrollY')

		# Verify that scrolling occurred
		assert final_scroll_position > initial_scroll_position, 'Page did not scroll down'

		# Verify the action was executed
		history = agent.state.history
		action_names = history.action_names()
		assert 'scroll_down' in action_names
