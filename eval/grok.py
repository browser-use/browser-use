import os
from langchain_openai import ChatOpenAI
from pydantic import SecretStr
from browser_use import Agent
import asyncio
from dotenv import load_dotenv
load_dotenv()

api_key = os.getenv('GROK_API_KEY', '')
if not api_key:
	raise ValueError('GROK_API_KEY is not set')

async def main():
    agent = Agent(
        task='Go to https://www.google.com and search for "python" and click on the first result',
        use_vision=False,
        llm=ChatOpenAI(model="grok-2-1212",base_url="https://api.x.ai/v1",api_key=SecretStr(api_key)),
    )

    await agent.run()

asyncio.run(main())