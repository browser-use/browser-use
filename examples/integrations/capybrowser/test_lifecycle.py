"""Non-billable fault tests: python -m unittest discover -s this_directory."""

import asyncio
import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from lifecycle import BASE, Lifecycle, SafeError, State
from main import execute, run_worker, single_use_browser


def projection(status='ready', billing='reserved', session_id='session-owned') -> dict:
	return dict(
		session_id=session_id,
		status=status,
		profile_id=None,
		purpose='agent',
		max_seconds=180,
		expires_at=(datetime.now(timezone.utc) + timedelta(seconds=180)).isoformat(),
		billing=dict(
			status=billing,
			actual_charge_centipoints=7 if billing == 'settled' else None,
			charge_stop_at='2026-10-16T01:00:00Z' if status == 'released' else None,
		),
	)


class FastLifecycle(Lifecycle):
	async def ready(self, timeout=0.025):
		return await super().ready(timeout)

	async def finish(self, timeout=0.04):
		return await super().finish(timeout)


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
	async def asyncSetUp(self):
		self.temp = tempfile.TemporaryDirectory()
		self.directory = Path(self.temp.name) / 'run'
		self.state = State(self.directory, 'test-key-not-real', False)
		self.calls = []
		self.stopped = False
		self.get_status = 'ready'
		self.pending = False
		self.fail_create = False
		self.fail_get = False
		self.fail_delete = False
		self.control_error = False
		self.client = httpx.AsyncClient(base_url=BASE, transport=httpx.MockTransport(self.respond))
		self.life = FastLifecycle(self.client, self.state, 0.001)

	async def asyncTearDown(self):
		await self.client.aclose()
		self.state.close()
		self.temp.cleanup()

	def respond(self, request):
		self.calls.append(request)
		if request.method == 'POST' and request.url.path.endswith('/sessions'):
			# Simulates server acceptance with a lost response.
			if self.fail_create:
				raise httpx.ReadTimeout('secret wss://private/token?key=do-not-log')
			data = projection()
		elif request.url.path.endswith('/control'):
			if self.control_error:
				return httpx.Response(503, json={'error': 'private-secret'})
			data = dict(
				cdp_url='wss://control.invalid/private-grant',
				expires_at=(datetime.now(timezone.utc) + timedelta(seconds=20)).isoformat(),
			)
		elif request.method == 'DELETE':
			self.stopped = True
			if self.fail_delete:
				raise httpx.ReadTimeout('unknown DELETE')
			data = projection('stopping', 'settling')
		else:
			if self.fail_get:
				raise httpx.ReadTimeout('unknown GET')
			data = (
				projection('released', 'settling' if self.pending else 'settled') if self.stopped else projection(self.get_status)
			)
		return httpx.Response(
			202 if request.method == 'DELETE' or request.url.path.endswith('/sessions') else 200,
			json={'code': 'ok', 'data': data},
		)

	async def good_runner(self, url, timeout, usage_path=None, trace_path=None):
		self.assertEqual(url, 'wss://control.invalid/private-grant')
		self.assertGreater(timeout, 0)
		return {'mode': 'agent', 'answer': 'Example Domain'}

	async def test_success_requires_release_and_settlement(self):
		result, code = await execute(self.life, False, self.good_runner)
		self.assertEqual(code, 0)
		self.assertTrue(result['cleanup']['released'])
		self.assertEqual(result['cleanup']['actual_charge_centipoints'], 7)
		self.assertTrue(result['cleanup']['delete_accepted'])
		self.assertEqual(result['cleanup']['delete_http_status'], 202)
		self.assertEqual(result['cleanup']['delete_outcome'], 'accepted')

	async def test_private_model_metadata_stays_out_of_default_result(self):
		usage = self.directory / 'model-usage.json'
		trace = self.directory / 'agent-trace.json'
		usage.write_text(json.dumps({'completion_id': 'private-completion-id'}))
		trace.write_text(json.dumps({'page_url': 'https://private.example/path'}))
		result, code = await execute(self.life, False, self.good_runner)
		self.assertEqual(code, 0)
		self.assertNotIn('model_usage', result)
		self.assertNotIn('agent_trace', result)
		self.assertIn('private-completion-id', usage.read_text())
		self.assertIn('private.example', trace.read_text())

	async def test_delete_200_and_202_facts_survive_state_reload(self):
		await self.life.create()
		for status_code in (200, 202):
			for terminal in ('failed', 'released'):
				with self.subTest(status_code=status_code, terminal=terminal):
					self.state.intent.delete_accepted = False
					self.state.intent.delete_http_status = None
					deleted = False

					def respond(request):
						nonlocal deleted
						if request.method == 'DELETE':
							deleted = True
							data = projection('stopping', 'settling') if status_code == 202 else projection(terminal, 'waived')
							return httpx.Response(status_code, json={'code': 'ok', 'data': data})
						data = projection(terminal, 'waived') if deleted else projection()
						return httpx.Response(200, json={'code': 'ok', 'data': data})

					with patch.object(self.client, '_transport', httpx.MockTransport(respond)):
						facts = await self.life.finish()
					self.assertTrue(facts['complete'])
					self.assertEqual(facts['released'], terminal == 'released')
					self.assertEqual(facts['billing_status'], 'waived')
					self.assertEqual(facts['delete_accepted'], status_code == 202)
					self.assertEqual(facts['delete_http_status'], status_code)
					self.assertEqual(facts['delete_outcome'], 'accepted' if status_code == 202 else 'already_terminal')
					self.state.close()
					self.state = State(self.directory, 'test-key-not-real', True)
					self.life = FastLifecycle(self.client, self.state, 0.001)
					for field in ('delete_accepted', 'delete_http_status', 'delete_outcome'):
						self.assertEqual(self.life.report()[field], facts[field])

	async def test_later_200_or_unknown_preserves_only_historical_202_acceptance(self):
		stopping = False

		def pending(request):
			nonlocal stopping
			if request.method == 'DELETE':
				stopping = True
			data = projection('stopping', 'settling') if stopping else projection('starting', 'preparing')
			return httpx.Response(202 if request.method in ('POST', 'DELETE') else 200, json={'code': 'ok', 'data': data})

		with patch.object(self.client, '_transport', httpx.MockTransport(pending)):
			initial, code = await execute(self.life, True)
		self.assertEqual(code, 2)
		self.assertTrue(initial['cleanup']['delete_accepted'])
		self.state.close()
		self.state = State(self.directory, 'test-key-not-real', True)
		self.life = FastLifecycle(self.client, self.state, 0.001)
		for unknown in (False, True):

			def respond(request):
				if request.method == 'DELETE' and unknown:
					raise httpx.ReadTimeout('synthetic lost response')
				return httpx.Response(200, json={'code': 'ok', 'data': projection('failed', 'waived')})

			with patch.object(self.client, '_transport', httpx.MockTransport(respond)):
				result, code = await execute(self.life, True)
			facts = result['cleanup']
			self.assertEqual(code, 0)
			self.assertTrue(facts['complete'])
			self.assertFalse(facts['released'])
			self.assertTrue(facts['delete_accepted'])
			self.assertEqual(facts['delete_http_status'], None if unknown else 200)
			self.assertEqual(facts['delete_outcome'], 'unknown' if unknown else 'already_terminal')
			self.state.close()
			self.state = State(self.directory, 'test-key-not-real', True)
			self.life = FastLifecycle(self.client, self.state, 0.001)
			self.assertEqual(self.life.report()['delete_outcome'], facts['delete_outcome'])

	async def test_legacy_ambiguous_acceptance_is_not_promoted_to_202_evidence(self):
		await self.life.create()
		identity = (self.state.intent.session_id, self.state.intent.idempotency_key, self.state.intent.body)
		legacy = self.state.intent.model_dump(mode='json')
		legacy.update(schema_version=1, delete_accepted=True, delete_attempted=True)
		legacy.pop('delete_http_status')
		self.state.close()
		(self.directory / 'intent.json').write_text(json.dumps(legacy))
		self.state = State(self.directory, 'test-key-not-real', True)
		self.life = FastLifecycle(self.client, self.state, 0.001)
		self.assertEqual(self.state.intent.schema_version, 2)
		self.assertEqual((self.state.intent.session_id, self.state.intent.idempotency_key, self.state.intent.body), identity)
		self.assertFalse(self.life.report()['delete_accepted'])
		self.assertEqual(self.life.report()['delete_outcome'], 'unknown')
		self.assertIsNone(self.life.report()['delete_http_status'])

	async def test_unknown_create_recovery_uses_original_key_and_body_no_agent(self):
		self.fail_create = True
		result, code = await execute(self.life, False, self.good_runner)
		self.assertEqual(code, 1)
		self.assertIsNone(result['cleanup']['released'])
		self.assertNotIn('private', json.dumps(result))
		self.state.close()
		self.state = State(self.directory, 'test-key-not-real', True)
		self.life = FastLifecycle(self.client, self.state, 0.001)
		self.fail_create = False
		result, code = await execute(self.life, True)
		self.assertEqual(code, 0)
		creates = [r for r in self.calls if r.method == 'POST']
		self.assertEqual(len(creates), 2)
		self.assertEqual(creates[0].headers['Idempotency-Key'], creates[1].headers['Idempotency-Key'])
		self.assertEqual(creates[0].content, creates[1].content)
		self.assertNotIn('task', result)

	async def test_ready_timeout_and_terminal_both_cleanup(self):
		for status in ('starting', 'stopping'):
			with self.subTest(status=status):
				self.get_status, self.stopped = status, False
				result, code = await execute(self.life, False, self.good_runner)
				self.assertEqual(code, 1)
				self.assertTrue(self.stopped)
				self.assertTrue(result['cleanup']['released'])

	async def test_control_failure_cleanup(self):
		self.control_error = True
		result, code = await execute(self.life, False, self.good_runner)
		self.assertEqual(code, 1)
		self.assertTrue(result['cleanup']['released'])

	async def test_cancellation_during_cleanup_waits_for_release(self):
		entered = asyncio.Event()
		original_finish = self.life.finish

		async def delayed_finish():
			entered.set()
			await asyncio.sleep(0.01)
			return await original_finish()

		with patch.object(self.life, 'finish', delayed_finish):
			task = asyncio.create_task(execute(self.life, False, self.good_runner))
			await entered.wait()
			task.cancel()
			result, code = await task
		self.assertEqual(code, 130)
		self.assertTrue(result['cleanup']['released'])

	async def test_worker_hard_deadline_and_cancellation_reap_process(self):
		original_spawn = asyncio.create_subprocess_exec
		for cancel in (False, True):
			started = asyncio.Event()
			processes = []

			async def capture_spawn(*args, **kwargs):
				process = await original_spawn(*args, **kwargs)
				processes.append(process)
				started.set()
				return process

			with patch('asyncio.create_subprocess_exec', capture_spawn):
				task = asyncio.create_task(run_worker('wss://127.0.0.1:1/synthetic-not-a-real-grant', 0.05, smoke=True))
				await started.wait()
				if cancel:
					task.cancel()
				with self.assertRaises(asyncio.CancelledError if cancel else TimeoutError):
					await task
			self.assertIsNotNone(processes[0].returncode)

	async def test_connection_task_exception_timeout_and_cancellation_cleanup(self):
		for error, expected in (
			(ConnectionError(), 1),
			(RuntimeError(), 1),
			(TimeoutError(), 1),
			(asyncio.CancelledError(), 130),
		):
			with self.subTest(error=type(error).__name__):
				self.stopped = False

				async def fail(url, timeout, usage_path=None, trace_path=None):
					raise error

				result, code = await execute(self.life, False, fail)
				self.assertEqual(code, expected)
				self.assertTrue(result['cleanup']['released'])

	async def test_pending_then_follow_up_without_recreate_or_task_replay(self):
		self.pending = True
		result, code = await execute(self.life, False, self.good_runner)
		self.assertEqual(code, 2)
		self.assertTrue(result['cleanup']['released'])
		self.assertEqual(result['cleanup']['billing_status'], 'settling')
		self.assertIsNone(result['cleanup']['actual_charge_centipoints'])
		self.assertIsNotNone(result['cleanup']['charge_stop_at'])
		before = len(self.calls)
		self.pending = False
		result, code = await execute(self.life, True)
		self.assertEqual(code, 0)
		self.assertTrue(all(r.method == 'GET' for r in self.calls[before:]))

	async def test_delete_unknown_can_be_verified_by_get(self):
		self.fail_delete = True
		result, code = await execute(self.life, False, self.good_runner)
		self.assertEqual(code, 0)
		self.assertFalse(result['cleanup']['delete_accepted'])
		self.assertTrue(result['cleanup']['released'])

	async def test_no_fresh_facts_does_not_claim_saved_release(self):
		await execute(self.life, False, self.good_runner)
		self.fail_get = self.fail_delete = True
		result, code = await execute(self.life, True)
		self.assertEqual(code, 2)
		self.assertIsNone(result['cleanup']['released'])
		self.assertEqual(result['cleanup']['billing_status'], 'unknown')

	async def test_wrong_identity_or_profile_cannot_replace_owned_id(self):
		await self.life.create()
		for data in (projection(session_id='session-other'), dict(projection(), profile_id='profile-other')):
			with self.assertRaises(SafeError):
				self.life.observe(data)
		self.assertEqual(self.state.intent.session_id, 'session-owned')

	async def test_failed_final_billing_resolves_but_is_not_released(self):
		for billing in ('waived', 'settled'):
			with self.subTest(billing=billing):
				await self.life.create()
				self.calls.clear()

				def terminal(request):
					self.calls.append(request)
					data = projection('failed', billing)
					data['billing']['actual_charge_centipoints'] = 0
					return httpx.Response(200, json={'code': 'ok', 'data': data})

				with patch.object(self.client, '_transport', httpx.MockTransport(terminal)):
					result, code = await execute(self.life, False, self.good_runner)
					self.assertEqual(code, 1)
					self.assertEqual([r.method for r in self.calls], ['GET', 'GET', 'DELETE'])
					facts = result['cleanup']
					self.assertTrue(facts['complete'])
					self.assertFalse(facts['released'])
					self.assertEqual(facts['resource_outcome'], 'startup_failed')
					self.assertFalse(facts['delete_accepted'])
					self.assertEqual(facts['delete_outcome'], 'already_terminal')
					self.assertEqual(facts['billing_status'], billing)
					self.assertEqual(facts['actual_charge_centipoints'], 0)
					self.assertIsNone(facts['charge_stop_at'])
					self.assertIsNone(facts['next_action'])
					self.assertNotIn('task', result)
					self.calls.clear()
					result, code = await execute(self.life, True)
					self.assertEqual(code, 0)
					self.assertEqual([r.method for r in self.calls], ['GET', 'DELETE'])

	async def test_failed_pending_or_review_billing_remains_unresolved(self):
		await self.life.create()
		for billing in ('preparing', 'reserved', 'settling', 'settlement_pending', 'review_required'):
			with self.subTest(billing=billing):

				def terminal(request):
					return httpx.Response(200, json={'code': 'ok', 'data': projection('failed', billing)})

				with patch.object(self.client, '_transport', httpx.MockTransport(terminal)):
					result, code = await execute(self.life, True)
				self.assertEqual(code, 2)
				self.assertFalse(result['cleanup']['complete'])
				self.assertFalse(result['cleanup']['released'])
				self.assertIsNone(result['cleanup']['actual_charge_centipoints'])
				self.assertIsNotNone(result['cleanup']['next_action'])

	async def test_run_refuses_existing_intent_and_parallel_recovery(self):
		with self.assertRaises(FileExistsError):
			State(self.directory, 'test-key-not-real', False)
		with self.assertRaises(BlockingIOError):
			State(self.directory, 'test-key-not-real', True)
		stored = (self.directory / 'intent.json').read_text()
		self.assertNotIn('test-key-not-real', stored)
		self.assertNotIn('wss://', stored)
		self.assertEqual((self.directory / 'intent.json').stat().st_mode & 0o777, 0o600)


