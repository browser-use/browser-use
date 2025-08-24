import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent, ChatOpenAI, Controller
from browser_use.browser import BrowserProfile, BrowserSession

# Initialize the model
llm = ChatOpenAI(
	model='gpt-4.1',
	temperature=0.0,
)

# Use default browser session for simplicity
browser_session = BrowserSession()

controller = Controller()

# Task that will use wait_for_user_input action to ask for user guidance
task = '''Search for information about Python web frameworks. 
After finding some initial results, use wait_for_user_input to ask me which specific framework I'd like to learn more about, 
then search for detailed information about that framework.'''

agent = Agent(task=task, llm=llm, controller=controller, browser_session=browser_session)


async def main():
	print("🚀 Starting agent with initial task...")
	print(f"Task: {task}")
	print()
	
	# Start the agent - it will run until it hits wait_for_user_input
	result = await agent.run()
	
	# Check if agent is waiting for user input
	if agent.is_waiting_for_user_input():
		print("\n" + "="*60)
		print("🔴 AGENT IS WAITING FOR USER INPUT")
		print("="*60)
		
		# Get user input
		user_response = input("\n👤 Your response: ")
		print()
		
		# Continue with user's response
		print(f"🟢 Continuing with your input: {user_response}")
		agent.add_new_task(f"User responded: {user_response}. Continue with the original task.")
		
		# Resume agent execution
		await agent.run()
	
	print("\n✅ Task completed!")


if __name__ == '__main__':
	asyncio.run(main())
