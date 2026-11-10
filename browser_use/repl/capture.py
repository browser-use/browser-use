"""Page.captureScreenshot with the hidden-tab fallback, for the agent's REPL worker and for the CLI and --cli-mcp."""

import functools
from collections.abc import Callable

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
	Chromium stalled 10 s or timed out at 60 s (win-cli-5). Idempotent."""
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
		return raw_cdp(method, session_id, **params)

	cdp.__bu_hidden_capture__ = True  # type: ignore[attr-defined]
	helpers.cdp = cdp
