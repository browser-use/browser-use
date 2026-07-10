"""
Use raw CDP from a Python cell during an agent run.

This example enables `Agent(code=True)`, which gives the model access to a
`run_python` action. The Python cell can call helpers such as:

- `await cdp("Domain.method", params)` for raw Chrome DevTools Protocol calls
- `await js("...")` for page JavaScript via Runtime.evaluate
- `open("relative-path")` or `WORKSPACE_DIR / "path"` for persistent files

Only enable this for trusted tasks. Cells execute directly inside the agent
worker process; run that worker under an external supervisor when hard killing
and restartability are required.
"""

import asyncio
import json
import logging
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from browser_use import Agent, Browser
from browser_use.llm.google.chat import ChatGoogle

load_dotenv()

FINAL_RESULT_LOG_CHARS = 1500
RUNS_DIR = Path(__file__).resolve().parent / 'raw_cdp_code_mode_runs'
# TASK = """go to netflix and get me prices for all countries https://help.netflix.com/en/node/24926"""
TASK = """go to hackernews and get top 5 posts with their top comment in a json"""
# TASK = """go to google flights and find a one way flight from SFO to Zurich on August 1st"""


class FinalResultClipFilter(logging.Filter):
	def filter(self, record: logging.LogRecord) -> bool:
		message = record.getMessage()
		marker = 'Final Result:'
		marker_index = message.find(marker)
		if marker_index == -1:
			return True

		prefix_end = marker_index + len(marker)
		record.msg = message[:prefix_end] + clip_text(message[prefix_end:])
		record.args = ()
		return True


def clip_text(value: Any, max_chars: int = FINAL_RESULT_LOG_CHARS) -> str:
	text = '' if value is None else str(value)
	if len(text) <= max_chars:
		return text
	remaining_chars = len(text) - max_chars
	return f'{text[:max_chars]}\n...[truncated {remaining_chars} chars; see saved run artifacts]'


def write_json(path: Path, data: Any) -> None:
	path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def create_run_dir() -> Path:
	run_dir = RUNS_DIR / datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
	run_dir.mkdir(parents=True, exist_ok=True)
	return run_dir


def install_run_logging(run_dir: Path) -> logging.FileHandler:
	log_filter = FinalResultClipFilter()
	file_handler = logging.FileHandler(run_dir / 'agent.log', encoding='utf-8')
	file_handler.setLevel(logging.INFO)
	file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)-8s [%(name)s] %(message)s'))
	file_handler.addFilter(log_filter)

	for logger_name in ('browser_use', 'bubus'):
		logger = logging.getLogger(logger_name)
		logger.addFilter(log_filter)
		logger.addHandler(file_handler)
		for handler in logger.handlers:
			handler.addFilter(log_filter)

	return file_handler


def extract_run_python_cells(history) -> list[dict[str, Any]]:
	cells: list[dict[str, Any]] = []
	for action in history.model_actions():
		run_python = action.get('run_python')
		if not run_python:
			continue
		cells.append({'index': len(cells) + 1, 'code': run_python.get('code', '')})
	return cells


def format_price_line(history) -> str:
	if history is None or history.usage is None:
		return 'Price: unavailable (no usage summary was returned by the LLM provider)'
	return (
		f'Price: ${history.usage.total_cost:.6f} '
		f'({history.usage.total_tokens} tokens across {history.usage.entry_count} LLM call(s))'
	)


