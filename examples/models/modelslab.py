"""
Example: Using ModelsLab LLMs with browser-use

ModelsLab provides access to open-source LLMs (Llama, Mistral, Mixtral, etc.)
through an OpenAI-compatible API.

Set your API key:
    export MODELSLAB_API_KEY=your_key_here

API docs: https://docs.modelslab.com
"""

import asyncio
import os

from browser_use import Agent
from browser_use.llm.modelslab.chat import ChatModelsLab


async def main():
    # Initialize ModelsLab chat model
    llm = ChatModelsLab(
        model='llama-3-70b-chat',  # or 'mistral-7b-v0.1', 'mixtral-8x7b', etc.
        api_key=os.getenv('MODELSLAB_API_KEY'),
        temperature=0.0,
    )

    agent = Agent(
        task='Go to modelslab.com and tell me the main product offerings.',
        llm=llm,
    )

    result = await agent.run()
    print(result)


if __name__ == '__main__':
    asyncio.run(main())
