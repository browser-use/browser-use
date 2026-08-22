"""Verify the eval image end to end without spending any LLM credits.

Serves the hermetic site, attaches to whichever browser backend is configured, navigates,
and reads the DOM back. Exits non-zero on any failure.

    docker run --rm --shm-size=2g -e BU_EVAL_CMD='python eval/smoke_test.py' browseruse-eval
"""

import asyncio
import os
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(EVAL_DIR))

from run_eval import build_browser  # noqa: E402


def serve(port: int) -> None:
	handler = partial(SimpleHTTPRequestHandler, directory=str(EVAL_DIR / 'site'))
	handler.log_message = lambda *a, **k: None  # type: ignore[attr-defined]
	server = ThreadingHTTPServer(('0.0.0.0', port), handler)
	threading.Thread(target=server.serve_forever, daemon=True).start()


async def main() -> int:
	from browser_use.browser.events import NavigateToUrlEvent

	site_url = os.getenv('EVAL_SITE_URL', 'http://127.0.0.1:8000')
	port = int(site_url.rsplit(':', 1)[-1])
	serve(port)
	print(f'[smoke] serving hermetic site on {site_url}')

	backend = os.getenv('BU_EVAL_BROWSER', 'local')
	prewarmed = os.getenv('BU_CDP_URL')
	print(f'[smoke] browser backend={backend} prewarmed_cdp={prewarmed or "none"}')

	session, owns_browser = build_browser()

	t0 = time.perf_counter()
	await session.start()
	start_seconds = time.perf_counter() - t0
	print(f'[smoke] session ready in {start_seconds:.3f}s (owns_browser={owns_browser})')

	try:
		await session.event_bus.dispatch(NavigateToUrlEvent(url=f'{site_url}/catalog.html'))

		t1 = time.perf_counter()
		state = await session.get_browser_state_summary()
		observe_seconds = time.perf_counter() - t1

		title = await session.get_current_page_title()
		dom_state = getattr(state, 'dom_state', None)
		element_count = len(dom_state.selector_map) if dom_state else 0
		print(f'[smoke] url={state.url!r}  title={title!r}  interactive_elements={element_count}  observe={observe_seconds:.3f}s')

		if not state.url.endswith('/catalog.html'):
			print(f'[smoke] FAIL: navigation did not land, url={state.url!r}')
			return 1
		if element_count < 1:
			print('[smoke] FAIL: no interactive elements found in the DOM')
			return 1
		# Known issue: BrowserSession reports the cached target title, which Chrome seeds
		# with the URL and does not always refresh, so this is a warning not a failure.
		if 'Product catalog' not in (title or ''):
			print(f'[smoke] WARN: page title reported as {title!r}, expected the document title')

	finally:
		await (session.kill() if owns_browser else session.stop())

	print('[smoke] PASS: browser, CDP, navigation and DOM extraction all working')
	return 0


if __name__ == '__main__':
	sys.exit(asyncio.run(main()))
