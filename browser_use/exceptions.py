from typing import TYPE_CHECKING

KEYS_URL = 'https://cloud.browser-use.com/new-api-key'  # the one link to a new key (the dashboard redirects it)
NO_KEY = {  # key_gate -> how to run without a key
	'web_search': 'No key: leave web_search off; the agent still browses.',
	'cloud_browser': "No key: browser=Browser('chromium') runs a local browser instead.",
}
NO_KEY_MODEL = "No key: Agent(task, llm=ChatOpenAI(...), browser=Browser('chromium')) runs your own model on a local browser."


def keys_url(gate: str | None = None) -> str:
	"""KEYS_URL tagged with where the library sent the user from (ref, gate, version): the dashboard's pageviews can then
	count library traffic. Never a device id or anything about the user; with telemetry off, untagged."""
	from browser_use.utils import get_browser_use_version

	return tagged(KEYS_URL, {'ref': 'bu-lib', **({'gate': gate} if gate else {}), 'v': get_browser_use_version()})


def tagged(url: str, query: dict[str, str]) -> str:
	"""url with query added when telemetry is on. Off (ANONYMIZED_TELEMETRY=false, browser-harness's opt-out), a link
	in an error still told cloud.browser-use.com where the click came from."""
	from urllib.parse import urlencode

	from browser_use.telemetry.service import telemetry

	try:
		if not telemetry().enabled:
			return url
	except Exception:  # - an unreadable setting: the plain link works the same
		return url
	return url + ('&' if '?' in url else '?') + urlencode(query)


class MissingAPIKeyError(RuntimeError):
	"""No usable Browser Use API key for the default model, the default cloud browser or web search. key_gate (what
	needed it: default_model, gateway_model, web_search, cloud_browser) and key_reason (missing, corrupt_store,
	unwritable_store, bad_chars) are enums telemetry sends; never the key."""

	def __init__(
		self, what: str = 'Browser Use Cloud', reason: str | None = None, *, gate: str | None = None, key_reason: str = 'missing'
	):
		self.what, self.key_gate = what, gate
		self.key_reason = key_reason if reason else 'missing'
		if reason:  # a key store that exists but cannot be read, or a key that cannot be sent
			super().__init__(f'{what} needs a Browser Use API key. {reason}')
			return
		super().__init__(missing_key_text(what, gate))

	@property
	def summary(self) -> str:
		"""The first line, for telemetry. A key store's error names the store's path, which scrub keeps outside HOME
		(BH_AUTH_PATH=/srv/<customer>/auth.json): those say only what needed the key and the reason."""
		if self.key_reason in ('corrupt_store', 'unwritable_store'):
			return f'{self.what} needs a Browser Use API key ({self.key_reason})'
		return str(self).splitlines()[0]


def missing_key_text(what: str, gate: str | None, notebook: bool | None = None) -> str:
	"""The fix for a missing key, at most 4 lines: sign in first (fewest steps), then the env var, then the no-key way.
	In a notebook the first line is the one call that signs in from a cell (no terminal, no restart)."""
	import sys

	url, no_key = keys_url(gate), NO_KEY.get(gate or '', NO_KEY_MODEL)
	if notebook if notebook is not None else 'ipykernel' in sys.modules:
		return (
			f'Run `import browser_use; browser_use.login()` in a cell, then run again: {what} needs a Browser Use API key.\n'
			f"Or os.environ['BROWSER_USE_API_KEY'] = '<key>' with a key from {url}\n{no_key}"
		)
	return (
		f'{what} needs a Browser Use API key. Sign in once: `browser-use login` (over SSH or in a container: '
		f'`browser-use login --device-code`).\nOr export BROWSER_USE_API_KEY with a key from {url}\n{no_key}'
	)


class BrowserConfigError(ValueError):
	"""A Browser option that names nothing (a Chrome or cloud profile), or no writable browser-harness dir, found as the
	browser starts, before any browser runs or is billed: Agent.run() raises it as it raises other configuration errors."""


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
