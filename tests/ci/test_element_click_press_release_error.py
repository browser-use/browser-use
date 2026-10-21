"""Regression test for https://github.com/browser-use/browser-use/issues/6173.

When the mouse press fails (e.g. its 1s ``wait_for`` times out) AND the release
in the ``finally`` block also raises, Python replaces the in-flight press
exception with the release exception, so ``Element.click`` reports only the
release error (e.g. ``ConnectionError: WebSocket connection closed``) and the
press failure is hidden.

Reproducer (from the issue reporter): drives the real ``cdp_use`` CDPClient
against a local websocket endpoint that answers geometry like Chrome, never
answers ``mousePressed``, and closes the connection on ``mouseReleased``.
No browser is needed.
"""

import json
from types import SimpleNamespace

import pytest
import websockets
from cdp_use.client import CDPClient

from browser_use.actor.element import Element

VIEWPORT = {'pageX': 0, 'pageY': 0, 'clientWidth': 800, 'clientHeight': 600}


async def browser(ws):
	async for raw in ws:
		msg = json.loads(raw)
		method, params = msg['method'], msg.get('params', {})
		if method == 'Input.dispatchMouseEvent' and params.get('type') == 'mousePressed':
			continue  # the page is busy: no reply
		if method == 'Input.dispatchMouseEvent' and params.get('type') == 'mouseReleased':
			await ws.close()  # the browser connection is lost
			return
		result = {}
		if method == 'Page.getLayoutMetrics':
			visual = {**VIEWPORT, 'offsetX': 0, 'offsetY': 0, 'scale': 1, 'zoom': 1}
			size = {'x': 0, 'y': 0, 'width': 800, 'height': 600}
			result = {
				'layoutViewport': VIEWPORT,
				'visualViewport': visual,
				'contentSize': size,
				'cssLayoutViewport': VIEWPORT,
				'cssVisualViewport': visual,
				'cssContentSize': size,
			}
		elif method == 'DOM.getContentQuads':
			result = {'quads': [[10, 10, 20, 10, 20, 20, 10, 20]]}
		await ws.send(json.dumps({'id': msg['id'], 'result': result}))


@pytest.mark.asyncio
async def test_press_failure_is_propagated():
	async with websockets.serve(browser, '127.0.0.1', 0) as server:
		client = CDPClient(f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}')
		await client.start()
		try:
			element = Element(browser_session=SimpleNamespace(cdp_client=client), backend_node_id=1, session_id='s1')
			with pytest.raises(RuntimeError) as exc_info:
				await element.click()
		finally:
			await client.stop()
	assert 'TimeoutError' in str(exc_info.value), f'the press timeout was replaced: {exc_info.value}'
	# The release failure must not be lost either: it is attached as a note.
	notes = getattr(exc_info.value.__cause__, '__notes__', [])
	assert any('WebSocket connection closed' in note for note in notes), notes
