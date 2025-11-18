"""
Quick test to see what the NVIDIA Direct API actually returns.
Uses httpx directly to avoid OpenAI client magic.
"""

import asyncio
import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

# Load environment variables
env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)


async def test_direct_http():
	"""Test NVIDIA Direct API with raw HTTP to see what happens."""
	api_key = os.getenv('NVIDIA_DIRECT_API_KEY')
	if not api_key:
		print('❌ NVIDIA_DIRECT_API_KEY not found in .env file')
		return

	url = 'https://integrate.api.nvidia.com/v1/chat/completions'
	headers = {
		'Authorization': f'Bearer {api_key}',
		'Content-Type': 'application/json',
	}

	# Simple test payload
	payload = {
		'model': 'nvidia/llama-3.1-nemotron-70b-instruct',
		'messages': [
			{
				'role': 'user',
				'content': 'Say hello in JSON format like {"message": "hello"}',
			}
		],
		'temperature': 0.7,
		'max_tokens': 100,
	}

	print('Testing NVIDIA Direct API with raw HTTP...')
	print(f'URL: {url}')
	print(f'Payload: {json.dumps(payload, indent=2)}\n')

	async with httpx.AsyncClient(timeout=30.0) as client:
		try:
			response = await client.post(url, headers=headers, json=payload)
			print(f'Status: {response.status_code}')
			print(f'Response: {response.text}\n')

			if response.status_code == 200:
				data = response.json()
				print(f'✅ Success!')
				print(f'Content: {data["choices"][0]["message"]["content"]}')
			else:
				print(f'❌ Error: {response.status_code}')

		except Exception as e:
			print(f'❌ Exception: {e}')


if __name__ == '__main__':
	asyncio.run(test_direct_http())