class SingleUseConnectionTests(unittest.IsolatedAsyncioTestCase):
	async def test_drop_registration_races_never_schedule_reconnect(self):
		# No library monkeypatch: use its actual callback seam and inspect its task.
		for already_done, cancelled, intentional in (
			(False, False, False),
			(True, False, False),
			(False, True, False),
			(True, True, False),
			(False, False, True),
		):
			with self.subTest(already_done=already_done, cancelled=cancelled, intentional=intentional):
				drops = []
				browser = single_use_browser('wss://control.invalid/one-time', lambda: drops.append(True))
				task = asyncio.get_running_loop().create_future()
				setattr(browser, '_cdp_client_root', type('Root', (), {'_message_handler_task': task})())

				def end():
					if cancelled:
						task.cancel()
					else:
						task.set_result(None)

				if already_done:
					end()
				browser._attach_ws_drop_callback()
				browser._intentional_stop = intentional
				if not already_done:
					end()
				await asyncio.sleep(0)
				await asyncio.sleep(0)
				self.assertEqual(drops, [] if intentional else [True])
				self.assertIsNone(browser._reconnect_task)
				with self.assertRaises(SafeError):
					await browser.reconnect()

	async def test_missing_transport_or_changed_version_fails_closed(self):
		browser = single_use_browser('wss://control.invalid/one-time', lambda: None)
		with self.assertRaises(SafeError):
			browser._attach_ws_drop_callback()
		with patch('main.version', return_value='0.13.14'), self.assertRaises(SafeError):
			single_use_browser('wss://control.invalid/one-time', lambda: None)


