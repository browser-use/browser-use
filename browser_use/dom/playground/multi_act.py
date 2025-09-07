from browser_use import Agent
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.browser.types import ViewportSize
from browser_use.llm import ChatAzureOpenAI

# Initialize the Azure OpenAI client
llm = ChatAzureOpenAI(
	model='gpt-4.1-mini',
)


TASK = """
Go to https://browser-use.github.io/stress-tests/challenges/react-native-web-form.html and complete the React Native Web form by filling in all required fields and submitting.
"""


async def main():
	browser = BrowserSession(
		browser_profile=BrowserProfile(
			window_size=ViewportSize(width=1100, height=1000),
		)
	)

	agent = Agent(task=TASK, llm=llm)

	await agent.run()


if __name__ == '__main__':
	import asyncio

	asyncio.run(main())
