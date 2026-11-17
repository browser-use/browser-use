"""Local-only integration tests: real Chrome, no providers or public network."""

import asyncio
import base64
import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

import pytest
from PIL import Image
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import InvalidStatus

import browser_use.gallery as gallery_module
from browser_use.gallery import HTML, Gallery


def test_gallery_source_and_html_are_ascii():
	# Source scans on Windows may use a legacy default encoding.
	Path(gallery_module.__file__).read_text(encoding='ascii')
	assert HTML.isascii()


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


@pytest.mark.parametrize('failure', ['Emulation.setFocusEmulationEnabled', 'Page.startScreencast'])
async def test_gallery_retries_failed_setup_without_losing_tab_or_session(failure):
	info = {'targetId': 'tab', 'type': 'page', 'title': 'Still open', 'url': 'about:blank'}
	calls = []
	attempts = 0
	cleaned = asyncio.Event()

	async def fake_cdp(ws):
		nonlocal attempts
		async for raw in ws:
			request = json.loads(raw)
			method = request['method']
			calls.append(request)
			result = {}
			if method == 'Target.setDiscoverTargets':
				await ws.send(json.dumps({'method': 'Target.targetCreated', 'params': {'targetInfo': info}}))
			elif method == 'Target.getTargets':
				result = {'targetInfos': [info]}
			elif method == 'Target.attachToTarget':
				attempts += 1
				result = {'sessionId': f'session-{attempts}'}
			if request.get('sessionId') == 'session-1' and method in (failure, 'Page.stopScreencast'):
				await ws.send(json.dumps({'id': request['id'], 'error': {'message': 'transient CDP failure'}}))
				continue
			await ws.send(json.dumps({'id': request['id'], 'result': result}))
			if method == 'Target.detachFromTarget' and request['params']['sessionId'] == 'session-1':
				cleaned.set()
			if method == 'Page.startScreencast' and request.get('sessionId') == 'session-2':
				await ws.send(
					json.dumps(
						{'method': 'Page.screencastFrame', 'sessionId': 'session-2', 'params': {'data': 'frame', 'sessionId': 1}}
					)
				)

	async with serve(fake_cdp, '127.0.0.1', 0) as server:
		port = server.sockets[0].getsockname()[1]
		async with Gallery(f'ws://127.0.0.1:{port}') as gallery:
			await asyncio.wait_for(cleaned.wait(), 3)
			assert gallery.tabs['tab']['title'] == 'Still open'
			async with connect(gallery.url.replace('http:', 'ws:').replace('/?', '/events?')) as viewer:
				await snapshot(viewer, lambda tabs: tabs.get('tab', {}).get('frame') == 'frame')
			assert gallery._sessions == {'session-2': 'tab'}
			assert attempts == 2
			assert any(c['method'] == 'Page.stopScreencast' and c.get('sessionId') == 'session-1' for c in calls)
			assert any(
				c['method'] == 'Emulation.setFocusEmulationEnabled'
				and c.get('sessionId') == 'session-1'
				and c['params'] == {'enabled': False}
				for c in calls
			)


async def test_gallery_detach_clears_last_frame():
	info = {'targetId': 'tab', 'type': 'page', 'title': 'Still open', 'url': 'about:blank'}
	detach = asyncio.Event()

	async def fake_cdp(ws):
		async for raw in ws:
			request = json.loads(raw)
			result = {}
			if request['method'] == 'Target.setDiscoverTargets':
				await ws.send(json.dumps({'method': 'Target.targetCreated', 'params': {'targetInfo': info}}))
			elif request['method'] == 'Target.attachToTarget':
				result = {'sessionId': 'session'}
			await ws.send(json.dumps({'id': request['id'], 'result': result}))
			if request['method'] == 'Page.startScreencast':
				await ws.send(
					json.dumps(
						{'method': 'Page.screencastFrame', 'sessionId': 'session', 'params': {'data': 'old', 'sessionId': 1}}
					)
				)
				await detach.wait()
				await ws.send(json.dumps({'method': 'Target.detachedFromTarget', 'params': {'sessionId': 'session'}}))

	async with serve(fake_cdp, '127.0.0.1', 0) as server:
		port = server.sockets[0].getsockname()[1]
		async with Gallery(f'ws://127.0.0.1:{port}') as gallery:
			async with connect(gallery.url.replace('http:', 'ws:').replace('/?', '/events?')) as viewer:
				await snapshot(viewer, lambda tabs: tabs.get('tab', {}).get('frame') == 'old')
				detach.set()
				await snapshot(viewer, lambda tabs: 'tab' in tabs and not tabs['tab'].get('frame'))
			assert not gallery._sessions


async def test_gallery_stalled_retry_does_not_delay_other_tabs(monkeypatch):
	gallery = Gallery('unused')
	gallery.tabs = {target: {'id': target, 'title': 'Old'} for target in ('stalled', 'later')}
	attempts = []
	refreshed = asyncio.Event()
	polls = 0

	async def call(method, session=None, **params):
		nonlocal polls
		if method == 'Target.getTargets':
			polls += 1
			if polls >= 2:
				refreshed.set()
			return {'targetInfos': [{'targetId': target, 'title': 'New', 'url': 'about:blank'} for target in gallery.tabs]}
		if method == 'Target.attachToTarget':
			target = params['targetId']
			attempts.append(target)
			if target == 'stalled':
				await asyncio.Event().wait()
			return {'sessionId': target}
		return {}

	monkeypatch.setattr(gallery, '_call', call)
	gallery._spawn(gallery._refresh_titles())
	try:
		await asyncio.wait_for(refreshed.wait(), 3)
		# Let the second refresh's attach tasks run to detect duplicate retries.
		await asyncio.sleep(0)
		assert gallery.tabs['later']['title'] == 'New'
		assert gallery._sessions == {'later': 'later'}
		assert attempts == ['stalled', 'later']
	finally:
		await gallery.__aexit__()


