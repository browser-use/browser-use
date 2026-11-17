"""Opt-in, read-only local gallery. One CDP connection, no browser ownership."""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import secrets
from http import HTTPStatus
from typing import Any
from urllib.parse import parse_qs, urlsplit

from websockets.asyncio.client import connect
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

HTML = r"""<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Browser Use &middot; Live gallery</title>
<style>
:root{color-scheme:dark;font-family:Inter,ui-sans-serif,system-ui,sans-serif;background:#101213;color:#eef1ef}
*{box-sizing:border-box}body{margin:0}header{padding:28px 36px 24px;border-bottom:1px solid #303534;display:flex;align-items:center;justify-content:space-between;gap:16px}
h1{font-size:23px;letter-spacing:-.7px;margin:5px 0 7px;font-weight:550}.brand{font-size:11px;letter-spacing:2px;color:#a0aaa5}
p{margin:0;color:#9ba6a0;font-size:13px}.status{font-size:12px;color:#b9e7bf;background:#203329;padding:8px 12px;border-radius:30px;white-space:nowrap}
.status:before{content:'\25cf';color:#8be7a1;margin-right:7px}main{padding:26px 36px}.toolbar{display:flex;justify-content:space-between;margin-bottom:18px;font-size:12px;color:#99a59e}
#grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}.tile{padding:0;text-align:left;background:#1a1e1c;border:1px solid #39413c;border-radius:12px;overflow:hidden;color:inherit;cursor:zoom-in;font:inherit;min-width:0;box-shadow:0 8px 25px #0002}
.tile:hover{border-color:#8caa96}.info{height:69px;padding:14px 15px;display:flex;gap:12px;align-items:center}.number{font-size:11px;color:#a6bcad;background:#303c34;border-radius:6px;padding:6px}.labels{min-width:0;flex:1}.title{font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:5px}.url{font-size:11px;color:#97a29b;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.expand{color:#8c9b91}
img{width:100%;aspect-ratio:16/10;object-fit:contain;object-position:top;background:#fff;display:block}.tile:has(img:not([src])) img{background:#252d28}
#empty{padding:80px 0;text-align:center;color:#99a59e}dialog{padding:0;border:1px solid #526257;border-radius:14px;background:#1a1e1c;color:#eef1ef;width:min(1180px,95vw);max-height:94vh}dialog::backdrop{background:#060a08df;backdrop-filter:blur(7px)}dialog .info{height:72px}dialog img{max-height:calc(90vh - 72px);aspect-ratio:auto}#close{background:#35463b;color:white;border:0;border-radius:6px;padding:8px 12px;cursor:pointer}
@media(min-width:1700px){#grid{grid-template-columns:repeat(4,minmax(0,1fr))}}@media(max-width:950px){#grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:560px){header{padding:22px 18px;align-items:flex-start}h1{font-size:21px}.status{font-size:10px;padding:7px 9px}header p{max-width:220px;line-height:1.5}main{padding:22px 18px}#grid{grid-template-columns:1fr;gap:16px}.toolbar{font-size:11px}.info{height:65px}}
</style>
<header><div><div class="brand">BROWSER USE / LOCAL</div><h1>Live gallery</h1><p>Every tab. One place to follow the work.</p></div><span class="status" id="status">Connecting</span></header>
<main><div class="toolbar"><span id="count">Waiting for tabs</span><span>Read only &middot; Click a tab to enlarge</span></div><div id="grid"></div><p id="empty">Waiting for browser tabs&hellip;</p></main>
<dialog id="detail"><div class="info"><div class="labels"><div class="title" id="detail-title"></div><div class="url" id="detail-url"></div></div><button id="close">Close &#10005;</button></div><img id="detail-img" alt="Live enlarged tab"></dialog>
<script>
const grid=document.querySelector('#grid'), detail=document.querySelector('#detail'), tiles=new Map();let selected=null;
const socket=new WebSocket(`ws://${location.host}/events${location.search}`);
socket.onopen=()=>document.querySelector('#status').textContent='Live \u00b7 Local';
socket.onclose=()=>{document.querySelector('#status').textContent='Disconnected';document.querySelector('#empty').textContent='Browser connection closed';};
document.querySelector('#close').onclick=()=>detail.close();detail.onclick=e=>{if(e.target===detail)detail.close()};
socket.onmessage=e=>{const {tabs}=JSON.parse(e.data);document.querySelector('#count').textContent=`${tabs.length} open tab${tabs.length===1?'':'s'}`;document.querySelector('#empty').hidden=!!tabs.length;
for(const [id,tile] of tiles)if(!tabs.some(t=>t.id===id)){tile.remove();tiles.delete(id);if(selected===id)detail.close()}
tabs.forEach((tab,i)=>{let tile=tiles.get(tab.id);if(!tile){tile=document.createElement('button');tile.className='tile';tile.innerHTML='<div class="info"><span class="number"></span><div class="labels"><div class="title"></div><div class="url"></div></div><span class="expand">&#8599;</span></div><img alt="Live browser tab">';tile.onclick=()=>{selected=tab.id;enlarge(tab);detail.showModal()};tiles.set(tab.id,tile);grid.append(tile)}tile.querySelector('.number').textContent=String(i+1).padStart(2,'0');tile.querySelector('.title').textContent=tab.title||'Untitled';tile.querySelector('.url').textContent=tab.url;if(tab.frame)tile.querySelector('img').src='data:image/jpeg;base64,'+tab.frame;else tile.querySelector('img').removeAttribute('src');if(selected===tab.id)enlarge(tab)});
};
function enlarge(tab){document.querySelector('#detail-title').textContent=tab.title;document.querySelector('#detail-url').textContent=tab.url;if(tab.frame)document.querySelector('#detail-img').src='data:image/jpeg;base64,'+tab.frame;else document.querySelector('#detail-img').removeAttribute('src')}
</script></html>"""


