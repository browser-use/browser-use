import asyncio

from browser_use import Agent


async def main():
	agent = Agent(
		task='Research the top 3 AI companies and their latest products',
		# Summarizes conversation history every N steps (default: 25)
		# Keeps the last M steps raw for recency (default: 5)
		# At step 25: summarizes 1-20, keeps 21-25
		# At step 50: summarizes 20-45, keeps 46-50
		# At step 75: summarizes 45-70, keeps 71-75
		summarize_every_n_steps=25,  # Can be customized
		summarize_keep_last_n_steps=5,  # Can be customized
	)

	await agent.run(max_steps=100)


if __name__ == '__main__':
	asyncio.run(main())
