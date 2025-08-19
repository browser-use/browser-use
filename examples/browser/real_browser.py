import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent, BrowserProfile, BrowserSession, ChatOpenAI

# SETUP: First copy your real Chrome profile (close Chrome first, then run):
# Mac:
# mkdir -p ~/.config/browseruse/profiles && cp -r ~/Library/Application\ Support/Google/Chrome ~/.config/browseruse/profiles/real-chrome


browser_profile = BrowserProfile(
	executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
	user_data_dir='~/.config/browseruse/profiles/real-chrome',
)
browser_session = BrowserSession(browser_profile=browser_profile)


async def main():
	agent = Agent(
		llm=ChatOpenAI(model='gpt-4.1-mini'),
		task='Visit https://duckduckgo.com and search for "browser-use founders"',
		browser_session=browser_session,
	)
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