class Gallery:
	"""Async context manager; start only on an explicit user request. URL carries the bearer token."""

	def __init__(self, ws_url: str):
		self.ws_url = ws_url
		self.token = secrets.token_urlsafe(32)
		self.url = ''
		self.tabs: dict[str, dict[str, Any]] = {}
		self._sessions: dict[str, str] = {}
		self._attaching: set[str] = set()
		self._pending: dict[int, asyncio.Future] = {}
		self._tasks: set[asyncio.Task] = set()
		self._id = 0
		self._server = None
		self._ws: Any = None
		self._reader: asyncio.Task | None = None
		self._failed = False
		self._closing = False

	async def __aenter__(self) -> Gallery:
		try:
			self._ws = await connect(self.ws_url, max_size=8 * 1024 * 1024, open_timeout=10)
			self._reader = asyncio.create_task(self._read())
			await self._call('Target.setDiscoverTargets', discover=True)
			self._spawn(self._refresh_titles())
			host = '127.0.0.1'
			self._server = await serve(self._viewer, host, 0, process_request=self._http, max_size=1024)
			port = next(iter(self._server.sockets)).getsockname()[1]
			self.url = f'http://{host}:{port}/?token={self.token}'
			return self
		except BaseException:
			await self.__aexit__(None, None, None)
			raise

	async def __aexit__(self, *exc) -> None:
		self._closing = True
		if self._server:
			self._server.close()
			await self._server.wait_closed()
		for task in self._tasks:
			task.cancel()
		await asyncio.gather(*self._tasks, return_exceptions=True)
		if self._ws:
			# Detaching our sessions stops their screencasts without closing anyone's tabs.
			for session in list(self._sessions):
				with contextlib.suppress(Exception):
					await self._call('Page.stopScreencast', session)
					await self._call('Emulation.setFocusEmulationEnabled', session, enabled=False)
					await self._call('Target.detachFromTarget', sessionId=session)
			await self._ws.close()
		if self._reader:
			self._reader.cancel()
			await asyncio.gather(self._reader, return_exceptions=True)

	async def _call(self, method: str, session: str | None = None, **params) -> dict:
		self._id += 1
		message = {'id': self._id, 'method': method, 'params': params}
		if session:
			message['sessionId'] = session
		future = asyncio.get_running_loop().create_future()
		self._pending[self._id] = future
		try:
			await self._ws.send(json.dumps(message))
			return await asyncio.wait_for(future, 5)
		finally:
			self._pending.pop(message['id'], None)

	def _spawn(self, coroutine) -> None:
		if self._closing:
			coroutine.close()
			return
		task = asyncio.create_task(coroutine)
		self._tasks.add(task)
		task.add_done_callback(self._tasks.discard)

	async def _refresh_titles(self) -> None:
		# Chrome doesn't emit targetInfoChanged for every document.title change.
		while not self._failed:
			await asyncio.sleep(1)
			try:
				infos = (await self._call('Target.getTargets'))['targetInfos']
				for info in infos:
					if info['targetId'] in self.tabs:
						self.tabs[info['targetId']].update(title=info['title'], url=info['url'])
						self._spawn(self._attach(info['targetId']))
			except Exception:
				return

	async def _attach(self, target: str) -> None:
		if target in self._attaching or target in self._sessions.values():
			return
		self._attaching.add(target)
		session = None
		try:
			session = (await self._call('Target.attachToTarget', targetId=target, flatten=True))['sessionId']
			self._sessions[session] = target
			# Chrome suppresses background screencasts unless the page is treated as focused.
			await self._call('Emulation.setFocusEmulationEnabled', session, enabled=True)
			await self._call('Page.startScreencast', session, format='jpeg', quality=65, maxWidth=1000, maxHeight=700)
		except Exception:
			# A setup error doesn't mean the target closed. Keep the tile and retry on refresh.
			if session:
				for method, params in (
					('Page.stopScreencast', {}),
					('Emulation.setFocusEmulationEnabled', {'enabled': False}),
				):
					with contextlib.suppress(Exception):
						await self._call(method, session, **params)
				with contextlib.suppress(Exception):
					await self._call('Target.detachFromTarget', sessionId=session)
				self._sessions.pop(session, None)
		finally:
			self._attaching.discard(target)

	async def _ack(self, session: str, frame: int) -> None:
		await asyncio.sleep(0.3)  # backpressure on Chrome, not an unbounded queue of JPEGs
		with contextlib.suppress(Exception):
			await self._call('Page.screencastFrameAck', session, sessionId=frame)

	async def _read(self) -> None:
		try:
			async for raw in self._ws:
				msg = json.loads(raw)
				if 'id' in msg:
					future = self._pending.get(msg['id'])
					if future and not future.done():
						if 'error' in msg:
							future.set_exception(RuntimeError(msg['error']['message']))
						else:
							future.set_result(msg.get('result', {}))
					continue
				params, method = msg.get('params', {}), msg.get('method')
				if method in ('Target.targetCreated', 'Target.targetInfoChanged'):
					info = params['targetInfo']
					if info['type'] == 'page':
						target = info['targetId']
						if target not in self.tabs:
							self.tabs[target] = {'id': target}
							self._spawn(self._attach(target))
						self.tabs[target].update(title=info['title'], url=info['url'])
				elif method == 'Target.targetDestroyed':
					target = params['targetId']
					self.tabs.pop(target, None)
					self._sessions = {s: t for s, t in self._sessions.items() if t != target}
				elif method == 'Target.detachedFromTarget':
					target = self._sessions.pop(params['sessionId'], None)
					if target in self.tabs:
						self.tabs[target].pop('frame', None)
				elif method == 'Page.screencastFrame':
					session = msg['sessionId']
					target = self._sessions.get(session)
					if target in self.tabs:
						self.tabs[target]['frame'] = params['data']
					self._spawn(self._ack(session, params['sessionId']))
		except Exception:
			pass
		finally:
			self._failed = True
			for future in self._pending.values():
				if not future.done():
					future.set_exception(ConnectionError('Gallery CDP connection closed'))

	def _http(self, connection, request):
		parsed = urlsplit(request.path)
		token = parse_qs(parsed.query).get('token', [''])[0]
		if not hmac.compare_digest(token.encode(), self.token.encode()):
			return connection.respond(HTTPStatus.FORBIDDEN, 'Invalid gallery token')
		if parsed.path == '/' and request.headers.get('Upgrade', '').lower() != 'websocket':
			response = connection.respond(HTTPStatus.OK, HTML)
			response.headers['Content-Type'] = 'text/html; charset=utf-8'
			response.headers['Cache-Control'] = 'no-store'
			response.headers['Referrer-Policy'] = 'no-referrer'
			response.headers['Content-Security-Policy'] = (
				"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'self'; frame-ancestors 'none'"
			)
			return response
		if parsed.path != '/events':
			return connection.respond(HTTPStatus.NOT_FOUND, 'Not found')
		return None

	async def _viewer(self, connection: ServerConnection) -> None:
		try:
			while not self._failed:
				await connection.send(json.dumps({'tabs': list(self.tabs.values())}))
				await asyncio.sleep(0.3)
		except ConnectionClosed:
			pass
		finally:
			await connection.close()


