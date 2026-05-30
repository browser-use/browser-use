"""
browser_use.rust — Rust-backed agent (browser-use/terminal `but` core).

Public API mirrors the classic `browser_use.Agent` shape:

    from browser_use.llm import ChatOpenAI
    from browser_use.rust import Agent

    agent = Agent(
        task="open https://example.com and tell me the title",
        llm=ChatOpenAI(api_key="sk-...", model="gpt-5"),  # owns provider/model/key
    )
    result = await agent.run()
    print(result.final_summary)

Browser config (CDP url, profile, headless flag, browser name) flows in via
`browser=` from a `BrowserSession`. Everything else is a constructor kwarg.

`from browser_use import Agent` is unchanged.
"""

from browser_use.rust import events
from browser_use.rust.events import (
	AnyAgentEvent,
	ModelTextDelta,
	SessionFailure,
	SessionResult,
	SessionStatus,
	ToolCall,
	ToolResult,
	parse_event,
)
from browser_use.rust.runner import (
	BUT_BINARY_ENV,
	ButNotInstalledError,
	find_browser_use_terminal_binary,
	find_but_binary,
	launch_terminal_ui,
)
from browser_use.rust.service import Agent
from browser_use.rust.views import AgentRunResult, Provider, StepRecord

__all__ = [
	'Agent',
	'AgentRunResult',
	'AnyAgentEvent',
	'BUT_BINARY_ENV',
	'ButNotInstalledError',
	'ModelTextDelta',
	'Provider',
	'SessionFailure',
	'SessionResult',
	'SessionStatus',
	'StepRecord',
	'ToolCall',
	'ToolResult',
	'events',
	'find_browser_use_terminal_binary',
	'find_but_binary',
	'launch_terminal_ui',
	'parse_event',
]
