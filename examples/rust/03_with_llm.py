"""
Pass an `llm=` object — same shape as the classic `browser_use.Agent`.

The `llm` carries provider (inferred from class), model (`.model`), and
credentials (`.api_key`). The Agent reads them off and forwards
`run-<provider> --model <name>` to the Rust core, with the api_key routed
to the provider's conventional env variable (`OPENAI_API_KEY`,
`ANTHROPIC_API_KEY`, ...).

Run:
    python examples/rust/03_with_llm.py
"""

from __future__ import annotations

import asyncio

from browser_use.llm import ChatOpenAI
from browser_use.rust import Agent


async def main() -> None:
	llm = ChatOpenAI(model='gpt-5')  # picks up OPENAI_API_KEY from env if not given
	agent = Agent(
		task='visit https://news.ycombinator.com and list the top 3 story titles',
		llm=llm,
		show_events=True,
	)
	result = await agent.run()
	print(f'session_id:    {result.session_id}')
	print(f'status:        {result.status}')
	print(f'final_summary:\n{result.final_summary}')


if __name__ == '__main__':
	asyncio.run(main())
