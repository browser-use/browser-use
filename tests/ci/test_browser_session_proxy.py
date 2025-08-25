import asyncio
from typing import Any

import pytest

from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.config import CONFIG


def test_chromium_args_include_proxy_flags():
	profile = BrowserProfile(
		headless=True,
		user_data_dir=str(CONFIG.BROWSER_USE_PROFILES_DIR / 'proxy-smoke'),
		proxy={
			'server': 'http://proxy.local:8080',
			'bypass': 'localhost,127.0.0.1',
		},
	)
	args = profile.get_args()
	assert any(a == '--proxy-server=http://proxy.local:8080' for a in args), args
	assert any(a == '--proxy-bypass-list=localhost,127.0.0.1' for a in args), args


@pytest.mark.asyncio
async def test_cdp_proxy_auth_handler_registers_and_responds():
	# Create profile with proxy auth credentials
	profile = BrowserProfile(
		headless=True,
		user_data_dir=str(CONFIG.BROWSER_USE_PROFILES_DIR / 'proxy-smoke'),
		proxy={'username': 'user', 'password': 'pass'},
	)
	session = BrowserSession(browser_profile=profile)

	# Stub CDP client with minimal Fetch support
	class StubCDP:
		def __init__(self) -> None:
			self.enabled = False
			self.last_auth: dict[str, Any] | None = None
			self.last_default: dict[str, Any] | None = None
			self.auth_callback = None
			self.request_paused_callback = None

			class _FetchSend:
				def __init__(self, outer: 'StubCDP') -> None:
					self._outer = outer

				async def enable(self, params: dict, session_id: str | None = None) -> None:
					self._outer.enabled = True

				async def continueWithAuth(self, params: dict, session_id: str | None = None) -> None:
					self._outer.last_auth = {'params': params, 'session_id': session_id}

				async def continueRequest(self, params: dict, session_id: str | None = None) -> None:
					# no-op; included to mirror CDP API surface used by impl
					pass

			class _Send:
				def __init__(self, outer: 'StubCDP') -> None:
					self.Fetch = _FetchSend(outer)

			class _FetchRegister:
				def __init__(self, outer: 'StubCDP') -> None:
					self._outer = outer

				def authRequired(self, callback) -> None:
					self._outer.auth_callback = callback

				def requestPaused(self, callback) -> None:
					self._outer.request_paused_callback = callback

			class _Register:
				def __init__(self, outer: 'StubCDP') -> None:
					self.Fetch = _FetchRegister(outer)

			self.send = _Send(self)
			self.register = _Register(self)

	root = StubCDP()

	# Attach stubs to session
	session._cdp_client_root = root  # type: ignore[attr-defined]
	# No need to attach a real CDPSession; _setup_proxy_auth works with root client

	# Should register Fetch handler and enable auth handling without raising
	await session._setup_proxy_auth()

	assert root.enabled is True
	assert callable(root.auth_callback)

	# Simulate proxy auth required event
	ev = {'requestId': 'r1', 'authChallenge': {'source': 'Proxy'}}
	root.auth_callback(ev, session_id='s1')  # type: ignore[misc]

	# Let scheduled task run
	await asyncio.sleep(0.05)

	assert root.last_auth is not None
	params = root.last_auth['params']
	assert params['authChallengeResponse']['response'] == 'ProvideCredentials'
	assert params['authChallengeResponse']['username'] == 'user'
	assert params['authChallengeResponse']['password'] == 'pass'
	assert root.last_auth['session_id'] == 's1'

	# Now simulate a non-proxy auth challenge and ensure default handling
	ev2 = {'requestId': 'r2', 'authChallenge': {'source': 'Server'}}
	root.auth_callback(ev2, session_id='s2')  # type: ignore[misc]
	await asyncio.sleep(0.05)
	# After non-proxy challenge, last_auth should reflect Default response
	assert root.last_auth is not None
	params2 = root.last_auth['params']
	assert params2['requestId'] == 'r2'
	assert params2['authChallengeResponse']['response'] == 'Default'