@unittest.skipUnless(os.environ.get('CAPY_LOCAL_CHROME'), 'Set CAPY_LOCAL_CHROME for the optional real CDP disconnect test.')
class RealDisconnectTests(unittest.IsolatedAsyncioTestCase):
	async def test_socket_drop_exits_worker_and_reaches_delete_without_retry(self):
		await self.exercise_drop('navigation')

	async def test_socket_drop_during_startup_reaches_delete_without_retry(self):
		await self.exercise_drop('startup')

	async def exercise_drop(self, stage):
		from websockets.asyncio.client import connect
		from websockets.asyncio.server import serve

		with tempfile.TemporaryDirectory(prefix='capy-drop-test-') as temp:
			chrome = await asyncio.create_subprocess_exec(
				os.environ['CAPY_LOCAL_CHROME'],
				'--headless=new',
				'--remote-debugging-port=0',
				'--remote-debugging-address=127.0.0.1',
				'--user-data-dir=' + temp,
				'--no-first-run',
				'--no-default-browser-check',
				'about:blank',
				stdout=asyncio.subprocess.DEVNULL,
				stderr=asyncio.subprocess.DEVNULL,
			)
			state = None
			try:
				active = Path(temp) / 'DevToolsActivePort'
				async with asyncio.timeout(15):
					for _ in range(300):
						if active.exists():
							break
						await asyncio.sleep(0.05)
				port, path = active.read_text().splitlines()[:2]
				attempts, drops, deletes = [], [], []

				async def bridge(client):
					attempts.append(time.monotonic())
					if len(attempts) > 1:
						await client.close(code=1008)
						return
					async with connect(f'ws://127.0.0.1:{port}{path}', proxy=None) as upstream:

						async def forward():
							async for message in client:
								command = json.loads(message)
								if stage == 'startup' or (
									command.get('method') == 'Page.navigate'
									and command.get('params', {}).get('url') == 'https://www.w3.org/Provider/Style/dummy.html'
								):
									drops.append(time.monotonic())
									client.transport.abort()
									return
								await upstream.send(message)

						async def backward():
							async for message in upstream:
								await client.send(message)

						tasks = [asyncio.create_task(forward()), asyncio.create_task(backward())]
						try:
							await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
						finally:
							for task in tasks:
								task.cancel()
							await asyncio.gather(*tasks, return_exceptions=True)

				def management(request):
					if request.method == 'DELETE':
						deletes.append(time.monotonic())
					data = projection('released', 'waived') if deletes else projection()
					return httpx.Response(202 if request.method == 'POST' else 200, json={'code': 'ok', 'data': data})

				state = State(Path(temp) / 'run', 'synthetic-test-key', False)
				async with (
					serve(bridge, '127.0.0.1', 0) as server,
					httpx.AsyncClient(base_url=BASE, transport=httpx.MockTransport(management)) as client,
				):
					url = f'ws://127.0.0.1:{next(iter(server.sockets)).getsockname()[1]}/synthetic-single-use'
					life = Lifecycle(client, state, poll=0.01)

					async def runner(url, timeout, usage_path=None, trace_path=None):
						return await run_worker(url, min(timeout, 25), smoke=True)

					# Only management/control is mocked; Browser/CDP, socket drop, and worker are real.
					with patch.object(life, 'control', AsyncMock(return_value=url)):
						result, code = await execute(life, False, runner)
				self.assertEqual(code, 1)
				if stage == 'navigation':
					self.assertIn('Control connection lost', result['error'])
				else:
					# Initial CDP setup can itself fail before the monitor sees its task.
					self.assertIn(
						result['error'],
						(
							'Control connection lost; worker stopped without reconnecting. Ending the owned Session.',
							'Browser task failed; raw library diagnostics suppressed.',
						),
					)
				self.assertEqual(len(attempts), 1)
				self.assertEqual(len(drops), 1)
				self.assertEqual(len(deletes), 1)
				self.assertLess(deletes[0] - drops[0], 2)
				self.assertTrue(result['cleanup']['complete'])
				print(f'local_drop ({stage}): handshakes=1; reconnects=0; drop_to_mock_DELETE={deletes[0] - drops[0]:.3f}s')
			finally:
				if state:
					state.close()
				chrome.terminate()
				try:
					await asyncio.wait_for(chrome.wait(), timeout=10)
				except TimeoutError:
					chrome.kill()
					await asyncio.wait_for(chrome.wait(), timeout=5)


if __name__ == '__main__':
	unittest.main()
