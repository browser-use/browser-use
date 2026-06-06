"""Run one eval task through the local Rust wrapper and a Browser Use Cloud browser.

Usage:
    BROWSER_USE_API_KEY=... EVALUATION_TOOL_URL=... EVALUATION_TOOL_SECRET_KEY=... \
      ANTHROPIC_API_KEY=... \
      uv run python examples/rust/eval_one_task_cloud.py real_v8 3

This is the local hard-task loop for the Rust-backed browser-use path:
- fetch one eval task,
- create a Browser Use Cloud browser and use its CDP URL,
- run browser_use.rust.Agent with BrowserSession(cdp_url=...),
- print session ids, trace/cost, final answer, and state-db hints,
- stop the cloud browser in finally.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests

from browser_use.browser import BrowserSession
from browser_use.browser.cloud.cloud import CloudBrowserClient, CloudBrowserError
from browser_use.browser.cloud.views import CreateBrowserRequest
from browser_use.rust import Agent


def _resolve_llm(model_name: str):
	low = model_name.lower()
	if low.startswith('claude') or 'sonnet' in low or 'haiku' in low or 'opus' in low:
		from browser_use.llm.anthropic.chat import ChatAnthropic

		return ChatAnthropic(model=model_name)
	if low.startswith('gemini') or 'gemini' in low:
		from browser_use.llm.google.chat import ChatGoogle

		return ChatGoogle(model=model_name)
	if low.startswith('deepseek'):
		from browser_use.llm.deepseek.chat import ChatDeepSeek

		return ChatDeepSeek(model=model_name)
	if low.startswith('openrouter'):
		from browser_use.llm.openrouter.chat import ChatOpenRouter

		return ChatOpenRouter(model=model_name)
	from browser_use.llm.openai.chat import ChatOpenAI

	return ChatOpenAI(model=model_name)


def _request_with_retry(method: str, url: str, **kwargs: Any) -> requests.Response:
	kwargs.setdefault('timeout', 30)
	for attempt in range(3):
		try:
			response = requests.request(method, url, **kwargs)
			response.raise_for_status()
			return response
		except requests.RequestException:
			if attempt == 2:
				raise
			time.sleep(2**attempt)
	raise RuntimeError('unreachable retry state')


def fetch_task(test_case_name: str, task_index: int) -> dict[str, Any]:
	url = os.environ['EVALUATION_TOOL_URL'].rstrip('/') + '/api/getTestCase'
	response = _request_with_retry(
		'post',
		url,
		headers={
			'Authorization': f'Bearer {os.environ["EVALUATION_TOOL_SECRET_KEY"]}',
			'Content-Type': 'application/json',
		},
		json={'name': test_case_name},
	)
	tasks = response.json()
	if not isinstance(tasks, list):
		raise RuntimeError(f'unexpected response shape: {type(tasks)}')
	if task_index < 0 or task_index >= len(tasks):
		raise IndexError(f'task_index {task_index} out of range, dataset has {len(tasks)} tasks')
	return tasks[task_index]


def task_text_from_record(task: dict[str, Any]) -> str:
	text = task.get('confirmed_task') or task.get('task') or task.get('description') or ''
	website = task.get('website') or ''
	if website:
		text = f'{text}\nwebsite: {website}'
	return text


def _maybe_set_local_terminal_binary() -> None:
	if os.environ.get('BROWSER_USE_TERMINAL_BINARY'):
		return
	repo_root = Path(__file__).resolve().parents[2]
	terminal_root = repo_root.parent / 'terminal'
	for candidate in [
		terminal_root / 'target' / 'debug' / 'browser-use-terminal',
		terminal_root / 'target' / 'release' / 'browser-use-terminal',
	]:
		if candidate.exists():
			os.environ['BROWSER_USE_TERMINAL_BINARY'] = str(candidate)
			return


def _state_db_hint(state_dir: str | None) -> Path:
	if state_dir:
		return Path(state_dir).expanduser() / 'state.db'
	return Path('~/.browser-use-terminal/state.db').expanduser()


async def _stop_cloud_browser(client: CloudBrowserClient, session_id: str | None) -> None:
	if not session_id:
		return
	for attempt in range(3):
		try:
			await client.stop_browser(session_id)
			return
		except CloudBrowserError as error:
			if attempt == 2:
				print(f'warning: failed to stop cloud browser {session_id}: {error}', file=sys.stderr)
				return
			await asyncio.sleep(2**attempt)


async def run_one(args: argparse.Namespace) -> int:
	_maybe_set_local_terminal_binary()
	os.environ.setdefault('BU_RUST_FORCE_SCREENSHOTS', '1')

	task = fetch_task(args.test_case_name, args.task_index)
	task_id = task.get('task_id') or task.get('id') or 'unknown'
	text = task_text_from_record(task)

	cloud = CloudBrowserClient(api_base_url=args.cloud_api_base_url)
	browser_id: str | None = None
	try:
		cloud_response = await cloud.create_browser(
			CreateBrowserRequest(
				timeout=args.cloud_timeout_minutes,
				proxy_country_code=args.cloud_proxy_country_code,
				enable_recording=args.enable_recording,
			)
		)
		browser_id = cloud_response.id
		browser_session = BrowserSession(cdp_url=cloud_response.cdpUrl)

		print(f'== task {task_id} ({args.test_case_name} #{args.task_index}) ==')
		print(text[:500])
		print()
		print('== cloud browser ==')
		print(f'  id      : {cloud_response.id}')
		print(f'  live    : {cloud_response.liveUrl}')
		print(f'  cdp     : {cloud_response.cdpUrl}')
		print()

		llm = _resolve_llm(args.model)
		state_dir = Path(args.state_dir).expanduser() if args.state_dir else None
		agent = Agent(task=text, llm=llm, browser_session=browser_session, state_dir=state_dir)
		result = await agent.run(max_steps=args.max_steps)

		usage = result.usage
		print('== run ==')
		print(f'  rust session : {result.session_id}')
		print(f'  steps        : {len(result.steps)}')
		print(f'  duration     : {(result.duration_seconds or 0):.1f}s')
		print(f'  exit_code    : {result.exit_code}')
		print(f'  input tokens : {usage.input_tokens}')
		print(f'  output tokens: {usage.output_tokens}')
		print(f'  cost         : ${usage.cost:.4f}')
		print(f'  model        : {usage.model}')
		if trace_url := result.laminar_trace_url():
			print(f'  laminar      : {trace_url}')
		print(f'  state db     : {_state_db_hint(args.state_dir)}')
		if result.session_id:
			print(f'  events       : browser-use-terminal events {result.session_id}')
			print(f'  show         : browser-use-terminal show {result.session_id}')
			print(
				'  inspect      : uv run python examples/rust/inspect_rust_trace.py '
				f'{_state_db_hint(args.state_dir)} {result.session_id}'
			)
		print()

		print('== final ==')
		print((result.final_summary or '(no final summary)')[:2000])
		print()

		print('== steps ==')
		for index, step in enumerate(result.steps):
			print(f'  {index:>2} {step.tool or "?":<16} screenshots={len(step.screenshot_paths)}')

		if args.judge:
			print()
			print('== judge ==')
			await agent._judge_and_log()
			judgement = result.judgement()
			if judgement:
				print(f'  verdict: {judgement.get("verdict")}')
				if judgement.get('failure_reason'):
					print(f'  failure: {judgement["failure_reason"][:500]}')
				if judgement.get('reasoning'):
					print(f'  reasoning: {judgement["reasoning"][:1000]}')
			else:
				print('  (no judgement returned)')

		return result.exit_code
	finally:
		await _stop_cloud_browser(cloud, browser_id)
		await cloud.close()


def parse_args(argv: list[str]) -> argparse.Namespace:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument('test_case_name', help='Eval test case name, for example real_v8')
	parser.add_argument('task_index', type=int, help='Zero-based task index')
	parser.add_argument('--model', default=os.environ.get('BU_MODEL', 'claude-sonnet-4-6'))
	parser.add_argument('--max-steps', type=int, default=int(os.environ.get('BU_MAX_STEPS', '150')))
	parser.add_argument('--state-dir', default=os.environ.get('BU_RUST_STATE_DIR'))
	parser.add_argument('--cloud-api-base-url', default=os.environ.get('BROWSER_USE_CLOUD_API_URL', 'https://api.browser-use.com'))
	parser.add_argument('--cloud-timeout-minutes', type=int, default=int(os.environ.get('BU_CLOUD_TIMEOUT_MINUTES', '30')))
	parser.add_argument('--cloud-proxy-country-code', default=os.environ.get('BU_CLOUD_PROXY_COUNTRY_CODE'))
	parser.add_argument('--enable-recording', action='store_true', default=os.environ.get('BU_CLOUD_ENABLE_RECORDING') == '1')
	parser.add_argument('--judge', action='store_true', default=os.environ.get('BU_JUDGE') == '1')
	return parser.parse_args(argv)


def main() -> None:
	args = parse_args(sys.argv[1:])
	raise SystemExit(asyncio.run(run_one(args)))


if __name__ == '__main__':
	main()
