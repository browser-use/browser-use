from typing import TYPE_CHECKING


class MissingAPIKeyError(RuntimeError):
	"""No usable Browser Use API key for the default model or the default cloud browser."""

	def __init__(self, what: str = 'Browser Use Cloud', reason: str | None = None):
		if reason:  # a key store that exists but cannot be read
			super().__init__(f'{what} needs a Browser Use API key. {reason}')
			return
		super().__init__(
			f'{what} needs a Browser Use API key. Get one at https://cloud.browser-use.com/new-api-key and set '
			'BROWSER_USE_API_KEY (or run `browser-use login`). No key: '
			"use a local browser and your own model: Agent(task, llm=ChatOpenAI(...), browser=Browser('chromium'))."
		)


class BrowserConfigError(ValueError):
	"""A Browser option that names nothing (a Chrome or cloud profile), found as the browser starts, before any browser
	runs or is billed: Agent.run() raises it as it raises other configuration errors."""


class BrowserConnectionLost(ConnectionError):
	"""The browser-harness daemon that drives the browser is gone (it crashed or was killed)."""

	def __init__(self, why: str = 'the browser-harness daemon is not running') -> None:
		super().__init__(f'browser connection lost: {why}')


ISSUES_URL = 'https://github.com/browser-use/browser-use/issues'
MIGRATING_URL = 'https://github.com/browser-use/browser-use/blob/main/MIGRATING.md'


def removed(feature: str, instead: str = '') -> str:
	"""The one error text for a 0.x feature 1.0 dropped (MIGRATING.md "Removed in 1.0"), with the 1.0 alternative."""
	return (
		f'{feature} was removed in browser-use 1.0. Open an issue at {ISSUES_URL} if you need it.'
		+ (f' In 1.0: {instead}' if instead else '')
		+ f' Migration guide: {MIGRATING_URL}'
	)


if not TYPE_CHECKING:  # pyright would accept any name imported from here
	from browser_use.legacy import removed_names

	__getattr__ = removed_names(__name__)  # a 0.x name raises the removed error naming its 1.0 answer
