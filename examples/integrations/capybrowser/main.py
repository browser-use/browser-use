"""Run one public reading task, then explicitly end the owned Capy Session."""

import argparse
import asyncio
import contextlib
import json
import logging
import os
import signal
import sys
import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import cast

import httpx
from gateway_model import GatewayModel
from lifecycle import BASE, Lifecycle, SafeError, State

TARGET = 'https://www.w3.org/Provider/Style/dummy.html'
TARGET_TITLE = '(Dummy link end from examples) -- Style guide'
TASK = f'Open {TARGET}. Report the page heading and the sentence explaining why this link exists in examples. Do not follow links, submit forms, or invent content.'


def single_use_browser(cdp_url: str, on_disconnect: Callable[[], None]):
	"""Instance-only adapter for the pinned version's private drop callback.

	0.13.13 has no public reconnect switch. Never attach its retry callback: a
	consumed Capy grant cannot be reused. Fail closed on version/transport drift.
	"""
	from browser_use import Browser
	from browser_use.browser import BrowserProfile

	if version('browser-use') != '0.13.13':
		raise SafeError('This example requires the reviewed browser-use 0.13.13 connection lifecycle.')
	used = False
	watched = None

	class SingleUseBrowser(Browser):
		async def connect(self, cdp_url: str | None = None):
			nonlocal used
			if used:
				raise SafeError('The control grant was already used; end this Session.')
			used = True

			async def watch_startup():
				# Upstream registers its callback only after CDP setup. Also observe
				# the transport during setup, where a drop can leave a command waiting.
				while True:
					if isinstance(getattr(self._cdp_client_root, '_message_handler_task', None), asyncio.Future):
						self._attach_ws_drop_callback()
						return
					await asyncio.sleep(0.01)

			watcher = asyncio.create_task(watch_startup())
			try:
				return await super().connect(cdp_url)
			finally:
				watcher.cancel()
				await asyncio.gather(watcher, return_exceptions=True)

		async def reconnect(self) -> None:
			raise SafeError('Reconnecting with a consumed control grant is disabled.')

		def _attach_ws_drop_callback(self) -> None:
			nonlocal watched
			# Override only this instance's callback registration, never the library class.
			task = getattr(self._cdp_client_root, '_message_handler_task', None)
			if not isinstance(task, asyncio.Future):
				raise SafeError('Cannot monitor the single-use control connection.')
			if task is watched:
				return
			watched = task

			def dropped(_future):
				if not self._intentional_stop:
					on_disconnect()

			# Also handles a socket that closed BEFORE registration (including cancellation).
			task.add_done_callback(dropped)

	return SingleUseBrowser(
		browser_profile=BrowserProfile(
			cdp_url=cdp_url,
			is_local=False,
			keep_alive=True,
			allowed_domains=['www.w3.org'],
			enable_default_extensions=False,
			accept_downloads=False,
		)
	)


def save_agent_trace(path: Path, agent) -> None:
	"""Persist only action names, result flags and public page-state metadata."""
	history = agent.history
	trace = {
		'history_is_successful': history.is_successful(),
		'final_result_length': len(history.final_result() or ''),
		'steps': [
			{
				'page_url': item.state.url,
				'page_title': item.state.title,
				'actions': [list(action.model_dump(exclude_none=True)) for action in item.model_output.action]
				if item.model_output
				else None,
				'results': [
					{
						'is_done': result.is_done,
						'success': result.success,
						'has_error': bool(result.error),
						'content_length': len(result.extracted_content or ''),
					}
					for result in item.result
				],
			}
			for item in history.history
		],
	}
	tmp = path.with_suffix('.tmp')
	with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as stream:
		json.dump(trace, stream)
		stream.flush()
		os.fsync(stream.fileno())
	os.replace(tmp, path)


