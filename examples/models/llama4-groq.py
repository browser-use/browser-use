import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from langchain_openai import ChatOpenAI

from browser_use import Agent

llm = ChatOpenAI(
	model='meta-llama/llama-4-maverick-17b-128e-instruct',
	base_url='https://api.groq.com/openai/v1',
	api_key=os.environ.get('GROQ_API_KEY'),
	temperature=0.0,
)

# llm = ChatGroq(
# 	model='meta-llama/llama-4-maverick-17b-128e-instruct',
# 	api_key=os.environ.get('GROQ_API_KEY'),
# 	temperature=0.0,
# )

task = 'Open the page with an overview of the submission of releases on Discogs. Website: https://www.discogs.com/ '


async def main():
	agent = Agent(
		task=task,
		llm=llm,
	)
	await agent.run()


if __name__ == '__main__':
	for i in range(10):
		print(f'Running {i + 1} of 10')
		asyncio.run(main())
