import asyncio
from pathlib import Path

from browser_use import Agent, Browser, ChatOpenAI

# NOTE: To use this example, install imageio[ffmpeg], e.g. with uv pip install "browser-use[video]"


async def main():
	browser_session = Browser(record_video_dir=Path('./tmp/recordings'))

	agent = Agent(
		task='Go to github.com/trending then navigate to the first trending repository and report how many commits it has.',
		llm=ChatOpenAI(model='gpt-4.1-mini'),
		browser_session=browser_session,
	)

	await agent.run(max_steps=5)

	# The video will be saved automatically when the agent finishes and the session closes.
	print('Agent run finished. Check the ./tmp/recordings directory for the video.')


if __name__ == '__main__':
	asyncio.run(main())
