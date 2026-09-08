"""
Example of using Avian with browser-use.

Avian (https://avian.io) provides cost-effective LLM inference through an
OpenAI-compatible API. It offers access to models like DeepSeek-V3.2,
Kimi-K2.5, GLM-5, and MiniMax-M2.5.

To use this example:
1. Get an API key from https://avian.io
2. Set your AVIAN_API_KEY environment variable
3. Run this script

Available models:
- deepseek/deepseek-v3.2  (164K input / 65K output context)
- moonshotai/kimi-k2.5    (131K input / 8K output context)
- z-ai/glm-5              (131K input / 16K output context)
- minimax/minimax-m2.5    (1M input / 1M output context)
"""

import asyncio
import os

from dotenv import load_dotenv

from browser_use import Agent
from browser_use.llm import ChatAvian

load_dotenv()

api_key = os.getenv('AVIAN_API_KEY')
if not api_key:
	print('Please set AVIAN_API_KEY environment variable.')
	print('Get your API key from https://avian.io')
	exit(1)


async def main():
	# Option 1: Use ChatAvian directly (recommended)
	llm = ChatAvian(
		model='deepseek/deepseek-v3.2',
		api_key=api_key,
	)

	# Option 2: Use pre-configured model instances
	# from browser_use import llm as llm_models
	# llm = llm_models.avian_deepseek_v3_2
	# llm = llm_models.avian_kimi_k2_5
	# llm = llm_models.avian_glm_5
	# llm = llm_models.avian_minimax_m2_5

	agent = Agent(
		task='Find the number of stars of the browser-use repo on GitHub',
		llm=llm,
		use_vision=False,
	)

	await agent.run(max_steps=10)


asyncio.run(main())
