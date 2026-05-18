"""
Example: browser-use agent with emem geospatial custom tool.

The agent browses the web normally, but when a task needs factual geospatial
evidence about a real-world location, it calls emem instead of guessing from
web pages.

emem is a public HTTP/MCP server for signed geospatial facts.
- https://emem.dev
- https://github.com/Vortx-AI/emem
- MCP endpoint: https://emem.dev/mcp
"""

import asyncio
import os
import sys

import httpx

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from pydantic import BaseModel

from browser_use import ChatOpenAI
from browser_use.agent.service import Agent
from browser_use.tools.service import Tools

tools = Tools()

EMEM_BASE_URL = 'https://emem.dev'


class EmemQuery(BaseModel):
	lat: float
	lon: float
	query: str


@tools.action(
	'Get geospatial facts from emem for a given location. Use this when you need real-world evidence about a place (elevation, flood risk, land cover, etc).',
	param_model=EmemQuery,
)
def get_geospatial_facts(params: EmemQuery):
	"""Call emem to get signed geospatial facts for a lat/lon."""
	response = httpx.post(
		f'{EMEM_BASE_URL}/ask',
		json={
			'lat': params.lat,
			'lon': params.lon,
			'query': params.query,
		},
		timeout=30,
	)
	response.raise_for_status()
	return response.json()


async def main():
	task = (
		'Research Helsinki Airport, Finland. '
		'Find its coordinates from the web, then use the emem geospatial tool '
		'to get signed facts about whether the location is low-lying or flood-prone. '
		'Summarize what you find.'
	)

	model = ChatOpenAI(model='gpt-4.1-mini')
	agent = Agent(task=task, llm=model, tools=tools)

	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
