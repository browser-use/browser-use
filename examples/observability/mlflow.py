import asyncio
import os

# test if mlflow is installed
try:
	import mlflow  # type: ignore
except ImportError:
	print('MLflow is not installed. Install with: pip install "browser-use[mlflow]"')
	exit(1)

# Select the MLflow tracing backend before importing browser_use (the backend is resolved at import).
os.environ['BROWSER_USE_TRACING_BACKEND'] = 'mlflow'
mlflow.set_tracking_uri(os.getenv('MLFLOW_TRACKING_URI', 'http://localhost:5000'))
mlflow.set_experiment('browser-use')

from browser_use import Agent, ChatOpenAI  # noqa: E402


async def main():
	agent = Agent(task='Find the founders of browser-use', llm=ChatOpenAI(model='gpt-4.1-mini'))
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
