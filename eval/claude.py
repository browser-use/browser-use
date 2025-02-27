from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic

from browser_use import Agent

load_dotenv()


async def run_agent(task: str, max_steps: int = 38):
	llm = ChatAnthropic(
		model_name='claude-3-5-sonnet-20240620',
		temperature=0.0,
		timeout=100,
		stop=None,
	)
	agent = Agent(task=task, llm=llm)
	result = await agent.run(max_steps=max_steps)
	return result
