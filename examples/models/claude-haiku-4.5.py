"""
Simple script demonstrating Claude Haiku 4.5 for cost-efficient browser automation.

Claude Haiku 4.5 is the most cost-efficient model for browser automation:
- $1 per million input tokens, $5 per million output tokens
- 3x cheaper than Sonnet 4.5
- 4-5x faster responses
- Similar coding performance to Claude Sonnet 4

Ideal for:
- High-volume automation tasks
- Cost-sensitive production deployments
- Quick response time requirements

@dev Ensure we have a `ANTHROPIC_API_KEY` variable in our `.env` file.
"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from langchain_anthropic import ChatAnthropic

from browser_use import Agent

llm = ChatAnthropic(model_name='claude-haiku-4-5-20251001', temperature=0.0, timeout=30, stop=None)

agent = Agent(
	task='Go to amazon.com, search for laptop, sort by best rating, and give me the price of the first result',
	llm=llm,
)


async def main():
	await agent.run(max_steps=10)


asyncio.run(main())
