"""Page.captureScreenshot with the hidden-tab fallback, for the agent's REPL worker and for the CLI and --cli-mcp."""

import functools
from collections.abc import Callable

CDP_TIMEOUT_S = 20.0  # bu-pi cdp timeout; 30s/60s waits made each stall cost more (v1b: 114 Hard timeouts)
SCREENSHOT_TIMEOUT_S = 60.0  # browser-harness's own screenshot timeout: cloud screenshots routinely take longer
HIDDEN_CAPTURE_TRY_S = 10.0  # a hidden tab's first capture try; Linux headless never answers it


def capture(raw_cdp, current_tab, session_id=None, *, activate: bool | Callable[[], bool] = False, frozen=False, **params):
	"""Page.captureScreenshot. new_tab()/switch_tab() never activate a tab, and on Linux headless a hidden tab renders
	no frames, so its capture hangs. A hidden attached tab gets a short first try; only when that times out is it
	activated (made Chrome's visible tab) and captured again. A hidden tab that captures (macOS, headful Chrome) is
	never activated: local mode does not switch the user's visible tab. activate=True (a cloud browser: ours, and it
	never answers a hidden tab's capture) activates a hidden tab without the first try; a callable activate is asked only
	for a hidden tab. frozen: a JS dialog is open (cdp()), so the page answers no visibility probe either (its 5 s took
	screenshot() to 7 s): capture as is."""
	timeout = params.pop('_response_timeout', SCREENSHOT_TIMEOUT_S)
	hidden = False
	if session_id is None and not frozen:  # the attached tab; another session's target is unknown here
		try:
			r = raw_cdp('Runtime.evaluate', expression='document.visibilityState', returnByValue=True, _response_timeout=5)
			hidden = r['result'].get('value') == 'hidden'
		except Exception:  # unknown: capture as for a visible tab
			pass
	if not hidden:
		return raw_cdp('Page.captureScreenshot', session_id, _response_timeout=timeout, **params)
	if not (activate() if callable(activate) else activate):
		try:
			return raw_cdp('Page.captureScreenshot', _response_timeout=min(timeout, HIDDEN_CAPTURE_TRY_S), **params)
		except TimeoutError:
			pass
	raw_cdp('Target.activateTarget', targetId=current_tab()['targetId'])
	return raw_cdp('Page.captureScreenshot', _response_timeout=timeout, **params)


def install() -> None:
	"""Route browser_harness.helpers.cdp's Page.captureScreenshot (capture_screenshot() uses it) through capture(), before
	a namespace star-imports the helpers. The CLI and --cli-mcp called the bare helper: a background tab of a headless
	Chromium stalled 10 s or timed out at 60 s (win-cli-5). Every other method waits CDP_TIMEOUT_S unless the caller
	passes _response_timeout, as the agent's cdp() does: browser-harness's 5 s failed 5-8% of MCP devices on a click or
	a navigation (_IPCResponseTimeout). A JS dialog freezes the page: while the daemon saw one open, a page call gets
	DIALOG_PROBE_S, and a call that times out with one open says so, as the agent's cdp() does. Idempotent."""
	from browser_harness import admin, helpers

	raw_cdp = helpers.cdp
	if getattr(raw_cdp, '__bu_hidden_capture__', False):
		return

	def on_cloud() -> bool:  # as the worker's activate=cloud: a cloud tab's first try waited 10 s on every new_tab()
		return admin.daemon_browser_kind(admin.NAME) == 'cloud'

	@functools.wraps(raw_cdp)
	def cdp(method, session_id=None, **params):
		if method == 'Page.captureScreenshot':
			return capture(raw_cdp, helpers.current_tab, session_id, activate=on_cloud, **params)
		from browser_use.repl.worker import DIALOG_PROBE_S, FROZEN_BY_DIALOG

		def pending_dialog() -> dict | None:
			if session_id is not None or not (method in FROZEN_BY_DIALOG or method.startswith('Input.')):
				return None
			try:
				return helpers._send({'meta': 'pending_dialog'}).get('dialog')
			except Exception:  # an older daemon, or none
				return None

		dialog = pending_dialog()
		timeout = params.pop('_response_timeout', CDP_TIMEOUT_S)
		try:
			return raw_cdp(method, session_id, _response_timeout=min(timeout, DIALOG_PROBE_S) if dialog else timeout, **params)
		except TimeoutError:
			if not (dialog := dialog or pending_dialog()):
				raise
			raise RuntimeError(
				f'A JavaScript {dialog.get("type") or "dialog"} is open ({str(dialog.get("message", ""))[:200]!r}): the '
				'page is frozen until it is handled. Accept or dismiss it: cdp("Page.handleJavaScriptDialog", accept=True) '
				'(or accept=False; promptText="..." for a prompt).'
			) from None

	cdp.__bu_hidden_capture__ = True  # type: ignore[attr-defined]
	helpers.cdp = cdp
