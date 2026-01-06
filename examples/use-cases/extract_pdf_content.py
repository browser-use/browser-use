#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["browser-use", "mistralai"]
# ///

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

import asyncio
import logging

from browser_use import Agent, ChatOpenAI

logger = logging.getLogger(__name__)


async def main():
	agent = Agent(
		task="""
        Objective: Navigate to the following UR, what is on page 3?

        URL: https://docs.house.gov/meetings/GO/GO00/20220929/115171/HHRG-117-GO00-20220929-SD010.pdf
        """,
		llm=ChatOpenAI(model='gpt-4.1-mini'),
	)
	result = await agent.run()
	logger.info(result)


if __name__ == '__main__':
	asyncio.run(main())
