import asyncio

from dotenv import load_dotenv
from langchain_openai import AzureChatOpenAI

from supatest.agent.service import SupatestAgent

load_dotenv()

# Initialize the model
llm = AzureChatOpenAI(
	model='gpt-4o',
	temperature=0.0,
)
task = 'Find the founders of browser-use and draft them a short personalized message'

agent = SupatestAgent(task=task, llm=llm)


async def main():
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
