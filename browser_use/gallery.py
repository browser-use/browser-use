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
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Browser Use &middot; Live gallery</title>
<style>
:root{color-scheme:dark;font:100%/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;background:#121416;color:#eef0f2;font-optical-sizing:auto;--muted:#989da5;--surface:#1e2125;--focus:#a9c9ff}
*{box-sizing:border-box}body{margin:0;min-width:0}button{font:inherit;color:inherit;touch-action:manipulation}::selection{background:#385775;color:#fff}html{scrollbar-color:#454a52 #121416}
header,main{max-width:1800px;margin:auto;padding-left:max(2rem,env(safe-area-inset-left));padding-right:max(2rem,env(safe-area-inset-right))}header{display:flex;align-items:baseline;gap:.75rem;padding-top:max(2rem,env(safe-area-inset-top));padding-bottom:1.75rem}h1{font-size:1.25rem;line-height:1.3;font-weight:600;letter-spacing:-.025em;margin:0}#count{font-size:.8125rem;color:var(--muted)}main{padding-bottom:max(2rem,env(safe-area-inset-bottom))}
#grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1.75rem 1.5rem}#grid>[role=listitem]{min-width:0}.tile{display:block;width:100%;min-width:0;padding:0;border:0;background:transparent;text-align:left;cursor:zoom-in;border-radius:12px}.preview{display:block;position:relative;aspect-ratio:16/10;border-radius:12px;overflow:hidden;background:var(--surface);box-shadow:0 6px 22px #0003;isolation:isolate}.preview:before{content:'';position:absolute;inset:0;background:linear-gradient(105deg,transparent 30%,#ffffff07 48%,transparent 66%);background-size:240% 100%;animation:shimmer 2s ease-in-out infinite}.preview:after{content:'Loading preview';position:absolute;inset:0;display:grid;place-content:center;color:var(--muted);font-size:.8125rem}.preview.ready:before,.preview.ready:after{display:none}img{display:block;width:100%;height:100%;object-fit:contain;object-position:top}img:not([src]){visibility:hidden}.live-dot{position:absolute;right:12px;bottom:12px;width:7px;height:7px;border-radius:50%;background:#79d8a4;box-shadow:0 0 0 3px #15221ccc,0 2px 6px #0006;opacity:0}.ready .live-dot{opacity:1;animation:breathe 2.4s ease-in-out infinite}.offline .live-dot{display:none}
.info{display:flex;align-items:center;gap:.5rem;min-width:0;margin-top:.75rem;padding:0 .125rem}.avatar{display:grid;place-items:center;flex:none;width:20px;height:20px;border-radius:6px;background:#2a2e34;color:#c4c9d0;font-size:.6875rem;font-weight:600}.title{min-width:0;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;font-size:.8125rem;font-weight:500}.url{min-width:0;max-width:38%;flex-shrink:0;margin-left:auto;color:var(--muted);font-size:.6875rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.tile:focus-visible,#close:focus-visible{outline:2px solid var(--focus);outline-offset:5px}.tile:hover .preview{box-shadow:0 9px 28px #0005}.tile:active .preview{filter:brightness(.88)}
#empty{min-height:65vh;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;gap:.5rem}#empty[hidden]{display:none}#empty h2{font-size:1.125rem;letter-spacing:-.02em;font-weight:500;margin:0}#empty p{font-size:.875rem;color:var(--muted);margin:0;max-width:28ch;text-wrap:balance}
dialog{position:fixed;inset:0;width:100%;height:100%;max-width:none;max-height:none;margin:0;padding:max(1.25rem,env(safe-area-inset-top)) max(1.25rem,env(safe-area-inset-right)) max(1.25rem,env(safe-area-inset-bottom)) max(1.25rem,env(safe-area-inset-left));border:0;background:transparent;color:inherit;overflow:hidden}dialog[open]{display:grid;place-items:center}dialog::backdrop{background:#0b0d10e8;backdrop-filter:blur(8px)}.panel{width:min(1120px,100%,calc((100dvh - 150px)*1.6));transform-origin:top left;will-change:transform}.panel .preview{box-shadow:0 24px 80px #0007}.panel .info{margin-top:1rem}.panel .title{font-size:.9375rem}.panel .url{font-size:.8125rem}#close{flex:none;display:grid;place-items:center;width:44px;height:44px;margin:-12px -8px -12px .25rem;border:0;border-radius:50%;background:transparent;cursor:pointer;color:#b9bec6;font-size:1.5rem;line-height:1}#close:hover{background:#ffffff0c;color:#fff}body:has(dialog[open]){overflow:hidden}
@keyframes shimmer{to{background-position:-140% 0}}@keyframes breathe{50%{opacity:.45}}
@media(min-width:1700px){#grid{grid-template-columns:repeat(4,minmax(0,1fr))}}@media(max-width:1050px){#grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:600px){header,main{padding-left:max(1.25rem,env(safe-area-inset-left));padding-right:max(1.25rem,env(safe-area-inset-right))}header{padding-top:max(1.5rem,env(safe-area-inset-top));padding-bottom:1.5rem}#grid{grid-template-columns:1fr;gap:1.5rem}.panel .info{flex-wrap:wrap}.panel .title{flex:1}.panel .url{order:2;max-width:100%;width:100%;margin-left:28px}.panel #close{margin-left:auto}}
@media(prefers-reduced-motion:reduce){*,*:before,*:after{animation:none!important}}@media(prefers-reduced-transparency:reduce){dialog::backdrop{background:#121416;backdrop-filter:none}}@media(prefers-contrast:more){:root{--muted:#c2c7cf}.preview{outline:1px solid #8d929b}}
</style>
<header><h1 id="status" tabindex="-1">Live</h1><span id="count" role="status">0 tabs</span></header>
<main><div id="grid" role="list" aria-label="Live browser tabs"></div><div id="empty" role="status"><h2>Waiting for tabs</h2><p>Open a page in your browser.<br>It will appear here automatically.</p></div></main>
<dialog id="detail" aria-labelledby="detail-title"><div class="panel"><div class="preview"><img id="detail-img" alt="Enlarged browser preview"><span class="live-dot" aria-hidden="true"></span></div><div class="info"><span class="avatar" aria-hidden="true" id="detail-avatar"></span><span class="title" id="detail-title"></span><span class="url" id="detail-url"></span><button id="close" aria-label="Close enlarged view" autofocus>&times;</button></div></div></dialog>
<script>
const grid=document.querySelector('#grid'),detail=document.querySelector('#detail'),panel=detail.querySelector('.panel'),tiles=new Map(),motion=matchMedia('(prefers-reduced-motion: reduce)');
let selected=null,origin=null,closing=false,raf=0,last=0,state=[0,0,1,1],velocity=[0,0,0,0],target=[0,0,1,1];
const socket=new WebSocket(`ws://${location.host}/events${location.search}`);
socket.onclose=()=>{document.body.classList.add('offline');document.querySelector('#status').textContent='Disconnected';document.querySelector('#empty h2').textContent='Browser disconnected';document.querySelector('#empty p').textContent='Reconnect your browser and reopen the gallery.';document.querySelector('#empty').hidden=false;};
function host(url){try{return new URL(url).hostname.replace(/^www\./,'')||'Local page'}catch{return 'Local page'}}
function paintFrame(img,frame){const src=frame?'data:image/jpeg;base64,'+frame:null;if(src){if(img.getAttribute('src')!==src)img.src=src}else img.removeAttribute('src');img.parentElement.classList.toggle('ready',!!frame)}
function enlarge(tab){document.querySelector('#detail-title').textContent=tab.title||'Untitled';document.querySelector('#detail-url').textContent=host(tab.url);document.querySelector('#detail-avatar').textContent=host(tab.url).charAt(0).toUpperCase();paintFrame(document.querySelector('#detail-img'),tab.frame)}
function destination(){const previous=panel.style.transform;panel.style.transform='none';const rect=panel.getBoundingClientRect();panel.style.transform=previous;return rect}
function tileTransform(){const from=origin.getBoundingClientRect(),to=destination();return [from.x-to.x,from.y-to.y,from.width/to.width,from.height/to.height]}
function finish(){cancelAnimationFrame(raf);raf=0;state=[...target];velocity=[0,0,0,0];panel.style.transform='none';if(closing){detail.close();selected=null;closing=false;if(origin?.isConnected)origin.focus({preventScroll:true});else document.querySelector('h1').focus({preventScroll:true});origin=null}}
// Retarget a critically damped FLIP spring without discarding its current position or velocity.
function step(now){const dt=(now-last)/1000,decay=Math.exp(-24*dt);last=now;let settled=true;for(let i=0;i<4;i++){const delta=state[i]-target[i],impulse=velocity[i]+24*delta;state[i]=target[i]+(delta+impulse*dt)*decay;velocity[i]=(velocity[i]-24*impulse*dt)*decay;if(Math.abs(target[i]-state[i])>(i<2?.25:.001)||Math.abs(velocity[i])>(i<2?1:.005))settled=false}panel.style.transform=`translate(${state[0]}px,${state[1]}px) scale(${state[2]},${state[3]})`;if(settled)finish();else raf=requestAnimationFrame(step)}
function animate(){if(motion.matches){finish();return}if(!raf){last=performance.now();raf=requestAnimationFrame(step)}}
function openTile(id){const tile=tiles.get(id);if(!tile)return;selected=id;origin=tile;enlarge(tile.tab);if(!detail.open){detail.showModal();state=tileTransform();velocity=[0,0,0,0];panel.style.transform=`translate(${state[0]}px,${state[1]}px) scale(${state[2]},${state[3]})`}closing=false;target=[0,0,1,1];animate()}
function closeDetail(){if(!detail.open||closing)return;closing=true;target=origin?.isConnected?tileTransform():[0,0,1,1];animate()}
document.querySelector('#close').onclick=closeDetail;detail.addEventListener('cancel',e=>{e.preventDefault();closeDetail()});detail.onclick=e=>{if(e.target===detail)closeDetail();else if(closing&&!e.target.closest('#close'))openTile(selected)};detail.addEventListener('close',()=>{cancelAnimationFrame(raf);raf=0;selected=null});window.addEventListener('resize',()=>{if(detail.open){target=closing&&origin?.isConnected?tileTransform():[0,0,1,1];animate()}});motion.addEventListener('change',()=>{if(detail.open&&motion.matches)finish()});
socket.onmessage=e=>{const {tabs}=JSON.parse(e.data);const count=document.querySelector('#count'),label=`${tabs.length} tab${tabs.length===1?'':'s'}`;if(count.textContent!==label)count.textContent=label;document.querySelector('#empty').hidden=!!tabs.length;
for(const [id,tile] of tiles)if(!tabs.some(t=>t.id===id)){tile.parentElement.remove();tiles.delete(id);if(selected===id){closing=true;finish()}}
for(const tab of tabs){let tile=tiles.get(tab.id);if(!tile){tile=document.createElement('button');tile.type='button';tile.className='tile';tile.setAttribute('aria-haspopup','dialog');tile.innerHTML='<span class="preview"><img alt=""><span class="live-dot" aria-hidden="true"></span></span><span class="info"><span class="avatar" aria-hidden="true"></span><span class="title"></span><span class="url"></span></span>';tile.onclick=()=>openTile(tab.id);tiles.set(tab.id,tile);const item=document.createElement('div');item.setAttribute('role','listitem');item.append(tile);grid.append(item)}tile.tab=tab;const title=tab.title||'Untitled',hostname=host(tab.url);tile.setAttribute('aria-label',`Enlarge ${title}, ${hostname}${tab.frame?'':', loading preview'}`);tile.querySelector('.title').textContent=title;tile.querySelector('.url').textContent=hostname;tile.querySelector('.avatar').textContent=hostname.charAt(0).toUpperCase();paintFrame(tile.querySelector('img'),tab.frame);if(selected===tab.id)enlarge(tab)}
};
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
