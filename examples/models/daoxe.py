"""
Use DaoXE as an OpenAI-compatible LLM gateway with browser-use.

@dev Set DAOXE_API_KEY in your environment.
     Copy an exact model ID from your DaoXE account catalog (GET /v1/models).
     DaoXE is a multi-model multi-protocol gateway (OpenAI Chat Completions /
     Responses + Anthropic Messages for other clients). Not available in mainland China.
     Community example from a DaoXE maintainer: https://github.com/seven7763/DaoXE-AI
"""

import asyncio
import os

from dotenv import load_dotenv

from browser_use import Agent, ChatOpenAI

load_dotenv()

api_key = os.getenv('DAOXE_API_KEY', '')
if not api_key:
	raise ValueError('DAOXE_API_KEY is not set')

# Prefer a live model ID from your DaoXE account; do not hardcode third-party names.
model_id = os.getenv('DAOXE_MODEL_ID', 'YOUR_DAOXE_MODEL_ID')


async def run_search():
	agent = Agent(
		task='Find the number of stars of the browser-use repo on GitHub',
		llm=ChatOpenAI(
			base_url='https://daoxe.com/v1',
			model=model_id,
			api_key=api_key,
		),
		use_vision=False,
	)
	await agent.run(max_steps=10)


if __name__ == '__main__':
	asyncio.run(run_search())
