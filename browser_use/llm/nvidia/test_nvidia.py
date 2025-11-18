"""
Test ChatNvidia with browser-use Agent.

Setup:
1. API key should be in .env file in this directory:
   NVIDIA_API_KEY=your-key-here

2. Run: uv run python browser_use/llm/nvidia/test_nvidia.py
"""

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

from browser_use import Agent
from browser_use.llm.nvidia.chat import ChatNvidia

# Load environment variables from .env in this directory
env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)


async def test_simple_task():
	"""Test ChatNvidia with a simple browser task."""
	api_key = os.getenv('NVIDIA_API_KEY')
	if not api_key:
		raise ValueError('NVIDIA_API_KEY not found in .env file')

	print('Testing NVIDIA Nemotron 70B (Brev) with browser automation...')

	# Uses default Brev deployment: nvidia/llama-3.1-nemotron-70b-instruct
	llm = ChatNvidia(
		api_key=api_key,
		temperature=0.7,
		max_tokens=1024,
	)

	agent = Agent(
		task='Go to https://pcpartpicker.com/list/ and add a 2080ti to my list.',
		llm=llm,
        use_vision=False
	)

	result = await agent.run()
	print('\n' + '=' * 80)
	print('Task Result:')
	print('=' * 80)
	print(result.final_result())
	print('=' * 80)


async def test_with_max_steps():
	"""Test with limited steps using demo mode."""
	api_key = os.getenv('NVIDIA_API_KEY')
	if not api_key:
		raise ValueError('NVIDIA_API_KEY not found in .env file')

	print('\n\nTesting with max_steps and demo_mode...')

	llm = ChatNvidia(
		api_key=api_key,
		model='nvidia/nemotron-nano-12b-v2-vl',
		temperature=0.5,
	)

	agent = Agent(
		task='Go to pcpartpicker.com and add a 2080ti to my list',
		llm=llm,
	)

	result = await agent.run(max_steps=10)
	print('\n' + '=' * 80)
	print('Task Result with Limited Steps:')
	print('=' * 80)
	print(result)
	print('=' * 80)


async def test_default_model():
	"""Test using the default model (no model parameter)."""
	api_key = os.getenv('NVIDIA_API_KEY')
	if not api_key:
		raise ValueError('NVIDIA_API_KEY not found in .env file')

	print('\n\nTesting with default model...')

	# No model specified - uses default nvidia/nemotron-nano-12b-v2-vl
	llm = ChatNvidia(api_key=api_key)

	agent = Agent(
		task='Go to hacker news and tell me the title of the #1 post',
		llm=llm,
	)

	result = await agent.run()
	print('\n' + '=' * 80)
	print('Task Result (Default Model):')
	print('=' * 80)
	print(result)
	print('=' * 80)


if __name__ == '__main__':
	print('Testing ChatNvidia integration with browser-use Agent...\n')

	# Run simple task test
	asyncio.run(test_simple_task())

	# Uncomment to run additional tests:
	# asyncio.run(test_with_max_steps())
	# asyncio.run(test_default_model())

	print('\n✓ All tests completed!')