def save_run_artifacts(agent: Agent, history, run_dir: Path, run_error: Exception | None = None) -> None:
	file_system_dir = str(agent.file_system.get_dir()) if agent.file_system else None
	(run_dir / 'agent_file_system_dir.txt').write_text(file_system_dir or '', encoding='utf-8')

	if run_error is not None:
		(run_dir / 'error.txt').write_text(
			''.join(traceback.format_exception(type(run_error), run_error, run_error.__traceback__)),
			encoding='utf-8',
		)

	if history is None:
		write_json(
			run_dir / 'summary.json',
			{
				'task': TASK,
				'run_error': repr(run_error) if run_error else None,
				'agent_file_system_dir': file_system_dir,
			},
		)
		return

	history.save_to_file(run_dir / 'history.json')
	(run_dir / 'final_result.txt').write_text(history.final_result() or '', encoding='utf-8')
	write_json(run_dir / 'model_actions.json', history.model_actions())
	write_json(
		run_dir / 'action_results.json',
		[result.model_dump(exclude_none=True, mode='json') for result in history.action_results()],
	)
	write_json(run_dir / 'usage.json', history.usage.model_dump(mode='json') if history.usage else None)

	run_python_cells = extract_run_python_cells(history)
	write_json(run_dir / 'run_python_cells.json', run_python_cells)
	(run_dir / 'run_python_cells.py').write_text(
		'\n\n'.join(f'# --- run_python code #{cell["index"]} ---\n{cell["code"].rstrip()}\n' for cell in run_python_cells)
		or '# No run_python code was executed.\n',
		encoding='utf-8',
	)

	write_json(
		run_dir / 'summary.json',
		{
			'task': TASK,
			'run_error': repr(run_error) if run_error else None,
			'is_done': history.is_done(),
			'is_successful': history.is_successful(),
			'has_errors': history.has_errors(),
			'steps': history.number_of_steps(),
			'duration_seconds': history.total_duration_seconds(),
			'urls': history.urls(),
			'action_names': history.action_names(),
			'final_result_chars': len(history.final_result() or ''),
			'final_result_preview': clip_text(history.final_result()),
			'run_python_cell_count': len(run_python_cells),
			'agent_file_system_dir': file_system_dir,
			'usage': history.usage.model_dump(mode='json') if history.usage else None,
		},
	)


def print_run_python_code(history) -> None:
	if history is None:
		print('\nNo agent history was returned.')
		return

	run_python_actions = [cell['code'] for cell in extract_run_python_cells(history)]

	if not run_python_actions:
		print('\nNo run_python code was executed.')
		return

	for index, code in enumerate(run_python_actions, start=1):
		print(f'\n--- run_python code #{index} ---')
		print(code.rstrip())


async def main():
	run_dir = create_run_dir()
	install_run_logging(run_dir)
	print(f'Run artifacts will be saved to: {run_dir}')

	agent = Agent(
		# task=(
		# 	'Go to https://quotes.toscrape.com/. '
		# 	'Use run_python with await js(...) to extract the first 5 quotes and authors from the DOM. '
		# 	'Save them to quotes.json using normal pathlib, then return the JSON.'
		# ),
		task=TASK,
		# llm=ChatBrowserUse(model='bu-2-0'),
		# llm=ChatOpenAI(model='gpt-5.5'),
		llm=ChatGoogle(model='gemini-3.5-flash'),
		browser=Browser(use_cloud=True),
		code=True,
		code_timeout=300,
		calculate_cost=True,
	)

	history = None
	run_error: Exception | None = None
	try:
		history = await agent.run(max_steps=10)
	except Exception as exc:
		run_error = exc
		history = agent.history

	print(f'\nFinal result (first {FINAL_RESULT_LOG_CHARS} chars):')
	print(clip_text(history.final_result() if history else None))
	print_run_python_code(history)

	save_run_artifacts(agent, history, run_dir, run_error)

	if run_error is not None:
		print(f'\nRun failed: {type(run_error).__name__}: {run_error}')
		print(f'Error traceback: {run_dir / "error.txt"}')
	print(f'\nRun artifacts saved to: {run_dir}')
	history_path = run_dir / 'history.json'
	print(f'History JSON: {history_path if history_path.exists() else "not written"}')
	price_line = format_price_line(history)
	with (run_dir / 'agent.log').open('a', encoding='utf-8') as log_file:
		log_file.write(f'\n{price_line}\n')
	print(price_line)
	return 1 if run_error else 0


if __name__ == '__main__':
	raise SystemExit(asyncio.run(main()))
