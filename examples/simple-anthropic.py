import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from langchain_anthropic import ChatAnthropic
from browser_use import Agent

sensitive_data = {
    'username': 'standard_user',
    'password': 'secret_sauce'
}

# Initialize the Claude model
llm = ChatAnthropic(
    model="claude-3-opus-20240229",
    temperature=0.0,
    max_tokens=4096,
	sensitive_data=sensitive_data
)

task = 'Go to https://www.saucedemo.com/ and buy Sauce Labs Bike Light'
agent = Agent(task=task, llm=llm)

async def main():
    await agent.run()

if __name__ == '__main__':
    asyncio.run(main())
