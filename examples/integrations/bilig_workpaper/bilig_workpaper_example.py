"""Browser Use integration for deterministic Bilig WorkPaper formula readback."""

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

sys.path.append(str(Path(__file__).resolve().parents[3]))

from browser_use import ActionResult, Agent, ChatBrowserUse, Tools

BILIG_WORKPAPER_PACKAGE = '@bilig/workpaper@0.96.0'


class FormulaReadbackRequest(BaseModel):
	"""Input passed from the browser agent to the Bilig WorkPaper tool."""

	conversion_rate: float = Field(
		default=0.4,
		ge=0,
		le=1,
		description='Conversion rate to write into the WorkPaper input cell.',
	)
	timeout_seconds: int = Field(
		default=45,
		ge=5,
		le=120,
		description='Maximum time to start the local Bilig server and read the proof.',
	)


class ForecastValues(BaseModel):
	"""Computed forecast values returned by Bilig."""

	model_config = ConfigDict(populate_by_name=True)

	expected_customers: float = Field(alias='expectedCustomers')
	expected_arr: float = Field(alias='expectedArr')
	expansion_arr: float = Field(alias='expansionArr')
	target_gap: float = Field(alias='targetGap')


class FormulaReadbackChecks(BaseModel):
	"""Verification checks returned by Bilig."""

	model_config = ConfigDict(populate_by_name=True)

	previous_value: float = Field(alias='previousValue')
	new_value: float = Field(alias='newValue')
	formulas_persisted: bool = Field(alias='formulasPersisted')
	restored_matches_after: bool = Field(alias='restoredMatchesAfter')
	computed_output_changed: bool = Field(alias='computedOutputChanged')
	serialized_bytes: int = Field(alias='serializedBytes')


class FormulaReadbackProof(BaseModel):
	"""Structured proof object returned by the Bilig formula-readback server."""

	model_config = ConfigDict(populate_by_name=True)

	verified: bool
	edited_cell: str = Field(alias='editedCell')
	before: ForecastValues
	after: ForecastValues
	restored: ForecastValues
	formula_contracts: dict[str, str] = Field(alias='formulaContracts')
	checks: FormulaReadbackChecks


def _find_open_port() -> int:
	with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
		sock.bind(('127.0.0.1', 0))
		return int(sock.getsockname()[1])


def _post_formula_readback(port: int, request: FormulaReadbackRequest) -> FormulaReadbackProof:
	url = f'http://127.0.0.1:{port}/api/workpaper/n8n/forecast'
	body = json.dumps(
		{
			'sheetName': 'Inputs',
			'address': 'B3',
			'value': request.conversion_rate,
		}
	).encode('utf-8')
	http_request = urllib.request.Request(
		url,
		data=body,
		headers={'content-type': 'application/json'},
		method='POST',
	)
	with urllib.request.urlopen(http_request, timeout=5) as response:
		payload = json.loads(response.read().decode('utf-8'))
	return FormulaReadbackProof.model_validate(payload)


def run_bilig_formula_readback(request: FormulaReadbackRequest) -> FormulaReadbackProof:
	"""Start Bilig's local formula server and return a verified WorkPaper proof."""

	port = _find_open_port()
	command = [
		'npm',
		'exec',
		'--yes',
		'--package',
		BILIG_WORKPAPER_PACKAGE,
		'--',
		'bilig-n8n-formula-server',
		'--host',
		'127.0.0.1',
		'--port',
		str(port),
	]
	with tempfile.TemporaryFile(mode='w+', encoding='utf-8') as process_log:
		process = subprocess.Popen(command, stdout=process_log, stderr=subprocess.STDOUT, text=True)
		deadline = time.monotonic() + request.timeout_seconds

		try:
			last_error: Exception | None = None
			while time.monotonic() < deadline:
				if process.poll() is not None:
					process_log.seek(0)
					output = process_log.read().strip()
					raise RuntimeError(f'Bilig server exited early with code {process.returncode}: {output}')
				try:
					return _post_formula_readback(port, request)
				except (ConnectionError, urllib.error.URLError) as exc:
					last_error = exc
					time.sleep(0.2)
				except TimeoutError as exc:
					last_error = exc
					time.sleep(0.2)

			raise TimeoutError(f'Bilig formula server did not become ready within {request.timeout_seconds}s: {last_error}')
		finally:
			if process.poll() is None:
				process.terminate()
				try:
					process.wait(timeout=5)
				except subprocess.TimeoutExpired:
					process.kill()
					process.wait(timeout=5)