async def test_gallery_enlarging_tab_without_frame_clears_previous_image(chrome):
	async with Gallery(chrome['ws']) as gallery, connect(chrome['ws']) as browser:
		cdp = CDP(browser)
		target = (await cdp.call('Target.createTarget', url='about:blank'))['targetId']
		try:
			session = (await cdp.call('Target.attachToTarget', targetId=target, flatten=True))['sessionId']
			await cdp.call('Page.navigate', session, url=gallery.url)
			async with asyncio.timeout(10):
				while True:
					ready = await cdp.call('Runtime.evaluate', session, expression='typeof enlarge === "function"')
					if ready['result'].get('value'):
						break
					await asyncio.sleep(0.05)
			result = await cdp.call(
				'Runtime.evaluate',
				session,
				expression="""(() => {
					const tab = {id:'detached', title:'First', url:'about:blank', frame:'previous'};
					socket.onmessage({data:JSON.stringify({tabs:[tab]})});
					socket.onmessage({data:JSON.stringify({tabs:[{...tab, frame:null}]})});
					const tile = tiles.get(tab.id).querySelector('img').getAttribute('src');
					enlarge(tab);
					const previous = document.querySelector('#detail-img').getAttribute('src');
					enlarge({title:'Second', url:'about:blank'});
					return [previous, document.querySelector('#detail-img').getAttribute('src'), tile];
				})()""",
				returnByValue=True,
			)
			assert result['result']['value'] == ['data:image/jpeg;base64,previous', None, None]
		finally:
			await cdp.call('Target.closeTarget', targetId=target)


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


async def test_gallery_keyboard_enlarge_returns_focus_and_respects_reduced_motion(chrome):
	async with Gallery(chrome['ws']) as gallery, connect(chrome['ws']) as browser:
		cdp = CDP(browser)
		target = (await cdp.call('Target.createTarget', url='about:blank'))['targetId']
		try:
			session = (await cdp.call('Target.attachToTarget', targetId=target, flatten=True))['sessionId']
			await cdp.call('Emulation.setDeviceMetricsOverride', session, width=390, height=844, deviceScaleFactor=1, mobile=True)
			await cdp.call('Page.navigate', session, url=gallery.url)
			async with asyncio.timeout(10):
				while True:
					ready = await cdp.call('Runtime.evaluate', session, expression='typeof openTile === "function"')
					if ready['result'].get('value'):
						break
					await asyncio.sleep(0.05)
			await cdp.call(
				'Runtime.evaluate',
				session,
				expression="""(() => {
					const receive = socket.onmessage;
					socket.onmessage = null;
					receive({data:JSON.stringify({tabs:[{id:'keyboard', title:'A very long title '.repeat(30), url:'https://example.com/path'}]})});
					tiles.get('keyboard').focus();
				})()""",
			)
			await cdp.call(
				'Input.dispatchKeyEvent', session, type='keyDown', key='Enter', code='Enter', windowsVirtualKeyCode=13, text='\r'
			)
			await cdp.call('Input.dispatchKeyEvent', session, type='keyUp', key='Enter', code='Enter', windowsVirtualKeyCode=13)
			opened = await cdp.call('Runtime.evaluate', session, expression='detail.open')
			assert opened['result']['value'] is True
			# Escape during opening must reverse the current animation and restore focus.
			await cdp.call(
				'Input.dispatchKeyEvent', session, type='keyDown', key='Escape', code='Escape', windowsVirtualKeyCode=27
			)
			async with asyncio.timeout(5):
				while True:
					closed = await cdp.call('Runtime.evaluate', session, expression='!detail.open')
					if closed['result'].get('value'):
						break
					await asyncio.sleep(0.05)
			await cdp.call(
				'Emulation.setEmulatedMedia', session, features=[{'name': 'prefers-reduced-motion', 'value': 'reduce'}]
			)
			result = await cdp.call(
				'Runtime.evaluate',
				session,
				expression="""(() => {
					const tile = tiles.get('keyboard');
					const focused = document.activeElement === tile;
					openTile('keyboard');
					const staticOpen = detail.open && raf === 0 && panel.style.transform === 'none'
						&& state.every((value, i) => value === target[i]) && velocity.every(value => value === 0);
					closeDetail();
					const frame = tile.querySelector('.preview').getBoundingClientRect();
					return [focused, staticOpen, !detail.open, document.activeElement === tile,
						document.documentElement.scrollWidth === innerWidth, Math.abs(frame.width / frame.height - 1.6) < .01,
						tile.querySelector('img').getAttribute('src'), tile.getAttribute('aria-label').includes('loading preview'),
						getComputedStyle(tile.querySelector('img')).objectFit === 'contain',
						grid.getAttribute('role') === 'list' && grid.getAttribute('aria-label') === 'Live browser tabs'
							&& tile.parentElement.getAttribute('role') === 'listitem' && tile.parentElement.parentElement === grid];
				})()""",
				returnByValue=True,
			)
			assert result['result']['value'] == [True, True, True, True, True, True, None, True, True, True]
		finally:
			await cdp.call('Target.closeTarget', targetId=target)
