import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from langchain_openai import ChatOpenAI

from browser_use import Agent, Browser


# Video: https://preview.screen.studio/share/8Elaq9sm
async def main():
	# Persist the browser state across agents

	browser = Browser()
	async with await browser.new_context() as context:
		model = ChatOpenAI(model='gpt-4o')
		current_agent = None

		async def get_input():
			return await asyncio.get_event_loop().run_in_executor(
				None, lambda: input('Enter task (p: pause current agent, r: resume, b: break): ')
			)

		while True:
			task = await get_input()

			if task.lower() == 'p':
				# Pause the current agent if one exists
				if current_agent:
					current_agent.pause()
				continue
			elif task.lower() == 'r':
				# Resume the current agent if one exists
				if current_agent:
					current_agent.resume()
				continue
			elif task.lower() == 'b':
				# Break the current agent's execution if one exists
				if current_agent:
					current_agent.stop()
					current_agent = None
				continue

			# If there's a current agent running, pause it before starting new one
			if current_agent:
				current_agent.pause()

			# Create and run new agent with the task
			current_agent = Agent(
				task=task,
				llm=model,
				browser_context=context,
			)

			# Run the agent asynchronously without blocking
			asyncio.create_task(current_agent.run())


asyncio.run(main())

# Now aad the cheapest to the cart
