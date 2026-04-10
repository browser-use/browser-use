"""AG2 Multi-Agent Web Research with browser-use.

Coordinates three AG2 agents to perform web research:
- Planner: decomposes a research question into browsing tasks
- Browser Agent: executes tasks via browser-use's autonomous browser
- Synthesizer: combines results into a final report

Usage:
    export OPENAI_API_KEY=sk-...
    python main.py
"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from dotenv import load_dotenv

load_dotenv()

from autogen import AssistantAgent, GroupChat, GroupChatManager, LLMConfig, UserProxyAgent
from langchain_openai import ChatOpenAI

from browser_use import Agent as BrowserUseAgent
from browser_use import Browser, BrowserProfile

# --- Configuration ---

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
if not OPENAI_API_KEY:
	raise ValueError('OPENAI_API_KEY environment variable is required')

HEADLESS = os.getenv('BROWSER_USE_HEADLESS', 'true').lower() != 'false'
MODEL = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')

# AG2 LLM config (for agent reasoning)
llm_config = LLMConfig({'model': MODEL, 'api_key': OPENAI_API_KEY, 'api_type': 'openai'})

# browser-use LLM (LangChain ChatOpenAI, separate from AG2's config)
browser_llm = ChatOpenAI(model=MODEL, api_key=OPENAI_API_KEY)  # type: ignore[arg-type]


# --- Termination ---


def is_termination(msg):
	content = msg.get('content', '') or ''
	return 'TERMINATE' in content


# --- AG2 Agents ---

user_proxy = UserProxyAgent(
	name='user_proxy',
	human_input_mode='NEVER',
	max_consecutive_auto_reply=10,
	code_execution_config=False,
	is_termination_msg=is_termination,
)

planner = AssistantAgent(
	name='planner',
	system_message=(
		'You are a research planner. Given a research question, decompose it into '
		'2-4 specific web browsing tasks. Each task should be a clear, self-contained '
		'instruction that a browser agent can execute (e.g., "Go to example.com and find X").\n'
		'Output tasks as a numbered list. Do NOT execute tasks yourself — hand them '
		'to the browser_agent.'
	),
	llm_config=llm_config,
)

browser_agent = AssistantAgent(
	name='browser_agent',
	system_message=(
		'You execute web browsing tasks using the browse_web tool. '
		'For each task given by the planner, call browse_web with a clear task description. '
		'Report the results back to the group. Call browse_web once per task — do not '
		'combine multiple tasks into one call.'
	),
	llm_config=llm_config,
)

synthesizer = AssistantAgent(
	name='synthesizer',
	system_message=(
		'You synthesize research results into a clear, well-structured report. '
		'Wait until the browser_agent has completed all browsing tasks before writing '
		'your report. Once you have enough information, write a final summary.\n'
		'When your report is complete, end your message with TERMINATE.'
	),
	llm_config=llm_config,
)


# --- browser-use Tool ---


@user_proxy.register_for_execution()
@browser_agent.register_for_llm(
	description='Browse the web to complete a task. Pass a natural-language task description.',
)
def browse_web(task: str) -> str:
	"""Use browser-use to autonomously browse the web and complete the given task."""

	async def _run() -> str:
		browser = Browser(browser_profile=BrowserProfile(headless=HEADLESS))
		try:
			agent = BrowserUseAgent(task=task, llm=browser_llm, browser=browser)  # type: ignore[arg-type]
			result = await agent.run()
			return result.final_result() or 'No results found.'
		except Exception as e:
			return f'Browsing error: {e}'
		finally:
			await browser.kill()

	return asyncio.run(_run())


# --- GroupChat ---

group_chat = GroupChat(
	agents=[user_proxy, planner, browser_agent, synthesizer],
	messages=[],
	max_round=15,
)

manager = GroupChatManager(
	groupchat=group_chat,
	llm_config=llm_config,
	is_termination_msg=is_termination,
)


# --- Main ---


def main():
	task = (
		'Compare the pricing and key features of the top 3 cloud GPU providers '
		'for AI model training in 2026. Include per-hour GPU costs where available.'
	)
	print(f'Starting research: {task}\n')
	user_proxy.run(manager, message=task).process()
	print('\n--- Conversation complete ---')


if __name__ == '__main__':
	main()
