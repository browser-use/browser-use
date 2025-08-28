import asyncio
from py_compile import main
from browser_use import Agent, ChatOpenAI ,ChatGoogle

agent = Agent(
	task='Find founders of browser-use',
	llm=ChatGoogle(model='gemini-2.0-flash'),
)

agent.run_sync()

if __name__ == '__main__':
    asyncio.run(main())