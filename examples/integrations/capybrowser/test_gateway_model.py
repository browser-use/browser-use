"""No-network contract test for the optional gateway model path."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import patch

import httpx2 as httpx
from gateway_model import GatewayModel
from openai import AsyncOpenAI
from pydantic import BaseModel

from browser_use.llm.messages import SystemMessage, UserMessage


class Reply(BaseModel):
	answer: str


class GatewayModelTests(unittest.IsolatedAsyncioTestCase):
	async def test_model_config_inside_checkout_is_rejected(self):
		checkout = Path(__file__).resolve().parents[3]
		with tempfile.TemporaryDirectory(dir=checkout) as directory:
			config = Path(directory) / 'model.json'
			config.write_text(json.dumps({'base_url': 'https://model.invalid', 'model': 'test', 'api_key': 'key'}))
			config.chmod(0o600)
			with self.assertRaisesRegex(ValueError, 'outside'):
				model = GatewayModel(config, Path(directory) / 'usage.json')
				await model.close()

	async def test_relative_config_path_is_rejected(self):
		with tempfile.TemporaryDirectory() as directory:
			config = Path(directory) / 'model.json'
			config.write_text(json.dumps({'base_url': 'https://model.invalid/api/openai', 'model': 'test', 'api_key': 'key'}))
			config.chmod(0o600)
			previous = Path.cwd()
			try:
				os.chdir(directory)
				with self.assertRaisesRegex(ValueError, 'absolute'):
					model = GatewayModel(Path('model.json'), Path(directory) / 'usage.json')
					await model.close()
			finally:
				os.chdir(previous)

	async def test_redirect_does_not_replay_prompt_to_another_host(self):
		with tempfile.TemporaryDirectory() as directory:
			config = Path(directory) / 'model.json'
			config.write_text(
				json.dumps({'base_url': 'https://model.invalid/api/openai', 'model': 'test', 'api_key': 'test-key'})
			)
			config.chmod(0o600)
			seen = []

			def respond(request):
				seen.append(str(request.url))
				if request.url.host == 'model.invalid':
					return httpx.Response(307, headers={'Location': 'https://other.invalid/capture'})
				return httpx.Response(200, json={'unexpected': 'redirect followed'})

			def mock_client(**kwargs):
				return httpx.AsyncClient(
					transport=httpx.MockTransport(respond), follow_redirects=kwargs.get('follow_redirects', True)
				)

			with patch('gateway_model.DefaultAsyncHttpxClient', side_effect=mock_client):
				model = GatewayModel(config, Path(directory) / 'usage.json')
				try:
					with self.assertRaises(Exception):
						await model.ainvoke([SystemMessage(content='Private schema'), UserMessage(content='Private page')], Reply)
				finally:
					await model.close()
			self.assertEqual(seen, ['https://model.invalid/api/openai/chat/completions'])

	async def test_structured_and_plain_calls_track_usage_without_prompts(self):
		with tempfile.TemporaryDirectory() as directory:
			config = Path(directory) / 'model.json'
			config.write_text(
				json.dumps({'base_url': 'https://model.invalid/api/openai', 'model': 'test-model', 'api_key': 'test-key'})
			)
			config.chmod(0o600)
			usage = Path(directory) / 'usage.json'
			model = GatewayModel(config, usage, max_calls=2)
			await model.close()
			seen = []

			def respond(request):
				body = json.loads(request.content)
				seen.append(body)
				self.assertEqual(str(request.url), 'https://model.invalid/api/openai/chat/completions')
				self.assertEqual(body['max_tokens'], 4096)
				self.assertEqual([message['role'] for message in body['messages']], ['system', 'user'])
				content = '{"answer":"ok"}' if len(seen) == 1 else 'plain extraction'
				return httpx.Response(
					200,
					json={
						'id': f'completion-{len(seen)}',
						'object': 'chat.completion',
						'created': 1,
						'model': 'test-model',
						'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': content}}],
						'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15},
					},
				)

			async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
				model._client = AsyncOpenAI(
					api_key='test-key', base_url='https://model.invalid/api/openai', max_retries=0, http_client=client
				)
				structured = await model.ainvoke([SystemMessage(content='Return JSON.'), UserMessage(content='Go.')], Reply)
				self.assertEqual(cast(Reply, structured.completion).answer, 'ok')
				self.assertEqual(seen[0]['response_format'], {'type': 'json_object'})
				self.assertTrue(seen[0]['messages'][0]['content'].startswith('Return JSON.\n<json_schema>'))
				plain = await model.ainvoke([SystemMessage(content='Extract.'), UserMessage(content='Go.')])
				self.assertEqual(plain.completion, 'plain extraction')
				self.assertNotIn('response_format', seen[1])
				with self.assertRaisesRegex(RuntimeError, 'budget'):
					await model.ainvoke([UserMessage(content='Again.')], Reply)
				await model.close()
			record = json.loads(usage.read_text())
			self.assertEqual(record['calls_started'], 2)
			self.assertEqual([event['total_tokens'] for event in record['events']], [15, 15])
			self.assertNotIn('request_messages', usage.read_text())
			self.assertNotIn('plain extraction', usage.read_text())
