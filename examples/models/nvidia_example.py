"""
Example of using NVIDIA NIM with browser-use.

To use this example:
1. Set your NVIDIA_API_KEY environment variable
2. Run this script

ChatNvidia talks to the hosted NVIDIA API catalog at https://integrate.api.nvidia.com/v1
by default. Pass base_url to point it at a self-hosted NIM instead.

Some NVIDIA models you can use:
- nvidia/nemotron-3.5-super-vl-120b-a12b (default, accepts screenshots)
- nvidia/nemotron-3-super-120b-a12b (text only, use with use_vision=False)
- meta/llama-3.2-11b-vision-instruct (smaller, accepts screenshots)
"""

import asyncio
import os

from browser_use import Agent, ChatNvidia


async def main():
	# Set your API key (recommended to use environment variable)
	api_key = os.getenv('NVIDIA_API_KEY')
	if not api_key:
		raise ValueError('Please set NVIDIA_API_KEY environment variable')

	# Create the model instance
	model = ChatNvidia(
		model='nvidia/nemotron-3.5-super-vl-120b-a12b',  # or any other model ID
		api_key=api_key,
		temperature=0.2,
		max_tokens=4096,
		# base_url='http://localhost:8000/v1',  # self-hosted NIM
	)

	# Create and run the agent with a simple task
	task = 'Explain the concept of quantum entanglement in simple terms.'
	agent = Agent(task=task, llm=model)

	print(f'Running task with NVIDIA {model.name} (ID: {model.model}): {task}')
	history = await agent.run(max_steps=3)
	result = history.final_result()

	print(f'Result: {result}')


if __name__ == '__main__':
	asyncio.run(main())
