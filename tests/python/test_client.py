import asyncio
import base64
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from pydantic import BaseModel, field_validator

from browser_use import Agent, Browser, BrowserUse, BrowserUseError, Tool


class Quantity(BaseModel):
	quantity: int


class Quote(BaseModel):
	total: int


class PositiveQuantity(BaseModel):
	quantity: int

	@field_validator('quantity')
	@classmethod
	def positive(cls, value):
		if value <= 0:
			raise ValueError('Quantity must exceed zero.')
		return value


class ClientTests(unittest.IsolatedAsyncioTestCase):
	async def asyncSetUp(self):
		self.original_node = os.environ.get('BROWSER_USE_NODE')
		os.environ['BROWSER_USE_NODE'] = str(Path(__file__).resolve().parents[2] / 'build/node/linux-x64/node')
		self.directory = tempfile.TemporaryDirectory(prefix='bu-python-')
		self.agent = None
		self.responses = []
		self.requests = []
		self.server = await asyncio.start_server(self.handle, '127.0.0.1', 0)
		self.base_url = f'http://127.0.0.1:{self.server.sockets[0].getsockname()[1]}/v1'

	async def asyncTearDown(self):
		if self.agent:
			await self.agent.close()
		self.server.close()
		await self.server.wait_closed()
		self.directory.cleanup()
		if self.original_node is None:
			os.environ.pop('BROWSER_USE_NODE', None)
		else:
			os.environ['BROWSER_USE_NODE'] = self.original_node

	async def handle(self, reader, writer):
		try:
			headers = (await reader.readuntil(b'\r\n\r\n')).decode()
			length = next(
				int(line.split(':', 1)[1]) for line in headers.splitlines() if line.lower().startswith('content-length:')
			)
			request = json.loads(await reader.readexactly(length))
			self.requests.append(request)
			if 'contents' in request:
				name, args = self.responses.pop(0)[:2]
				part = {'functionCall': {'name': name, 'args': args}, 'thoughtSignature': '-_-_Pj8='}
				chunk = {
					'candidates': [{'index': 0, 'finishReason': 'STOP', 'content': {'role': 'model', 'parts': [part]}}],
					'usageMetadata': {'promptTokenCount': 10, 'candidatesTokenCount': 5, 'totalTokenCount': 15},
				}
				payload = f'data: {json.dumps(chunk)}\n\n'.encode()
				writer.write(
					f'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nContent-Length: {len(payload)}\r\nConnection: close\r\n\r\n'.encode()
					+ payload
				)
				await writer.drain()
				return
			if 'max_tokens' in request and 'messages' in request:
				name, args = self.responses.pop(0)[:2]
				events = [
					(
						'message_start',
						{
							'message': {
								'id': 'msg_1',
								'type': 'message',
								'role': 'assistant',
								'model': 'claude-opus-4-7',
								'content': [],
								'stop_reason': None,
								'usage': {'input_tokens': 10, 'output_tokens': 1},
							}
						},
					),
					('content_block_start', {'index': 0, 'content_block': {'type': 'thinking', 'thinking': ''}}),
					('content_block_delta', {'index': 0, 'delta': {'type': 'thinking_delta', 'thinking': 'plan'}}),
					('content_block_delta', {'index': 0, 'delta': {'type': 'signature_delta', 'signature': 'sig-1'}}),
					('content_block_stop', {'index': 0}),
					(
						'content_block_start',
						{
							'index': 1,
							'content_block': {'type': 'tool_use', 'id': f'toolu_{len(self.requests)}', 'name': name, 'input': {}},
						},
					),
					(
						'content_block_delta',
						{'index': 1, 'delta': {'type': 'input_json_delta', 'partial_json': json.dumps(args)}},
					),
					('content_block_stop', {'index': 1}),
					('message_delta', {'delta': {'stop_reason': 'tool_use'}, 'usage': {'output_tokens': 5}}),
					('message_stop', {}),
				]
				payload = ''.join(
					f'event: {kind}\ndata: {json.dumps({"type": kind, **body})}\n\n' for kind, body in events
				).encode()
				writer.write(
					f'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nContent-Length: {len(payload)}\r\nConnection: close\r\n\r\n'.encode()
					+ payload
				)
				await writer.drain()
				return
			name, args, *reasoning = self.responses.pop(0)
			index = len(self.requests)
			item = {
				'id': f'fc_{index}',
				'type': 'function_call',
				'call_id': f'call_{index}',
				'name': name,
				'arguments': json.dumps(args),
				'status': 'completed',
			}
			before = [('response.output_item.done', {'output_index': 0, 'item': item}) for item in reasoning]
			offset = len(reasoning)
			events = [
				*before,
				(
					'response.created',
					{
						'response': {
							'id': f'resp_{index}',
							'status': 'in_progress',
							'output': [],
						}
					},
				),
				(
					'response.output_item.added',
					{
						'output_index': offset,
						'item': {**item, 'arguments': '', 'status': 'in_progress'},
					},
				),
				(
					'response.function_call_arguments.delta',
					{
						'item_id': item['id'],
						'output_index': offset,
						'delta': item['arguments'],
					},
				),
				(
					'response.function_call_arguments.done',
					{
						'item_id': item['id'],
						'output_index': offset,
						'arguments': item['arguments'],
					},
				),
				('response.output_item.done', {'output_index': offset, 'item': item}),
				(
					'response.completed',
					{
						'response': {
							'id': f'resp_{index}',
							'status': 'completed',
							'output': [*reasoning, item],
							'usage': {
								'input_tokens': 10,
								'output_tokens': 5,
								'total_tokens': 15,
								'input_tokens_details': {'cached_tokens': 0},
							},
						}
					},
				),
			]
			payload = ''.join(f'event: {kind}\ndata: {json.dumps({"type": kind, **body})}\n\n' for kind, body in events).encode()
			writer.write(
				f'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nContent-Length: {len(payload)}\r\nConnection: close\r\n\r\n'.encode()
				+ payload
			)
			await writer.drain()
		finally:
			writer.close()
			await writer.wait_closed()

	async def create(self, **options):
		self.agent = await BrowserUse.create(
			workspace=self.directory.name,
			baseUrl=self.base_url,
			apiKey='local-fixture-key',
			telemetry=False,
			**{'browser': {'cdpUrl': 'http://127.0.0.1:1'}, 'model': 'openai/gpt-5.5', **options},
		)
		return self.agent

	async def test_model_free_browser_executes_json_without_model_configuration(self):
		self.agent = await Browser.create(
			workspace=self.directory.name,
			browser={'cdpUrl': 'http://127.0.0.1:1'},
			telemetry=False,
		)
		payload = {'values': list(range(4000))}
		result = await self.agent.execute_json(json.dumps(payload))
		self.assertEqual(result, payload)
		with self.assertRaisesRegex(BrowserUseError, 'Configure a model'):
			await self.agent.run('Do not call a model.')
		manual = Path(self.directory.name) / '.browser-use/manual.jsonl'
		await self.agent.execute("console.log('manual')")
		self.assertIn('manual_execution', manual.read_text())

	async def test_default_research_tools_include_working_bash(self):
		self.responses = [
			('bash', {'command': 'printf shell-ready'}),
			('finish', {'result': 'done'}),
		]
		agent = await self.create()
		result = await agent.run('Check the shell.')
		self.assertEqual(result.status, 'completed')
		self.assertIn('shell-ready', json.dumps(self.requests[1]))

	async def test_python_hook_blocks_a_tool_before_side_effects(self):
		seen = []

		async def before(call):
			seen.append(call['toolCall']['name'])
			if call['toolCall']['name'] == 'javascript':
				return {'block': True, 'reason': 'Fixture blocks writing.'}
			return None

		self.responses = [
			('javascript', {'code': "await artifact('forbidden.txt', 'written')"}),
			('finish', {'result': 'blocked'}),
		]
		agent = await self.create(before_tool_call=before)
		result = await agent.run('Try the blocked write.')
		self.assertEqual(result.output, 'blocked')
		self.assertIn('javascript', seen)
		self.assertFalse((Path(self.directory.name) / 'forbidden.txt').exists())

	async def test_pydantic_validation_requests_a_repair_turn(self):
		self.responses = [
			('finish', {'result': {'quantity': -1}}),
			('finish', {'result': {'quantity': 2}}),
		]
		agent = await self.create()
		result = await agent.run('Return a positive quantity.', schema=PositiveQuantity)
		self.assertEqual(result.output, PositiveQuantity(quantity=2))
		self.assertEqual(len(self.requests), 2)
		self.assertIn('Quantity must exceed zero', json.dumps(self.requests[1]))

	async def test_ready_callback_timeout_cancels_the_callback_and_closes_the_runtime(self):
		entered = asyncio.Event()
		cancelled = asyncio.Event()
		clients = []

		async def ready(browser):
			clients.append(browser)
			entered.set()
			try:
				await asyncio.Event().wait()
			finally:
				cancelled.set()

		with self.assertRaisesRegex(BrowserUseError, 'Hook exceeded'):
			await self.create(on_browser_ready=ready, hook_timeout_ms=50)
		await asyncio.wait_for(entered.wait(), 1)
		await asyncio.wait_for(cancelled.wait(), 1)
		self.assertIsNotNone(clients[0]._process.returncode)
		self.assertTrue(clients[0]._closed)

	async def test_cleanup_retries_then_reports_failure_after_stopping_the_runtime(self):
		for succeeds in (True, False):
			with self.subTest(retry_succeeds=succeeds):
				fixture = Path(self.directory.name) / 'close_fixture.py'
				receipt = Path(self.directory.name) / 'close_calls'
				fixture.write_text(
					'import json, sys\n'
					'from pathlib import Path\n'
					'calls = 0\n'
					'for line in sys.stdin:\n'
					' request = json.loads(line)\n'
					' method = request["method"]\n'
					' response = {"id": request["id"], "result": None}\n'
					' if method == "ping": response["result"] = {"protocol": 1, "node": "24.0"}\n'
					' if method == "create": response["result"] = {"workspace": "."}\n'
					' if method == "close":\n'
					'  calls += 1\n'
					f'  Path({str(receipt)!r}).write_text(str(calls))\n'
					f'  if calls == 1 or not {succeeds!r}: response = {{"id": request["id"], "error": {{"message": "Cloud stop failed"}}}}\n'
					' print(json.dumps(response), flush=True)\n'
				)
				agent = await BrowserUse.create(node=sys.executable, server_path=fixture)
				try:
					if succeeds:
						await agent.close()
					else:
						with self.assertRaisesRegex(BrowserUseError, 'cleanup failed after retry'):
							await agent.close()
					self.assertEqual(receipt.read_text(), '2')
					self.assertIsNotNone(agent._process.returncode)
					self.assertTrue(agent._closed)
				finally:
					if not agent._closed:
						await agent.close()

	async def test_python_ready_callback_runs_before_the_first_model_call(self):
		async def ready(browser):
			await browser.execute('var setupValue = 41')

		self.responses = [
			('javascript', {'code': 'console.log(setupValue + 1)'}),
			('finish', {'result': 'ready'}),
		]
		agent = await self.create(on_browser_ready=ready)
		result = await agent.run('Read the setup value.')
		self.assertEqual(result.output, 'ready')
		self.assertIn('42', json.dumps(self.requests[1]))

	async def test_agent_context_manager_starts_and_closes_the_runtime(self):
		self.responses = [('finish', {'result': 'context'})]
		context = Agent(
			model='openai/gpt-5.5',
			browser={'kind': 'pending'},
			workspace=self.directory.name,
			base_url=self.base_url,
			api_key='local-fixture-key',
			telemetry=False,
		)
		async with context as agent:
			self.assertEqual((await agent.run('Return context.')).output, 'context')
			process = agent._process
		self.assertIsNotNone(process.returncode)

	async def test_cancel_waits_for_manual_worker_termination(self):
		agent = await self.create()
		started = asyncio.Event()

		async def observe():
			async for event in agent.events():
				if event.get('type') == 'manual_execution' and event.get('phase') == 'start':
					started.set()
					return

		watcher = asyncio.create_task(observe())
		cell = asyncio.create_task(agent.execute('await new Promise(() => {})'))
		try:
			await asyncio.wait_for(started.wait(), 2)
			await asyncio.wait_for(agent.cancel(), 2)
			with self.assertRaisesRegex(BrowserUseError, 'cancelled'):
				await cell
			self.assertEqual(await agent.execute_json('7'), 7)
		finally:
			watcher.cancel()
			await asyncio.gather(watcher, return_exceptions=True)
			if not cell.done():
				cell.cancel()
			await asyncio.gather(cell, return_exceptions=True)

	async def test_python_after_tool_callback_observes_the_result(self):
		seen = []

		async def after(call):
			seen.append(call['toolCall']['name'])

		self.responses = [('javascript', {'code': 'console.log("observed")'}), ('finish', {'result': 'done'})]
		agent = await self.create(after_tool_call=after)
		self.assertEqual((await agent.run('Observe one cell.')).output, 'done')
		self.assertEqual(seen, ['javascript'])

	async def test_timed_out_hook_cancels_its_python_callback(self):
		entered = asyncio.Event()
		cancelled = asyncio.Event()

		async def before(call):
			entered.set()
			try:
				await asyncio.Event().wait()
			finally:
				cancelled.set()

		self.responses = [('javascript', {'code': 'await artifact("blocked.txt", "value")'})]
		agent = await self.create(before_tool_call=before, hook_timeout_ms=50)
		result = await agent.run('Stop the callback.', max_steps=1, timeout_ms=1000)
		await asyncio.wait_for(entered.wait(), 1)
		await asyncio.wait_for(cancelled.wait(), 1)
		self.assertNotEqual(result.status, 'completed')
		self.assertFalse((Path(self.directory.name) / 'blocked.txt').exists())

	async def test_browser_policy_and_secrets_cross_the_python_bridge(self):
		agent = await self.create(
			browser={'kind': 'chromium'},
			allowedDomains=[],
			sensitiveData={'password': {'value': 'fixture-private-password', 'domains': ['example.com']}},
		)
		with self.assertRaisesRegex(BrowserUseError, 'domain policy'):
			await agent.execute("await page.goto('https://example.com')")
		self.responses = [('finish', {'result': 'Policy configured'})]
		result = await agent.run('Report readiness.')
		self.assertEqual(result.status, 'completed')
		self.assertNotIn('fixture-private-password', json.dumps(self.requests))

	async def test_partial_findings_survive_step_limit_without_final_schema_validation(self):
		self.responses = [
			('javascript', {'code': "await checkpoint('findings.json', [{issue:'Broken search'}], {partial:true})"})
		]
		agent = await self.create(highlightActions=True)
		result = await agent.run('Audit', schema=Quote, maxSteps=1)
		self.assertEqual(result.status, 'max_steps')
		self.assertIsNone(result.output)
		self.assertEqual(result.partial['value'], [{'issue': 'Broken search'}])
		self.assertTrue(Path(result.partial['path']).is_file())
		self.assertEqual(len(self.requests), 1)

	async def test_typed_python_tool_round_trip_and_live_events(self):
		called = []

		async def quote(args):
			called.append(args.quantity)
			return Quote(total=args.quantity * 7)

		self.responses = [
			('quote', {'quantity': 3}),
			('finish', {'result': {'total': 21}}),
		]
		agent = await self.create(
			tools=[Tool('quote', 'Price the quantity', Quantity, quote)],
			modelTimeoutMs=5000,
			compactionTimeoutMs=2000,
			compactionRetryDelayMs=1,
		)
		stream = agent.events()
		first = asyncio.create_task(anext(stream))
		await asyncio.sleep(0)
		running = asyncio.create_task(agent.run('Calculate quote', schema=Quote))
		self.assertEqual((await asyncio.wait_for(first, 5))['type'], 'run_start')
		result = await asyncio.wait_for(running, 15)
		self.assertEqual(result.status, 'completed')
		self.assertEqual(result.output, Quote(total=21))
		self.assertEqual(called, [3])
		self.assertIn('21', json.dumps(self.requests[1]))
		self.assertEqual(result.usage['totalTokens'], 30)
		await stream.aclose()

	async def test_workspace_and_followup(self):
		self.responses = [
			('finish', {'result': 'first'}),
			('finish', {'result': 'second'}),
		]
		agent = await self.create()
		await agent.execute("const x = 9; await require('node:fs/promises').writeFile('output.txt', 'hello')")
		self.assertEqual((await agent.execute('x + 1'))['text'], '10')
		self.assertEqual((await agent.files())[0]['relativePath'], 'output.txt')
		await agent.run('remember the first task')
		self.assertEqual((await agent.follow_up('continue')).output, 'second')
		self.assertIn('remember the first task', json.dumps(self.requests[1]))
		path = await agent.save_history()
		self.assertEqual(json.loads(Path(path).read_text())['version'], 1)

	async def test_bundled_oversized_screenshot_preserves_original_and_reaches_provider(self):
		agent = await self.create(browser={'kind': 'chromium'})
		capture = await agent.execute(
			"await page.goto('data:text/html,<body>Image fixture</body>'); "
			"await page.cdp('Page.captureScreenshot', {format:'png',captureBeyondViewport:true,"
			'clip:{x:0,y:0,width:1440,height:22000,scale:1}})'
			".then(r=>artifact('original.png',Buffer.from(r.data,'base64')))"
		)
		self.assertEqual(len(capture['images']), 1, capture['text'])
		self.assertIn('model preview', capture['text'])
		original = (Path(self.directory.name) / 'original.png').read_bytes()
		self.assertEqual(int.from_bytes(original[20:24], 'big'), 22000)
		preview = base64.b64decode(capture['images'][0]['data'])
		self.assertNotEqual(original, preview)

		self.responses = [
			(
				'javascript',
				{
					'code': "await page.cdp('Page.captureScreenshot', {format:'png',captureBeyondViewport:true,clip:{x:0,y:0,width:1440,height:22000,scale:1}}); void 0"
				},
			),
			('finish', {'result': 'preview received'}),
		]
		result = await agent.run('Capture and inspect the full page')
		self.assertEqual(result.output, 'preview received')
		serialized = json.dumps(self.requests[-1])
		self.assertIn('input_image', serialized)
		self.assertIn('model preview', serialized)
		self.assertNotIn(base64.b64encode(original).decode(), serialized)

	async def test_cancel_propagates_to_python_tool(self):
		entered, cancelled = asyncio.Event(), asyncio.Event()

		async def slow(_args):
			entered.set()
			try:
				await asyncio.Future()
			finally:
				cancelled.set()

		self.responses = [('slow', {'quantity': 1})]
		agent = await self.create(tools=[Tool('slow', 'Wait', Quantity, slow)])
		task = asyncio.create_task(agent.run('wait'))
		await asyncio.wait_for(entered.wait(), 10)
		task.cancel()
		with self.assertRaises(asyncio.CancelledError):
			await task
		await asyncio.wait_for(cancelled.wait(), 5)

	async def test_model_id_renames_only_the_upstream_model(self):
		self.responses = [('finish', {'result': 'done'})]
		agent = await self.create(modelId='gpt-6-luna')
		self.assertEqual((await agent.run('say done')).output, 'done')
		self.assertEqual(self.requests[0]['model'], 'gpt-6-luna')

	async def test_model_info_serves_a_model_newer_than_the_catalog(self):
		self.responses = [('finish', {'result': 'done'})]
		info = {'template': 'openai/gpt-5.5', 'contextWindow': 250_000, 'maxTokens': 32_000}
		agent = await self.create(model='openai/gpt-7-fixture', modelInfo=info)
		self.assertEqual((await agent.run('say done')).output, 'done')
		self.assertEqual(self.requests[0]['model'], 'gpt-7-fixture')
		self.assertEqual(self.requests[0]['max_output_tokens'], 32_000)
		path = Path(self.directory.name) / 'history.json'
		await agent.save_history(str(path))
		self.assertEqual(json.loads(path.read_text())['model'], 'openai/gpt-7-fixture')

	async def test_gemini_signatures_are_replayed_as_standard_base64(self):
		self.responses = [('javascript', {'code': '1 + 1'}), ('finish', {'result': 'done'})]
		agent = await self.create(model='google/gemini-3.6-flash')
		self.assertEqual((await agent.run('add')).output, 'done')
		replayed = [part for content in self.requests[1]['contents'] if content['role'] == 'model' for part in content['parts']]
		self.assertEqual(replayed[0]['thoughtSignature'], '+/+/Pj8=')

	async def test_thinking_survives_a_gateway_answering_under_another_model_name(self):
		self.responses = [('javascript', {'code': '1 + 1'}), ('finish', {'result': 'done'})]
		agent = await self.create(model='anthropic/claude-opus-4-7', modelId='claude-opus-4.7')
		self.assertEqual((await agent.run('add')).output, 'done')
		replayed = [
			block for message in self.requests[1]['messages'] if message['role'] == 'assistant' for block in message['content']
		]
		self.assertIn({'type': 'thinking', 'thinking': 'plan', 'signature': 'sig-1'}, replayed)

	async def test_model_info_thinking_levels_override_the_catalog(self):
		self.responses = [('finish', {'result': 'done'})]
		info = {'thinkingLevelMap': {'off': 'disabled'}, 'compat': {'supportsMidConvoEffort': False}}
		agent = await self.create(model='anthropic/claude-opus-5', modelInfo=info, reasoning='off')
		await agent.run('say done')
		self.assertEqual(self.requests[0]['thinking'], {'type': 'disabled'})

	async def test_model_info_can_turn_thinking_off_entirely(self):
		self.responses = [('finish', {'result': 'done'})]
		agent = await self.create(
			model='anthropic/claude-opus-5', modelInfo={'reasoning': False, 'compat': {'supportsMidConvoEffort': False}}
		)
		try:
			await agent.run('say done')
		except BrowserUseError:
			pass
		self.assertNotIn('thinking', self.requests[0])
		self.assertNotIn('output_config', self.requests[0])

	async def test_shell_env_reaches_the_bash_tool(self):
		self.responses = [('bash', {'command': 'echo token=$CLOUD_TOKEN'}), ('finish', {'result': 'done'})]
		agent = await self.create(researchTools=True, shellEnv={'CLOUD_TOKEN': 'fixture-run-token'})
		self.assertEqual((await agent.run('check')).output, 'done')
		self.assertIn('token=fixture-run-token', json.dumps(self.requests[1]['input']))

	async def test_shell_timeout_outlasts_the_cell_timeout(self):
		self.responses = [('bash', {'command': 'sleep 3 && echo slept'}), ('finish', {'result': 'done'})]
		agent = await self.create(researchTools=True, cellTimeoutMs=2000, shellTimeoutMs=10000)
		self.assertEqual((await agent.run('wait')).output, 'done')
		outputs = [i for i in self.requests[1]['input'] if i.get('type') == 'function_call_output']
		self.assertTrue(any('slept' in json.dumps(i['output']) for i in outputs), outputs)

	async def test_moving_to_another_browser_needs_the_host_option(self):
		agent = await self.create(browser={'kind': 'chromium'})
		with self.assertRaisesRegex(BrowserUseError, 'not enabled'):
			await agent.execute("await reconnect('ws://127.0.0.1:9/devtools/browser/x')")

	async def test_model_info_compat_overrides_the_catalog(self):
		for info in (None, {'compat': {'supportsMidConvoEffort': False}}):
			self.responses = [('finish', {'result': 'done'})]
			await self.create(model='anthropic/claude-opus-5', **({'modelInfo': info} if info else {}))
			try:
				await self.agent.run('say done')
			except BrowserUseError:
				pass
			await self.agent.close()
		beta_messages = [[m for m in request['messages'] if 'output_config' in m] for request in self.requests]
		self.assertTrue(beta_messages[0])
		self.assertEqual(beta_messages[-1], [])

	async def test_unknown_model_runs_without_catalog_registration(self):
		self.responses = [('finish', {'result': 'new model'})]
		agent = await self.create(
			model='openai/gpt-7-fixture',
			model_info={'api': 'openai-responses', 'maxTokens': 32_000},
		)
		result = await agent.run('Use the requested model.')
		self.assertEqual(result.output, 'new model')
		self.assertEqual(self.requests[0]['model'], 'gpt-7-fixture')
		self.assertIsNone(result.metadata['estimatedCostUsd'])
		self.assertIsNone(result.usage['cost'])
		with self.assertRaisesRegex(BrowserUseError, 'explicit pricing'):
			await agent.run('Use a cost limit.', max_cost_usd=1)

	async def test_gateway_null_fields_are_not_replayed_on_reasoning_items(self):
		reasoning = {
			'id': 'rs_1',
			'type': 'reasoning',
			'summary': [],
			'encrypted_content': 'gAAAA-opaque',
			'status': None,
		}
		self.responses = [
			('javascript', {'code': '1 + 1'}, reasoning),
			('finish', {'result': 'done'}),
		]
		agent = await self.create()
		self.assertEqual((await agent.run('add')).output, 'done')
		replayed = [i for i in self.requests[1]['input'] if i.get('type') == 'reasoning']
		self.assertEqual(replayed, [{k: v for k, v in reasoning.items() if v is not None}])

	async def test_stream_deltas_false_keeps_only_settled_events(self):
		self.responses = [('finish', {'result': 'done'})]
		agent = await self.create(streamDeltas=False)
		seen = []
		ready = asyncio.Event()
		finished = asyncio.Event()

		async def collect():
			stream = agent.events()
			first = asyncio.create_task(anext(stream))
			try:
				ready.set()
				event = await first
				while True:
					if event.get('type') == 'agent_event':
						seen.append(event['event']['type'])
					if event.get('type') == 'run_end':
						finished.set()
						return
					event = await anext(stream)
			finally:
				first.cancel()
				await asyncio.gather(first, return_exceptions=True)
				await stream.aclose()

		task = asyncio.create_task(collect())
		try:
			await ready.wait()
			await agent.run('finish')
			await asyncio.wait_for(finished.wait(), 2)
			await task
		finally:
			task.cancel()
			await asyncio.gather(task, return_exceptions=True)
		self.assertNotIn('message_update', seen)
		self.assertIn('message_end', seen)

	async def test_unknown_options_and_missing_runtime_fail_explicitly(self):
		with self.assertRaisesRegex(BrowserUseError, 'Unsupported create option'):
			await BrowserUse.create(model='openai/gpt-5.5', imaginaryOption=True)
		with self.assertRaisesRegex(BrowserUseError, 'runtime is missing'):
			await BrowserUse.create(model='openai/gpt-5.5', server_path='/nonexistent/server.mjs')

	async def test_start_then_configure_matches_create(self):
		async def quote(args):
			return Quote(total=args.quantity * 7)

		self.responses = [('quote', {'quantity': 3}), ('finish', {'result': {'total': 21}})]
		self.agent = await BrowserUse.start(tools=[Tool('quote', 'Price the quantity', Quantity, quote)])
		agent = await self.agent.configure(
			model='openai/gpt-5.5',
			workspace=self.directory.name,
			baseUrl=self.base_url,
			apiKey='local-fixture-key',
			telemetry=False,
			browser={'kind': 'pending'},
		)
		self.assertIs(agent, self.agent)
		self.assertEqual(Path(agent.workspace).resolve(), Path(self.directory.name).resolve())
		result = await agent.run('Calculate quote', schema=Quote)
		self.assertEqual(result.output, Quote(total=21))
		with self.assertRaisesRegex(BrowserUseError, 'already configured'):
			await agent.configure(model='openai/gpt-5.5')

	async def test_a_pending_browser_session_runs_the_model_and_connects_once(self):
		self.responses = [('finish', {'result': 'no browser needed'})]
		agent = await self.create(browser={'kind': 'pending'}, dedicatedBrowser=True)
		result = await asyncio.wait_for(agent.run('Answer without the browser.'), 30)
		self.assertEqual(result.status, 'completed')
		with self.assertRaisesRegex(BrowserUseError, 'WebSocket endpoint'):
			await agent.connect_browser('file:///tmp/not-a-browser')
		await agent.connect_browser('ws://127.0.0.1:9/devtools/browser/x', target_id='T1')
		with self.assertRaisesRegex(BrowserUseError, 'already has a browser'):
			await agent.connect_browser('ws://127.0.0.1:9/devtools/browser/x')

	async def test_close_after_start_stops_the_runtime(self):
		agent = await BrowserUse.start()
		process = agent._process
		await asyncio.wait_for(agent.close(), 5)
		self.assertIsNotNone(process.returncode)
		self.assertNotIn('Graceful close failed', agent._stderr)
		with self.assertRaisesRegex(BrowserUseError, 'closed'):
			await agent.configure(model='openai/gpt-5.5')

	async def test_failed_configure_stops_the_runtime(self):
		agent = await BrowserUse.start()
		with self.assertRaisesRegex(BrowserUseError, 'Unsupported create option'):
			await agent.configure(model='openai/gpt-5.5', imaginaryOption=True)
		self.assertIsNotNone(agent._process.returncode)

	async def test_nested_pydantic_schema_round_trip(self):
		class Invoice(BaseModel):
			quote: Quote

		self.responses = [('finish', {'result': {'quote': {'total': 21}}})]
		agent = await self.create()
		result = await agent.run('Nested schema', schema=Invoice)
		self.assertEqual(result.output.quote.total, 21)
		self.assertNotIn('"$ref"', json.dumps(self.requests[0]['tools']))

	async def test_tool_failure_is_returned_to_agent_for_recovery(self):
		async def broken(_args):
			raise ValueError('fixture business error')

		self.responses = [
			('broken', {'quantity': 1}),
			('finish', {'result': 'reported failure'}),
		]
		agent = await self.create(tools=[Tool('broken', 'Fail', Quantity, broken)])
		result = await agent.run('report errors')
		self.assertEqual(result.output, 'reported failure')
		self.assertIn('fixture business error', json.dumps(self.requests[1]))


if __name__ == '__main__':
	unittest.main()