async def browser_task(cdp_url: str, smoke: bool = False, usage_path: Path | None = None, trace_path: Path | None = None) -> dict:
	"""Real browser-use connection; smoke mode deliberately does not run an LLM."""
	from browser_use import Agent, ChatBrowserUse, Tools

	# Drop => exit without waiting for Agent/CDP finalizers. The parent reaps this
	# child and explicitly ends Capy; no grant, page action or model task is replayed.
	browser = single_use_browser(cdp_url, lambda: os._exit(3))
	agent = None
	gateway = None
	try:
		await asyncio.wait_for(browser.start(), 20)
		if smoke:
			await asyncio.wait_for(browser.navigate_to(TARGET), 20)
			page = await browser.get_current_page()
			assert page is not None
			for _ in range(30):
				title = await page.get_title()
				if title == TARGET_TITLE:
					break
				await asyncio.sleep(0.1)
			return {
				'mode': 'connection_only',
				'title': title,
				'page': await page.evaluate(
					'() => ({title: document.title, heading: document.querySelector("h1")?.textContent, url: location.href})'
				),
			}
		with tempfile.TemporaryDirectory(prefix='capy-agent-') as directory:
			from browser_use.llm.base import BaseChatModel

			model_config = os.environ.get('CAPY_MODEL_CONFIG')
			if model_config:
				if usage_path is None:
					raise SafeError('Model usage path was not provided.')
				gateway = GatewayModel(Path(model_config), usage_path)
				llm = cast(BaseChatModel, gateway)
			else:
				llm = ChatBrowserUse()
			agent = Agent(
				task=TASK,
				llm=llm,
				browser_session=browser,
				tools=Tools(
					exclude_actions=[
						'click',
						'input',
						'upload_file',
						'send_keys',
						'evaluate',
						'dropdown_options',
						'select_dropdown',
						'write_file',
						'read_file',
						'replace_file',
						'search',
					]
				),
				file_system_path=directory,
				enable_signal_handler=False,
				generate_gif=False,
				use_vision=False,
				use_judge=False,
				enable_planning=False,
				message_compaction=False,
				final_response_after_failure=False,
				max_actions_per_step=5,
				max_failures=2,
				llm_timeout=55,
				step_timeout=75,
			)
			history = await asyncio.wait_for(agent.run(max_steps=7), 120)
			if not history.is_successful():
				raise SafeError('Agent did not report success.')
			return {'mode': 'agent', 'answer': history.final_result()}
	finally:
		if agent and trace_path:
			with contextlib.suppress(Exception):
				save_agent_trace(trace_path, agent)
		if gateway:
			with contextlib.suppress(Exception):
				await gateway.close()
		with contextlib.suppress(Exception):
			await asyncio.wait_for(browser.stop(), 5)


def worker():
	"""Keep raw library logs and exceptions out of the management process."""
	output = sys.stdout
	with open(os.devnull, 'w') as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
		logging.disable(logging.CRITICAL)
		try:
			payload = json.loads(sys.stdin.read())
			result = asyncio.run(
				browser_task(
					payload['cdp_url'],
					payload.get('smoke', False),
					Path(payload['usage_path']) if payload.get('usage_path') else None,
					Path(payload['trace_path']) if payload.get('trace_path') else None,
				)
			)
		except BaseException:
			result = {'error': 'Browser task failed or timed out; raw library diagnostics suppressed.'}
	# This single result is validated/redacted again by the parent before display.
	output.write(json.dumps(result) + '\n')


async def run_worker(
	cdp_url: str, timeout: float, smoke: bool = False, usage_path: Path | None = None, trace_path: Path | None = None
) -> dict:
	env = os.environ.copy()
	env.pop('CAPYBROWSER_API_KEY', None)
	if env.get('CAPY_MODEL_CONFIG'):
		env.pop('BROWSER_USE_API_KEY', None)
	for name in (
		'ANONYMIZED_TELEMETRY',
		'BROWSER_USE_CLOUD_SYNC',
		'BROWSER_USE_SETUP_LOGGING',
		'BROWSER_USE_VERBOSE_OBSERVABILITY',
	):
		env[name] = 'false'
	# No trace callbacks or .env auto-loading in the isolated task.
	env['PYTHON_DOTENV_DISABLED'] = '1'
	for name in list(env):
		if name.startswith(('LMNR_', 'LANGSMITH_', 'LANGFUSE_', 'OTEL_')) or name in (
			'BROWSER_USE_DEBUG_LOG_FILE',
			'BROWSER_USE_INFO_LOG_FILE',
		):
			del env[name]
	process = await asyncio.create_subprocess_exec(
		sys.executable,
		str(Path(__file__).resolve()),
		'--worker',
		stdin=asyncio.subprocess.PIPE,
		stdout=asyncio.subprocess.PIPE,
		stderr=asyncio.subprocess.DEVNULL,
		env=env,
	)
	try:
		async with asyncio.timeout(timeout):
			stdout, _ = await process.communicate(
				json.dumps(
					{
						'cdp_url': cdp_url,
						'smoke': smoke,
						'usage_path': str(usage_path) if usage_path else None,
						'trace_path': str(trace_path) if trace_path else None,
					}
				).encode()
			)
		if process.returncode or len(stdout) > 16384:
			if process.returncode == 3:
				raise SafeError('Control connection lost; worker stopped without reconnecting. Ending the owned Session.')
			raise SafeError('Browser task process failed.')
		result = json.loads(stdout)
		if result.get('error') or result.get('mode') not in ('agent', 'connection_only'):
			raise SafeError('Browser task failed; raw library diagnostics suppressed.')
		return result
	finally:
		if process.returncode is None:
			process.kill()
			await asyncio.wait_for(process.wait(), 5)