def create_bilig_workpaper_tools() -> Tools:
	"""Create Browser Use tools backed by Bilig WorkPaper."""

	tools = Tools()

	@tools.action(
		'Run a Bilig WorkPaper formula readback proof for a quote forecast. '
		'Use this when exact workbook formulas should compute the result instead of the LLM.',
		param_model=FormulaReadbackRequest,
	)
	async def verify_workpaper_formula_readback(params: FormulaReadbackRequest) -> ActionResult:
		"""Write an input cell, recalculate formulas, and return Bilig's structured proof."""

		try:
			proof = await asyncio.to_thread(run_bilig_formula_readback, params)
		except Exception as exc:
			return ActionResult(error=f'Bilig WorkPaper formula readback failed: {exc}')

		summary = (
			f'Bilig verified {proof.edited_cell}: expected ARR changed from '
			f'{proof.before.expected_arr} to {proof.after.expected_arr}; '
			f'restored readback matched: {proof.checks.restored_matches_after}.'
		)
		return ActionResult(
			extracted_content=proof.model_dump_json(by_alias=True, indent=2),
			long_term_memory=summary,
		)

	return tools


def _quote_input_page(conversion_rate: float) -> str:
	html = f"""<!doctype html>
<html lang="en">
	<head>
		<meta charset="utf-8" />
		<title>Bilig quote inputs</title>
	</head>
	<body>
		<h1>Quote forecast inputs</h1>
		<dl>
			<dt>Pipeline accounts</dt>
			<dd>20</dd>
			<dt>Conversion rate</dt>
			<dd>{conversion_rate}</dd>
			<dt>ARR per customer</dt>
			<dd>12000</dd>
		</dl>
	</body>
</html>"""
	return 'data:text/html,' + urllib.parse.quote(html)


async def run_agent(conversion_rate: float) -> None:
	"""Run the full Browser Use agent with the Bilig WorkPaper custom tool."""

	load_dotenv()
	if not os.getenv('BROWSER_USE_API_KEY'):
		raise RuntimeError('Set BROWSER_USE_API_KEY or run this file with --smoke for the no-key proof.')

	task = (
		f'Open this quote input page: {_quote_input_page(conversion_rate)}. '
		'Read the conversion rate from the page, then call verify_workpaper_formula_readback with that rate. '
		'Report the edited cell, expected ARR after recalculation, target gap, and whether Bilig verified persistence.'
	)
	agent = Agent(task=task, llm=ChatBrowserUse(), tools=create_bilig_workpaper_tools())
	await agent.run()


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description='Run the Browser Use + Bilig WorkPaper integration example.')
	parser.add_argument('--smoke', action='store_true', help='Run the Bilig tool path without an LLM or browser session.')
	parser.add_argument('--conversion-rate', type=float, default=0.4, help='Conversion rate to write into Inputs!B3.')
	return parser.parse_args()


def main() -> None:
	args = parse_args()
	request = FormulaReadbackRequest(conversion_rate=args.conversion_rate)

	if args.smoke:
		proof = run_bilig_formula_readback(request)
		print(proof.model_dump_json(by_alias=True, indent=2))
		return

	asyncio.run(run_agent(conversion_rate=args.conversion_rate))


if __name__ == '__main__':
	main()
