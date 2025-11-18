"""
Test ChatNvidiaDirect with browser-use Agent.

Setup:
1. API key should be in .env file in this directory:
   NVIDIA_DIRECT_API_KEY=your-nvidia-api-key-here

   Get your API key from: https://build.nvidia.com/explore/discover

2. Run: uv run python browser_use/llm/nvidia/test_nvidia_direct.py
"""

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

from browser_use import Agent
from browser_use.llm.nvidia.chat_direct import ChatNvidiaDirect

# Load environment variables from .env in this directory
env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)


async def test_simple_task():
	"""Test ChatNvidiaDirect with a simple browser task."""
	api_key = os.getenv('NVIDIA_DIRECT_API_KEY')
	if not api_key:
		raise ValueError('NVIDIA_DIRECT_API_KEY not found in .env file')

	print('Testing NVIDIA Direct API with browser automation...')
	print(f'Using API endpoint: https://integrate.api.nvidia.com/v1')

	# Test with Nemotron 70B
	llm = ChatNvidiaDirect(
		api_key=api_key,
		model='nvidia/llama-3.1-nemotron-70b-instruct',
		temperature=0.7,
		max_tokens=1024,
	)

	agent = Agent(
		task='please find how many stars the browser-use repository has on github.',
		llm=llm,
	)

	result = await agent.run()
	print('\n' + '=' * 80)
	print('Task Result:')
	print('=' * 80)
	print(result)
	print('=' * 80)


async def test_vision_model():
	"""Test with a vision model to verify multimodal support."""
	api_key = os.getenv('NVIDIA_DIRECT_API_KEY')
	if not api_key:
		raise ValueError('NVIDIA_DIRECT_API_KEY not found in .env file')

	print('\n\nTesting NVIDIA Direct API with vision model...')

	# Test with a vision-capable model
	# Note: Check https://build.nvidia.com/explore/discover for available vision models
	llm = ChatNvidiaDirect(
		api_key=api_key,
		model='microsoft/phi-3-vision-128k-instruct',  # Example vision model
		temperature=0.5,
		max_tokens=512,
	)

	agent = Agent(
		task='Go to hacker news and tell me what the top post is about',
		llm=llm,
	)

	result = await agent.run(max_steps=5)
	print('\n' + '=' * 80)
	print('Vision Model Test Result:')
	print('=' * 80)
	print(result)
	print('=' * 80)


async def list_available_models():
	"""List available models on NVIDIA Direct API."""
	api_key = os.getenv('NVIDIA_DIRECT_API_KEY')
	if not api_key:
		raise ValueError('NVIDIA_DIRECT_API_KEY not found in .env file')

	print('Fetching available NVIDIA models...\n')

	from openai import AsyncOpenAI

	client = AsyncOpenAI(
		base_url='https://integrate.api.nvidia.com/v1',
		api_key=api_key,
	)

	try:
		models = await client.models.list()
		print('Available models:')
		for model in models.data:
			print(f'  - {model.id}')
	except Exception as e:
		print(f'Error listing models: {e}')


if __name__ == '__main__':
	print('Testing ChatNvidiaDirect integration with browser-use Agent...\n')

	# Uncomment to list available models first
	# asyncio.run(list_available_models())

	# Run simple task test
	asyncio.run(test_simple_task())

	# Uncomment to test vision capabilities:
	# asyncio.run(test_vision_model())

	print('\n✓ All tests completed!')
