"""
Simple try of the agent.

@dev You need to add OPENAI_API_KEY to your environment variables.
"""

import os
import sys
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio

from langchain_openai import ChatOpenAI
from browser_use import Agent
grocery_list_path = Path.cwd() / 'examples/grocery_list.txt'


# Initialize OpenAI LLM
llm = ChatOpenAI(
    model="gpt-4o-mini", 
    temperature=0.7,
    # function_calling_enabled=True,  # Enable function calling if required
)

# Path to the grocery list file
print(f"grocery_list_path is as follow: {grocery_list_path}")
# Initialize the agent with the grocery list
print(f"RUNNING AGENT")
agent = Agent(
    task="Go to instacart.com, search through my grocery list, add them to cart",
    llm=llm,
    file_path=grocery_list_path,  # Add the grocery list file here
)
print(f"DONE AGENT")

async def main():
    # Run the agent's workflow
    await agent.run(max_steps=50)

# Run the async main function
asyncio.run(main())
