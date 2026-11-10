"""page_info() that waits for a new document's <html> element (cli-1).

DELETE this module and its uses (repl/worker.py, mcp/cli_mcp.py, cli.py) once browser-harness pins a page_info() that
waits for or null-guards document.documentElement.

new_tab(url) and goto_url(url) return when Page.navigate does: the new document has committed, but until its first bytes
are parsed it has no <html> element. browser-harness 0.1.13's page_info() reads document.documentElement.scrollWidth, so
the documented first example `new_tab(url); print(page_info())` failed about half the time on local Chromium with
"Cannot read properties of null (reading 'scrollWidth')" (every time on a server slow to send the body). This waits up
to ROOT_WAIT_S for <html>; a body later than that still raises the same error, and calling page_info() again retries.
"""

import functools
import time

ROOT_WAIT_S = 5.0
NO_ROOT = "of null (reading 'scroll"  # V8's TypeError for document.documentElement.scrollWidth/scrollHeight on null


def install() -> None:
	"""Replace browser_harness.helpers.page_info, before a namespace star-imports the helpers. Idempotent."""
	from browser_harness import helpers

	original = helpers.page_info
	if getattr(original, '__bu_waits_for_root__', False):
		return

	@functools.wraps(original)
	def page_info():
		# Retry page_info() itself, not a probe of our own: each try checks for a dialog first, so a page that opens an
		# alert() as it loads returns {dialog} instead of timing out on an evaluate the open dialog blocks.
		deadline = time.monotonic() + ROOT_WAIT_S
		while True:
			try:
				return original()
			except RuntimeError as e:
				if NO_ROOT not in str(e) or time.monotonic() >= deadline:
					raise
			time.sleep(0.05)

	page_info.__bu_waits_for_root__ = True  # type: ignore[attr-defined]
	helpers.page_info = page_info
