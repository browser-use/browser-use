"""Test remote browser download support.

When download_from_remote_browser is True and using a remote browser (is_local=False),
downloads are fetched in-browser and saved to the agent's local filesystem.
"""


from browser_use.browser.profile import BrowserProfile


def test_browser_profile_accepts_download_from_remote_browser():
	"""BrowserProfile accepts download_from_remote_browser flag."""
	profile = BrowserProfile(download_from_remote_browser=True)
	assert profile.download_from_remote_browser is True

	profile_default = BrowserProfile()
	assert profile_default.download_from_remote_browser is False


async def test_download_from_remote_browser_flag_flows_to_session(browser_session, mock_llm):
	"""When creating Browser with download_from_remote_browser=True, the profile has the flag set."""
	from browser_use import Agent
	from browser_use.browser import BrowserSession
	from browser_use.browser.profile import BrowserProfile

	profile = BrowserProfile(headless=True, user_data_dir=None, download_from_remote_browser=True)
	session = BrowserSession(browser_profile=profile)
	await session.start()
	try:
		assert session.browser_profile.download_from_remote_browser is True
		agent = Agent(task='test', llm=mock_llm, browser_session=session)
		assert agent.browser_session.browser_profile.download_from_remote_browser is True
	finally:
		await session.kill()
