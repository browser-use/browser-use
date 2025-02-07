import asyncio

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from browser_use import Agent
from browser_use.agent.views import ActionResult
from browser_use.controller.service import Controller

load_dotenv()

# Initialize the model
llm = ChatOpenAI(
	model='gpt-4o',
	temperature=0.0,
)
controller = Controller()


task = 'Find the founders of browser-use and draft them a short personalized message'

agent = Agent(task=task, llm=llm, controller=controller)


async def main():
	await agent.run()

	# new_task = input('Type in a new task: ')
	new_task = 'Find an image of the founders'

	agent.add_new_task(new_task)

	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
