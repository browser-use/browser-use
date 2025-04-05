import logging
import os
from typing import List, Optional

import aiohttp
from patchright.async_api import Page, async_playwright

from browser_use.browser.service import Browser
from browser_use.browser.views import BrowserState, TabInfo

logger = logging.getLogger(__name__)


class DolphinBrowser(Browser):
	"""A class for managing Dolphin Anty browser sessions using Playwright"""

	def __init__(self, headless: bool = False, keep_open: bool = False):
		"""
		Initialize the DolphinBrowser instance.

		Args:
		    headless (bool): Run browser in headless mode (default: False).
		    keep_open (bool): Keep browser open after finishing tasks (default: False).
		"""
		# Retrieve environment variables for API connection
		self.api_token = os.getenv('DOLPHIN_API_TOKEN')
		self.api_url = os.getenv('DOLPHIN_API_URL', 'http://localhost:3001/v1.0')
		self.profile_id = os.getenv('DOLPHIN_PROFILE_ID')

		# Initialize internal attributes
		self.playwright = None
		self.browser = None
		self.context = None
		self.page = None
		self.headless = headless
		self.keep_open = keep_open
		self._pages: List[Page] = []  # List to store open pages
		self.session = None
		self.cached_state = None

	async def get_current_page(self) -> Page:
		"""
		Get the currently active page.

		Raises:
		    Exception: If no active page is available.
		"""
		if not self.page:
			raise Exception('No active page. Browser might not be connected.')
		return self.page

	async def create_new_tab(self, url: str | None = None) -> None:
		"""
		Create a new tab and optionally navigate to a given URL.

		Args:
		    url (str, optional): URL to navigate to after creating the tab. Defaults to None.

		Raises:
		    Exception: If browser context is not initialized or navigation fails.
		"""
		if not self.context:
			raise Exception('Browser context not initialized')

		# Create new page (tab) in the current browser context
		new_page = await self.context.new_page()
		self._pages.append(new_page)
		self.page = new_page  # Set as current page

		if url:
			try:
				# Navigate to the URL and wait for the page to load
				await new_page.goto(url, wait_until='networkidle')
				await self.wait_for_page_load()
			except Exception as e:
				logger.error(f'Failed to navigate to URL {url}: {str(e)}')
				raise

	async def switch_to_tab(self, page_id: int) -> None:
		"""
		Switch to a specific tab by its page ID.

		Args:
		    page_id (int): The index of the tab to switch to.

		Raises:
		    Exception: If the tab index is out of range or no tabs are available.
		"""
		if not self._pages:
			raise Exception('No tabs available')

		# Handle negative indices (e.g., -1 for last tab)
		if page_id < 0:
			page_id = len(self._pages) + page_id

		if page_id >= len(self._pages) or page_id < 0:
			raise Exception(f'Tab index {page_id} out of range')

		# Set the current page to the selected tab
		self.page = self._pages[page_id]
		await self.page.bring_to_front()  # Bring tab to the front
		await self.wait_for_page_load()

	async def get_tabs_info(self) -> list[TabInfo]:
		"""
		Get information about all open tabs.

		Returns:
		    list: A list of TabInfo objects containing details about each tab.
		"""
		tabs_info = []
		for idx, page in enumerate(self._pages):
			tab_info = TabInfo(
				page_id=idx,
				url=page.url,
				title=await page.title(),  # Fetch the title of the page
			)
			tabs_info.append(tab_info)
		return tabs_info

	async def wait_for_page_load(self, timeout: int = 30000):
		"""
		Wait for the page to load completely.

		Args:
		    timeout (int): Maximum time to wait for page load in milliseconds (default: 30000ms).

		Raises:
		    Exception: If the page fails to load within the specified timeout.
		"""
		if self.page:
			try:
				await self.page.wait_for_load_state('networkidle', timeout=timeout)
			except Exception as e:
				logger.warning(f'Wait for page load timeout: {str(e)}')

	async def get_session(self):
		"""
		Get the current session.

		Returns:
		    DolphinBrowser: The current DolphinBrowser instance.

		Raises:
		    Exception: If the browser is not connected.
		"""
		if not self.browser:
			raise Exception('Browser not connected. Call connect() first.')
		self.session = self
		return self

	async def authenticate(self):
		"""
		Authenticate with Dolphin Anty API using the API token.

		Raises:
		    Exception: If authentication fails.
		"""
		async with aiohttp.ClientSession() as session:
			auth_url = f'{self.api_url}/auth/login-with-token'
			auth_data = {'token': self.api_token}
			async with session.post(auth_url, json=auth_data) as response:
				if not response.ok:
					raise Exception(f'Failed to authenticate with Dolphin Anty: {await response.text()}')
				return await response.json()

	async def get_browser_profiles(self):
		"""
		Get a list of available browser profiles from Dolphin Anty.

		Returns:
		    list: A list of browser profiles.

		Raises:
		    Exception: If fetching the browser profiles fails.
		"""
		# Authenticate before fetching profiles
		await self.authenticate()

		async with aiohttp.ClientSession() as session:
			headers = {'Authorization': f'Bearer {self.api_token}'}
			async with session.get(f'{self.api_url}/browser_profiles', headers=headers) as response:
				if not response.ok:
					raise Exception(f'Failed to get browser profiles: {await response.text()}')
				data = await response.json()
				return data.get('data', [])  # Return the profiles array from the response

	async def start_profile(self, profile_id: Optional[str] = None, headless: bool = False) -> dict:
		"""
		Start a browser profile on Dolphin Anty.

		Args:
		    profile_id (str, optional): Profile ID to start (defaults to the one set in the environment).
		    headless (bool): Run browser in headless mode (default: False).

		Returns:
		    dict: Information about the started profile.

		Raises:
		    ValueError: If no profile ID is provided and no default is set.
		    Exception: If starting the profile fails.
		"""
		# Authenticate before starting the profile
		await self.authenticate()

		profile_id = profile_id or self.profile_id
		if not profile_id:
			raise ValueError('No profile ID provided')

		url = f'{self.api_url}/browser_profiles/{profile_id}/start'
		params = {'automation': 1}
		if headless:
			params['headless'] = 1

		async with aiohttp.ClientSession() as session:
			async with session.get(url, params=params) as response:
				if not response.ok:
					raise Exception(f'Failed to start profile: {await response.text()}')
				return await response.json()

	async def stop_profile(self, profile_id: Optional[str] = None):
		"""
		Stop a browser profile on Dolphin Anty.

		Args:
		    profile_id (str, optional): Profile ID to stop (defaults to the one set in the environment).

		Returns:
		    dict: Information about the stopped profile.

		Raises:
		    ValueError: If no profile ID is provided and no default is set.
		"""
		# Authenticate before stopping the profile
		await self.authenticate()

		profile_id = profile_id or self.profile_id
		if not profile_id:
			raise ValueError('No profile ID provided')

		url = f'{self.api_url}/browser_profiles/{profile_id}/stop'
		async with aiohttp.ClientSession() as session:
			async with session.get(url) as response:
				return await response.json()

	async def connect(self, profile_id: Optional[str] = None):
		"""
		Connect to a running browser profile using Playwright.

		Args:
		    profile_id (str, optional): Profile ID to connect to (defaults to the one set in the environment).

		Returns:
		    PlaywrightBrowser: The connected browser instance.

		Raises:
		    Exception: If authentication or profile connection fails.
		"""
		# Authenticate before connecting to the profile
		await self.authenticate()

		# Start the browser profile
		profile_data = await self.start_profile(profile_id)

		if not profile_data.get('success'):
			raise Exception(f'Failed to start profile: {profile_data}')

		automation = profile_data['automation']
		port = automation['port']
		ws_endpoint = automation['wsEndpoint']
		ws_url = f'ws://127.0.0.1:{port}{ws_endpoint}'

		# Use Playwright to connect to the browser's WebSocket endpoint
		self.playwright = await async_playwright().start()
		self.browser = await self.playwright.chromium.connect_over_cdp(ws_url)

		# Get or create a browser context and page
		contexts = self.browser.contexts
		self.context = contexts[0] if contexts else await self.browser.new_context()
		pages = self.context.pages
		self.page = pages[0] if pages else await self.context.new_page()

		self._pages = [self.page]  # Initialize pages list with the first page

		return self.browser

	async def close(self, force: bool = False):
		"""
		Close the browser connection and clean up resources.

		Args:
		    force (bool): If True, forcefully stop the associated profile (default: False).
		"""
		try:
			# Close all open pages
			if self._pages:
				for page in self._pages:
					try:
						await page.close()
					except BaseException:
						pass
				self._pages = []

			# Close the browser and Playwright instance
			if self.browser:
				await self.browser.close()

			if self.playwright:
				await self.playwright.stop()

			if force:
				await self.stop_profile()  # Force stop the profile
		except Exception as e:
			logger.error(f'Error during browser cleanup: {str(e)}')

	async def get_current_state(self) -> BrowserState:
		"""
		Get the current state of the browser (URL, content, viewport size, tabs).

		Returns:
		    BrowserState: The current state of the browser.

		Raises:
		    Exception: If no active page is available.
		"""
		if not self.page:
			raise Exception('No active page')

		# Get page content and viewport size
		content = await self.page.content()
		viewport_size = await self.page.viewport_size()

		# Create and return the current browser state
		state = BrowserState(
			url=self.page.url,
			content=content,
			viewport_height=viewport_size['height'] if viewport_size else 0,
			viewport_width=viewport_size['width'] if viewport_size else 0,
			tabs=await self.get_tabs_info(),
		)

		# Cache and return the state
		self.cached_state = state
		return state

	def __del__(self):
		"""Clean up resources when the DolphinBrowser instance is deleted."""
		# No need to handle session cleanup as we're using self as session
		pass
