"""
Structured output: hand a pydantic model in via `output_model=`, and the
final agent message gets parsed into that type. Works whether the agent
returned plain JSON, fenced ```json``` blocks, or a JSON object embedded in
prose.

Run:
    python examples/terminal/06_output_model.py
"""

from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from browser_use.rust import Agent


class StoryList(BaseModel):
	stories: list[str] = Field(description='Top 3 story titles in order')


async def main() -> None:
	agent = Agent(
		task=(
			'Open https://news.ycombinator.com and respond with ONLY a JSON object of the form '
			'{"stories": ["title1", "title2", "title3"]}. No prose, no fences.'
		),
		output_model=StoryList,
	)
	result = await agent.run(interactive=False)
	print(f'[example] status:        {result.status}')
	print(f'[example] final_summary: {result.final_summary}')
	if isinstance(result.final_output, StoryList):
		print(f'[example] typed output:  {result.final_output.stories}')
	else:
		print('[example] (no structured output extracted)')


if __name__ == '__main__':
	asyncio.run(main())
