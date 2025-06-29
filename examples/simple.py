import asyncio
import os
import sys

from browser_use.llm.openai.chat import ChatOpenAI

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()


from browser_use import Agent

# Initialize the model
llm = ChatOpenAI(
	model='gpt-4.1-mini',
)


task = 'Open 3 tabs with random wikipedia pages'
agent = Agent(task=task, llm=llm)


async def main():
	history = await agent.run()
	# token usage
	print(history.usage)


if __name__ == '__main__':
	asyncio.run(main())
