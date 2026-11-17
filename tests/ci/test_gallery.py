"""Local-only integration tests: real Chrome, no providers or public network."""

import asyncio
import base64
import io
import json
import sys
import urllib.error
import urllib.request
from urllib.parse import quote

import pytest
from PIL import Image
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import InvalidStatus

from browser_use.gallery import Gallery


class CDP:
	def __init__(self, ws):
		self.ws = ws
		self.sequence = 0

	async def call(self, method, session=None, **params):
		self.sequence += 1
		msg = {'id': self.sequence, 'method': method, 'params': params}
		if session:
			msg['sessionId'] = session
		await self.ws.send(json.dumps(msg))
		while True:
			response = json.loads(await self.ws.recv())
			if response.get('id') == self.sequence:
				assert 'error' not in response, response
				return response['result']


async def snapshot(ws, predicate):
	async with asyncio.timeout(15):
		while True:
			tabs = {t['id']: t for t in json.loads(await ws.recv())['tabs']}
			if predicate(tabs):
				return tabs


async def test_view_exits_when_browser_connection_closes():
	close_cdp = asyncio.Event()

	async def fake_cdp(ws):
		request = json.loads(await ws.recv())
		assert request['method'] == 'Target.setDiscoverTargets'
		await ws.send(json.dumps({'id': request['id'], 'result': {}}))
		await close_cdp.wait()
		await ws.close()

	async with serve(fake_cdp, '127.0.0.1', 0) as server:
		port = server.sockets[0].getsockname()[1]
		process = await asyncio.create_subprocess_exec(
			sys.executable,
			'-m',
			'browser_use.cli',
			'view',
			'--cdp-url',
			f'ws://127.0.0.1:{port}',
			stdout=asyncio.subprocess.PIPE,
			stderr=asyncio.subprocess.PIPE,
		)
		try:
			assert process.stdout is not None
			line = await asyncio.wait_for(process.stdout.readline(), 15)
			assert line.startswith(b'Live gallery: '), line
			url = line.decode().strip().removeprefix('Live gallery: ')
			async with connect(url.replace('http:', 'ws:').replace('/?', '/events?')) as viewer:
				await asyncio.wait_for(viewer.recv(), 5)
				close_cdp.set()
				stdout, stderr = await asyncio.wait_for(process.communicate(), 10)
				await asyncio.wait_for(viewer.wait_closed(), 5)
			assert process.returncode != 0
			assert stdout == b''
			assert stderr.decode().splitlines() == ['the browser connection closed']
			with pytest.raises(OSError):
				await asyncio.open_connection('127.0.0.1', int(url.split(':')[2].split('/')[0]))
		finally:
			close_cdp.set()
			if process.returncode is None:
				process.kill()
			await process.wait()


async def test_gallery_streams_every_tab_and_tracks_open_close(chrome, monkeypatch):
	focus_disabled = set()
	original_call = Gallery._call

	async def record_call(self, method, session=None, **params):
		result = await original_call(self, method, session, **params)
		if method == 'Emulation.setFocusEmulationEnabled' and params == {'enabled': False}:
			focus_disabled.add(session)
		return result

	monkeypatch.setattr(Gallery, '_call', record_call)
	async with connect(chrome['ws']) as browser:
		cdp = CDP(browser)
		first = (await cdp.call('Target.createTarget', url='data:text/html,<title>First</title><body style="background:red">'))[
			'targetId'
		]
		second = None
		try:
			async with Gallery(chrome['ws']) as gallery:
				async with connect(gallery.url.replace('http:', 'ws:').replace('/?', '/events?'), max_size=None) as viewer:
					await snapshot(viewer, lambda tabs: tabs.get(first, {}).get('frame'))
					# A new background tab must attach and stream without activating it.
					second = (
						await cdp.call(
							'Target.createTarget', url='data:text/html,<title>Second</title><body style="background:blue">'
						)
					)['targetId']
					tabs = await snapshot(
						viewer,
						lambda tabs: all(tabs.get(t, {}).get('frame') for t in (first, second))
						and tabs[first]['title'] == 'First'
						and tabs[second]['title'] == 'Second',
					)
					assert tabs[first]['title'] == 'First' and tabs[second]['title'] == 'Second'
					for target in (first, second):
						image = Image.open(io.BytesIO(base64.b64decode(tabs[target]['frame'])))
						assert image.format == 'JPEG' and 0 < image.width <= 1000
					# The first tab is backgrounded: a changed frame proves ongoing capture, not just an initial still.
					previous = tabs[first]['frame']
					session = (await cdp.call('Target.attachToTarget', targetId=first, flatten=True))['sessionId']
					await cdp.call(
						'Runtime.evaluate', session, expression='document.body.style.background="lime"; document.title="Updated"'
					)
					await snapshot(
						viewer,
						lambda tabs: tabs[first]['title'] == 'Updated' and tabs[first].get('frame') != previous,
					)
					# Viewer messages never become CDP commands.
					await viewer.send(json.dumps({'method': 'Target.closeTarget', 'params': {'targetId': first}}))
					await cdp.call('Target.closeTarget', targetId=second)
					tabs = await snapshot(viewer, lambda tabs: second not in tabs)
					assert first in tabs
				live_sessions = set(gallery._sessions)
			# Closing the gallery leaves the browser and its tabs alive.
			assert live_sessions and focus_disabled == live_sessions
			assert first in {t['targetId'] for t in (await cdp.call('Target.getTargets'))['targetInfos']}
			assert gallery._reader.done() and not gallery._tasks
		finally:
			live = {t['targetId'] for t in (await cdp.call('Target.getTargets'))['targetInfos']}
			for target in (first, second):
				if target in live:
					await cdp.call('Target.closeTarget', targetId=target)


async def test_gallery_requires_token_for_html_and_websocket(chrome):
	async with Gallery(chrome['ws']) as gallery:
		assert gallery.url.startswith('http://127.0.0.1:')
		assert len(gallery.token) >= 32 and gallery.token != Gallery(chrome['ws']).token
		base = gallery.url.split('?')[0]

		def get(url):
			with urllib.request.urlopen(url, timeout=5) as response:
				return response.headers, response.read().decode()

		for path in ('', '?token=wrong', '?token=' + quote('☃')):
			with pytest.raises(urllib.error.HTTPError) as error:
				await asyncio.to_thread(get, base + path)
			assert error.value.code == 403
		headers, html = await asyncio.to_thread(get, gallery.url)
		assert headers['Cache-Control'] == 'no-store'
		assert headers['Referrer-Policy'] == 'no-referrer'
		assert 'Live gallery' in html
		for query in ('', '?token=wrong'):
			with pytest.raises(InvalidStatus) as error:
				async with connect(base.replace('http:', 'ws:') + 'events' + query):
					pytest.fail('Unauthenticated viewer connected')
			assert error.value.response.status_code == 403