def main(args: list[str]) -> int:
	import argparse
	import os
	import sys

	from browser_use.browser import local
	from browser_use.browser.browser import _ws_url
	from browser_use.cli import _own_chromium_ws

	parser = argparse.ArgumentParser(prog='browser-use view', description='Watch every local browser tab (read only).')
	parser.add_argument('--cdp-url', help='Browser CDP HTTP or websocket endpoint (also BU_CDP_URL / BU_CDP_WS).')
	options = parser.parse_args(args)
	endpoint = options.cdp_url or os.environ.get('BU_CDP_URL') or os.environ.get('BU_CDP_WS') or _own_chromium_ws()
	if not endpoint:
		for profile in local.live_debug_dirs():
			endpoint = local._ws_url(profile, profile / 'none.log')
			if endpoint:
				break
	if not endpoint:
		parser.error('No reachable endpoint found. Pass --cdp-url http://127.0.0.1:PORT of your local Chrome.')

	async def run() -> None:
		async with Gallery(await asyncio.to_thread(_ws_url, endpoint)) as gallery:
			print(f'Live gallery: {gallery.url}', flush=True)
			assert gallery._reader is not None
			await gallery._reader
			raise ConnectionError('the browser connection closed')

	try:
		asyncio.run(run())
	except KeyboardInterrupt:
		pass
	except ConnectionError:
		print('the browser connection closed', file=sys.stderr)
		return 1
	return 0
