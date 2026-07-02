import ast
import asyncio
import base64
import json
from unittest.mock import patch

import httpx
import pytest

from browser_use import Browser
from browser_use.sandbox import SandboxError, sandbox


class DummyStream:
	status_code = 200

	def raise_for_status(self):
		pass

	async def __aenter__(self):
		return self

	async def __aexit__(self, *exc):
		return False

	async def aiter_lines(self):
		event = {
			'type': 'result',
			'data': {'execution_response': {'success': True, 'result': 'ok', 'error': None}},
		}
		yield f'data: {json.dumps(event)}'


def test_sandbox_payload_uses_json_not_cloudpickle():
	captured = {}

	async def run():
		@sandbox(BROWSER_USE_API_KEY='test-key', server_url='https://sandbox.invalid', quiet=True)
		async def task(browser: Browser, value: str):
			return value

		await task(value='safe')

	def fake_stream(self, method, url, json, headers):
		captured.update(json)
		return DummyStream()

	with patch.object(httpx.AsyncClient, 'stream', fake_stream):
		asyncio.run(run())

	code = base64.b64decode(captured['code']).decode()
	assert 'cloudpickle' not in code
	assert 'pickle.loads' not in code
	assert 'json.loads' in code

	parsed = ast.parse(code)
	assert not any(
		isinstance(node, ast.Call)
		and isinstance(node.func, ast.Attribute)
		and node.func.attr == 'loads'
		and isinstance(node.func.value, ast.Name)
		and node.func.value.id in {'pickle', 'cloudpickle'}
		for node in ast.walk(parsed)
	)


def test_sandbox_rejects_non_json_serializable_params():
	class CustomParam:
		pass

	async def run():
		@sandbox(BROWSER_USE_API_KEY='test-key', server_url='https://sandbox.invalid', quiet=True)
		async def task(browser: Browser, value):
			return value.missing_attribute

		await task(value=CustomParam())

	with pytest.raises(SandboxError, match='unsupported type CustomParam'):
		asyncio.run(run())
