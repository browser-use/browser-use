import os
import sys
import asyncio

# Adjust Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from pydantic import SecretStr
from langchain_openai import AzureChatOpenAI

from browser_use import BrowserConfig, Agent, Browser
from browser_use import BrowserContextConfig
from browser_use.agent.service import Agent
from browser_use.browser.browser import Browser, BrowserConfig, BrowserContextConfig

# Load environment variables
load_dotenv()

# Validate required environment variables
required_env_vars = ["AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT"]
for var in required_env_vars:
    if not os.getenv(var):
        raise ValueError(f"{var} is not set. Please add it to your environment variables.")

# Browser setup
browser = Browser(
    config=BrowserConfig(
        headless=True,  # True in production
        disable_security=True,
        new_context_config=BrowserContextConfig(
            disable_security=True,
            minimum_wait_page_load_time=1,  # 3 in production
            maximum_wait_page_load_time=10, # 20 in production
            browser_window_size={
                'width': 1280,
                'height': 1100,
            },
        ),
    )
)

# LLM setup
llm = AzureChatOpenAI(
    model='gpt-4o',
    api_version='2024-10-21',
    azure_endpoint=os.getenv('AZURE_OPENAI_ENDPOINT', ''),
    api_key=SecretStr(os.getenv('AZURE_OPENAI_API_KEY', '')),
)

# Example task
TASK = """
Go to https://blazedemo.com/index.php and select Boston for departure and London for destination. 
Then click on Find Flights. Select the first flight and click on Choose This Flight. 
Then on the next page, scroll down by some amount and just do nothing. Do nothing after that.
"""

def print_menu():
    print('\nAgent Control Menu:')
    print('1. Start')
    print('2. Pause')
    print('3. Resume')
    print('4. Stop')
    print('5. Exit')

async def console_loop(agent):
    """
    Continuously prompt the user for commands and manage
    the agent's async task.
    """
    agent_task = None

    while True:
        print_menu()

        # Read user input in a non-blocking way via asyncio.to_thread
        choice = await asyncio.to_thread(input, 'Enter your choice (1-5): ')

        if choice == '1':
            if agent_task is None:
                print('Starting agent...')
                # Create an asyncio Task so agent.run() executes in the background
                agent_task = asyncio.create_task(agent.run(max_steps=50))
            else:
                print('Agent is already running or paused.')
        
        elif choice == '2':
            print('Pausing agent...')
            agent.pause()

        elif choice == '3':
            print('Resuming agent...')
            agent.resume()

        elif choice == '4':
            print('Stopping agent...')
            agent.stop()
            # If the agent task is running, cancel it and wait for it to finish
            if agent_task:
                agent_task.cancel()
                try:
                    await agent_task
                except asyncio.CancelledError:
                    pass
                agent_task = None

        elif choice == '5':
            print('Exiting...')
            if agent_task:
                agent.stop()
                agent_task.cancel()
                try:
                    await agent_task
                except asyncio.CancelledError:
                    pass
            break

        else:
            print("Unknown command. Please enter a valid option.")

async def main():
    """
    Main entry point: Initialize the agent, then start
    the console loop to handle user commands asynchronously.
    """
    agent = Agent(
        task=TASK,
        llm=llm,
        browser=browser,
    )

    await console_loop(agent)

if __name__ == "__main__":
    asyncio.run(main())
