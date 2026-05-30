"""
Every `browser_use.rust.Agent` constructor option, in one file.

The Agent surface is intentionally minimal — exactly the kwargs you'd
expect from the classic `browser_use.Agent`:

    Agent(
        task,
        llm=ChatXxx(api_key=..., model=...),   # owns provider/model/api_key
        browser=Browser(cdp_url=..., headless=...),
        timeout=...,
        on_event=...,
        output_model=...,
        state_dir=...,
        extra_args=[...],
    )

Run:
    python examples/rust/00_all_options.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from pydantic import BaseModel, Field

from browser_use import BrowserSession
from browser_use.llm import ChatOpenAI
from browser_use.rust import Agent, SessionResult, ToolCall


# Pydantic output model — the final agent message gets parsed into it.
class TopStory(BaseModel):
	title: str
	url: str = Field(description='Absolute URL to the story')
	comments: int = 0


class TopStories(BaseModel):
	items: list[TopStory]


async def on_event(event):
	if isinstance(event, ToolCall):
		print(f'  → tool {event.tool_name}')
	elif isinstance(event, SessionResult):
		print(f'  → result ({len(event.text)} chars)')


async def main() -> None:
	# 1. The LLM. Owns model, provider (from class), api_key.
	#    ChatOpenAI / ChatAzureOpenAI                       → run-openai
	#    ChatAnthropic                                       → run-anthropic
	#    ChatGoogle / ChatGemini / ChatOpenRouter / ChatGroq → run-openrouter
	#    ChatDeepSeek                                        → run-deepseek
	# The api_key is read off llm.api_key and routed to the right env var
	# for the chosen provider (OPENAI_API_KEY here). If you omit api_key=,
	# the chat class picks it up from your environment automatically.
	llm = ChatOpenAI(
		# api_key='sk-...',  # uncomment to scope a key to this Agent only
		model='gpt-5',
	)

	# 2. The browser. Owns cdp_url, profile, headless, name.
	#    The wrapper reads .name → `--browser <name>` and .cdp_url → env var
	#    BUT_BROWSER_CDP_URL (the matching Rust-side `--cdp-url` flag is the
	#    follow-up patch).
	browser = BrowserSession()

	# 3. The Agent itself — every user-facing knob.
	agent = Agent(
		task='Open https://news.ycombinator.com and return JSON of the top 5 stories.',
		llm=llm,
		browser=browser,
		timeout=180.0,                # cancel ladder fires on expiry
		on_event=on_event,            # typed event callback (sync or async)
		output_model=TopStories,      # parse the final summary into this pydantic class
		state_dir=Path.home() / '.browser-use-terminal',  # override Rust SQLite dir
		extra_args=[],                # rare CLI escape hatch
	)

	# Inspect what the wrapper resolved without actually running.
	print('provider:    ', agent.provider)
	print('model:       ', agent._model)
	print('api_key_env: ', agent.provider.api_key_env)
	print('browser_name:', getattr(browser, 'name', None))
	print('state_dir:   ', agent.state_dir)
	print('timeout:     ', agent.timeout, 's')
	print('output_model:', agent.output_model.__name__ if agent.output_model else None)
	print('binary:      ', Agent.headless_binary_path())
	print()
	print('Resolved CLI argv (what would be spawned):')
	for token in (
		[str(Agent.headless_binary_path()), agent.provider.subcommand, '<task>']
		+ (['--model', agent._model] if agent._model else [])
		+ agent._cli_flags_excluding_task()
	):
		print('  ', token)
	print()
	print('Env overrides passed to the subprocess:')
	for k, v in agent._env_overrides().items():
		print(f'   {k}={v[:8]}…' if 'KEY' in k or 'AUTH' in k else f'   {k}={v}')

	# Now actually run the agent against a real LLM + browser.
	print()
	print('running agent…')
	result = await agent.run()
	print()
	print('status:        ', result.status)
	print('session_id:    ', result.session_id)
	print('duration:      ', f'{result.duration_seconds:.1f}s')
	print('steps:         ', len(result.steps))
	print('events:        ', len(result.events))
	print('final_summary:\n' + (result.final_summary or '(none)'))
	if result.final_output is not None:
		print()
		print('typed output:', result.final_output.model_dump_json(indent=2))


if __name__ == '__main__':
	asyncio.run(main())
