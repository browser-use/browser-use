import asyncio

from browser_use.code_use import CodeAgent


async def main():
	task = """
Find the WebVoyager dataset, download it and create a new version where you remove all tasks which have older dates than today.
"""

	# Create code-use agent
	agent = CodeAgent(
		task=task,
		max_steps=25,
	)

	try:
		# Run the agent
		print('Running code-use agent to filter WebVoyager dataset...')
		session = await agent.run()

	finally:
		await agent.close()


if __name__ == '__main__':
	asyncio.run(main())
