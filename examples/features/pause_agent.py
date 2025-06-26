import asyncio
import os
import sys
import threading

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent
from browser_use.llm import ChatOpenAI


class AgentController:
	def __init__(self):
		llm = ChatOpenAI(model='gpt-4o')
		self.agent = Agent(
			task='open in one action https://www.google.com, https://www.wikipedia.org, https://www.youtube.com, https://www.github.com, https://amazon.com',
			llm=llm,
		)
		self.running = False

	async def run_agent(self):
		"""Run the agent"""
		self.running = True
		await self.agent.run()

	def start(self):
		"""Start the agent in a separate thread"""
		loop = asyncio.new_event_loop()
		asyncio.set_event_loop(loop)
		loop.run_until_complete(self.run_agent())

	def pause(self):
		"""Pause the agent"""
		self.agent.pause()

	def resume(self):
		"""Resume the agent"""
		self.agent.resume()

	def stop(self):
		"""Stop the agent"""
		self.agent.stop()
		self.running = False


def print_menu():
	print('\nAgent Control Menu:')
	print('1. Start')
	print('2. Pause')
	print('3. Resume')
	print('4. Stop')
	print('5. Exit')


async def main():
	controller = AgentController()
	agent_thread = None

	while True:
		print_menu()
		try:
			choice = input('Enter your choice (1-5): ')
		except KeyboardInterrupt:
			choice = '5'

		if choice == '1' and not agent_thread:
			print('Starting agent...')
			agent_thread = threading.Thread(target=controller.start)
			agent_thread.start()

		elif choice == '2':
			print('Pausing agent...')
			controller.pause()

		elif choice == '3':
			print('Resuming agent...')
			controller.resume()

		elif choice == '4':
			print('Stopping agent...')
			controller.stop()
			if agent_thread:
				agent_thread.join()
				agent_thread = None

		elif choice == '5':
			print('Exiting...')
			if controller.running:
				controller.stop()
				if agent_thread:
					agent_thread.join()
			break

		await asyncio.sleep(0.1)  # Small delay to prevent CPU spinning


if __name__ == '__main__':
	asyncio.run(main())
