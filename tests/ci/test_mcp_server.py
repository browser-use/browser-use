from browser_use.mcp import server as mcp_server


def test_mcp_server_applies_browser_profile_overrides(monkeypatch):
	"""Browser-use CLI overrides should reach the MCP browser profile."""
	monkeypatch.setattr(
		mcp_server,
		'load_browser_use_config',
		lambda: {
			'browser_profile': {
				'headless': True,
			},
			'llm': {},
			'agent': {},
		},
	)

	server = mcp_server.BrowserUseServer(browser_profile_overrides={'cdp_url': 'http://127.0.0.1:9223'})

	assert server.config['browser_profile']['headless'] is True
	assert server.config['browser_profile']['cdp_url'] == 'http://127.0.0.1:9223'


async def test_mcp_browser_session_receives_cdp_url_as_top_level_kwarg(monkeypatch):
	"""CDP URLs must use BrowserSession's top-level cdp_url path."""
	captured_kwargs = {}

	class FakeBrowserSession:
		id = 'fake-session'
		current_url = None

		def __init__(self, **kwargs):
			captured_kwargs.update(kwargs)
			self.id = 'fake-session'
			self.current_url = None

		async def start(self):
			return None

	monkeypatch.setattr(mcp_server, 'BrowserSession', FakeBrowserSession)
	monkeypatch.setattr(
		mcp_server,
		'load_browser_use_config',
		lambda: {
			'browser_profile': {
				'cdp_url': 'http://127.0.0.1:9223',
				'headless': True,
				'user_data_dir': None,
			},
			'llm': {},
			'agent': {},
		},
	)

	server = mcp_server.BrowserUseServer()
	await server._init_browser_session()

	assert captured_kwargs['cdp_url'] == 'http://127.0.0.1:9223'
	assert captured_kwargs['browser_profile'].cdp_url is None
