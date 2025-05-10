import asyncio
import os

from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import SecretStr

from browser_use import Agent


async def test_google_model():
	api_key_gemini = SecretStr(os.getenv('GEMINI_API_KEY') or '')
	llm = ChatGoogleGenerativeAI(model='gemini-2.0-flash-exp', api_key=api_key_gemini)

	agent = Agent(
		task='what is the square root of 4',
		llm=llm,
	)

	await agent.run()


if __name__ == '__main__':
	asyncio.run(test_google_model())
