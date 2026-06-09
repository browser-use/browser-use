import asyncio
import os

from dotenv import load_dotenv

from browser_use import Agent, Browser, ChatOpenAI, Tools

load_dotenv()


async def main():
	browser = Browser(cdp_url='http://localhost:9222')

	llm = ChatOpenAI(
		model=os.getenv('BROWSER_USE_LLM_MODEL', 'gpt-5.4'),
		api_key=os.getenv('OPENAI_API_KEY'),
		base_url=os.getenv('OPENAI_BASE_URL') or None,
	)

	tools = Tools()

	task = """
    Design me a mid-range water-cooled ITX computer
    Keep the total budget under $2000

    Go to https://pcpartpicker.com/
    Make sure the build is complete and has no incompatibilities.
    Provide the full list of parts with prices and a link to the completed build.
    """

	agent = Agent(
		task=task,
		browser=browser,
		tools=tools,
		llm=llm,
		use_thinking=False,
		use_vision=False,
		max_actions_per_step=2,
		max_failures=8,
		llm_timeout=180,
		step_timeout=240,
	)

	history = await agent.run(max_steps=100000)
	return history


if __name__ == '__main__':
	history = asyncio.run(main())
	final_result = history.final_result()
	print(final_result)
