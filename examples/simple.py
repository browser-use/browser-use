from dotenv import load_dotenv

from browser_use import Agent, ChatGoogle

load_dotenv()

agent = Agent(
	task='Find the number of stars of the browser-use repo',
	llm=ChatGoogle(model='gemini-flash-latest'),
	# browser=Browser(use_cloud=True),  # Uses Browser-Use cloud for the browser
)
agent.run_sync()
