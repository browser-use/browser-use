"""
Generate CSV files with automatic normalization.

The agent's file system automatically normalizes CSV output using Python's csv module,
so fields containing commas, quotes, or empty values are properly handled per RFC 4180.
This means the agent doesn't need to worry about manual quoting — it's fixed at the
infrastructure level.

Common LLM mistakes that are auto-corrected:
- Unquoted fields containing commas (e.g. "San Francisco, CA" without quotes)
- Unescaped double quotes inside fields
- Inconsistent empty field handling
- Stray blank lines
"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent, ChatBrowserUse


async def main():
	agent = Agent(
		task=(
			'Go to https://en.wikipedia.org/wiki/List_of_largest_cities and extract the top 10 cities. '
			'Create a CSV file called "top_cities.csv" with columns: rank, city name, country, population. '
			'Make sure to include all cities even if some data is missing — leave those cells empty.'
		),
		llm=ChatBrowserUse(model='bu-2-0'),
	)

	history = await agent.run()

	# Check the generated CSV file
	if agent.file_system:
		csv_file = agent.file_system.get_file('top_cities.csv')
		if csv_file:
			print('\nGenerated CSV content:')
			print(csv_file.content)
			print(f'\nFile saved to: {agent.file_system.get_dir() / csv_file.full_name}')


if __name__ == '__main__':
	asyncio.run(main())
