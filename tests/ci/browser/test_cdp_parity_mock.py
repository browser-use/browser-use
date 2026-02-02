import json
from dataclasses import dataclass, field
from pathlib import Path

import aiohttp
import pytest
from aiohttp import web

from browser_use.browser.session import BrowserSession


@dataclass
class MockCDPServer:
	methods: list[str] = field(default_factory=list)
	last_evaluate_expression: str | None = None
	app: web.Application | None = None
	runner: web.AppRunner | None = None
	site: web.TCPSite | None = None
	base_url: str | None = None

	async def start(self) -> None:
		self.app = web.Application()
		self.app.router.add_get('/json/version', self.handle_version)
		self.app.router.add_get('/ws', self.handle_ws)
		self.runner = web.AppRunner(self.app)
		await self.runner.setup()
		self.site = web.TCPSite(self.runner, '127.0.0.1', 0)
		await self.site.start()
		port = self.site._server.sockets[0].getsockname()[1]
		self.base_url = f'http://127.0.0.1:{port}'

	async def close(self) -> None:
		if self.runner:
			await self.runner.cleanup()

	async def handle_version(self, request: web.Request) -> web.Response:
		assert self.base_url
		return web.json_response({'webSocketDebuggerUrl': f'ws://127.0.0.1:{self.base_url.split(":")[-1]}/ws'})

	async def handle_ws(self, request: web.Request) -> web.StreamResponse:
		ws = web.WebSocketResponse()
		await ws.prepare(request)

		async for msg in ws:
			if msg.type != aiohttp.WSMsgType.TEXT:
				continue
			payload = json.loads(msg.data)
			method = payload.get('method')
			if method:
				self.methods.append(method)
			msg_id = payload.get('id')
			if not msg_id:
				continue

			result = {}
			if method == 'Target.getTargets':
				result = {
					'targetInfos': [
						{
							'targetId': 'page-1',
							'type': 'page',
							'url': 'https://example.com',
							'title': 'Example',
						}
					]
				}
			elif method == 'Target.attachToTarget':
				result = {'sessionId': 'session-1'}
				await ws.send_str(
					json.dumps(
						{
							'method': 'Target.attachedToTarget',
							'params': {
								'sessionId': 'session-1',
								'targetInfo': {
									'targetId': 'page-1',
									'type': 'page',
									'url': 'https://example.com',
									'title': 'Example',
								},
							},
						}
					)
				)
			elif method == 'Runtime.evaluate':
				params = payload.get('params') or {}
				self.last_evaluate_expression = params.get('expression')
				result = {'result': {'value': 'ok'}}

			await ws.send_str(json.dumps({'id': msg_id, 'result': result}))

		return ws


@pytest.mark.asyncio
async def test_cdp_connect_sequence_and_evaluate():
	server = MockCDPServer()
	await server.start()
	assert server.base_url

	session = BrowserSession(cdp_url=server.base_url)
	await session.connect()

	fixture_path = Path(__file__).resolve().parents[2] / 'fixtures' / 'cdp_connect_sequence.json'
	with fixture_path.open('r', encoding='utf-8') as handle:
		expected = json.load(handle)
	assert server.methods[: len(expected)] == expected

	page = await session.get_current_page()
	assert page
	cdp_session = await session.get_or_create_cdp_session()
	page._session_id = cdp_session.session_id

	with pytest.raises(ValueError):
		await page.evaluate('document.title')

	result = await page.evaluate('() => "ok"')
	assert result == 'ok'
	assert server.last_evaluate_expression is not None

	await session.reset()
	await server.close()