async def execute(lifecycle: Lifecycle, recover: bool, runner=run_worker) -> tuple[dict, int]:
	result = {}
	code = 0
	try:
		if not lifecycle.state.intent.session_id:
			await lifecycle.create()  # Recovery uses exactly the durable key and body.
		if not recover:
			session = await lifecycle.ready()
			url = await lifecycle.control()
			remaining = (session.expires_at - datetime.now(timezone.utc)).total_seconds() - 5
			if remaining <= 0:
				raise SafeError('Session lifetime is exhausted; ending it now.')
			result['task'] = await runner(
				url,
				min(140, remaining),
				usage_path=lifecycle.state.directory / 'model-usage.json',
				trace_path=lifecycle.state.directory / 'agent-trace.json',
			)
	except asyncio.CancelledError:
		result['error'], code = 'Cancelled; cleanup attempted.', 130
	except SafeError as error:
		result['error'], code = str(error), 1
	except Exception:
		result['error'], code = 'Run failed or timed out; cleanup attempted. Retain the saved intent.', 1
	finally:
		cleanup = asyncio.create_task(lifecycle.finish())
		try:
			result['cleanup'] = await asyncio.shield(cleanup)
		except asyncio.CancelledError:
			result['error'], code = 'Cancelled during cleanup; cleanup continued.', 130
			result['cleanup'] = await asyncio.shield(cleanup)
		except Exception:
			result['cleanup'] = lifecycle.report()
			result['cleanup']['complete'] = False
	if not result['cleanup']['complete']:
		code = code or 2
	return result, code


async def run(args, key: str):
	if args.command == 'run' and version('browser-use') != '0.13.13':
		raise SafeError('Use the reviewed browser-use 0.13.13 checkout before creating a Session.')
	if args.command == 'run' and (model_config := os.environ.get('CAPY_MODEL_CONFIG')):
		# Validate the model config without a network call before any Session exists.
		model = GatewayModel(Path(model_config), args.state.parent / 'unused-model-usage.json')
		await model.close()
	state = State(args.state, key, args.command == 'recover')
	try:
		# First SIGINT/SIGTERM cancels work; repeated signals cannot interrupt bounded cleanup.
		task = asyncio.current_task()
		assert task is not None
		cancelled = False

		def cancel():
			nonlocal cancelled
			if not cancelled:
				cancelled = True
				task.cancel()

		loop = asyncio.get_running_loop()
		for sig in (signal.SIGINT, signal.SIGTERM):
			loop.add_signal_handler(sig, cancel)
		async with httpx.AsyncClient(
			base_url=BASE, headers={'Authorization': 'Bearer ' + key}, timeout=10, follow_redirects=False, trust_env=False
		) as client:
			return await execute(Lifecycle(client, state), args.command == 'recover')
	finally:
		state.close()


def cli():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument('command', choices=('run', 'recover'))
	parser.add_argument(
		'--state', required=True, type=Path, help='Private run directory; must not exist for run, must exist for recover.'
	)
	args = parser.parse_args()
	key = os.environ.get('CAPYBROWSER_API_KEY', '')
	if not key or (args.command == 'run' and not (os.environ.get('BROWSER_USE_API_KEY') or os.environ.get('CAPY_MODEL_CONFIG'))):
		print('Set CAPYBROWSER_API_KEY and, for run, BROWSER_USE_API_KEY or CAPY_MODEL_CONFIG.', file=sys.stderr)
		return 1
	try:
		result, code = asyncio.run(run(args, key))
		# Never display credential-bearing URL text, even if a model/library echoes it.
		import re

		text = json.dumps(result, ensure_ascii=True).replace(key, '[redacted]')
		text = re.sub(r'wss?://[^\s"\\]+', '[redacted control URL]', text)
		print(text)
		return code
	except Exception:
		print(
			'Could not initialize or recover this run. Keep the state directory; check its permissions, lock, and original credential.',
			file=sys.stderr,
		)
		return 1


if __name__ == '__main__':
	if sys.argv[1:] == ['--worker']:
		worker()
	else:
		sys.exit(cli())
