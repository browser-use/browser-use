from browser_use import Agent, ChatOpenAI

agent = Agent(
	task='Ask human for help',
	llm=ChatOpenAI(model='gpt-4.1-mini'),
)

agent.run_sync()
