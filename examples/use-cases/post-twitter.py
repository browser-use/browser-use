"""
Goal: Provides a template for automated posting on X (Twitter), including new tweets, tagging, and replies.

X Posting Template using browser-use
----------------------------------------

This template allows you to automate posting on X using browser-use.
It supports:
- Posting new tweets
- Tagging users
- Replying to tweets

Add your target user and message in the config section.

target_user="XXXXX"
message="XXXXX"
reply_url="XXXXX"

Any issues, contact me on X @defichemist95
"""

import asyncio
import os
import sys
from dataclasses import dataclass

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent, Controller
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.llm import ChatOpenAI

if not os.getenv('OPENAI_API_KEY'):
	raise ValueError('OPENAI_API_KEY is not set. Please add it to your environment variables.')


# ============ Configuration Section ============
@dataclass
class TwitterConfig:
	"""Configuration for Twitter posting"""

	openai_api_key: str
	chrome_path: str
	target_user: str  # Twitter handle without @
	message: str
	reply_url: str
	headless: bool = False
	model: str = 'gpt-4.1-mini'
	base_url: str = 'https://x.com/home'


# Customize these settings
openai_key = os.getenv('OPENAI_API_KEY')
assert openai_key is not None, 'OPENAI_API_KEY must be set'

config = TwitterConfig(
	openai_api_key=openai_key,
	chrome_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',  # This is for MacOS (Chrome)
	target_user='XXXXX',
	message='XXXXX',
	reply_url='XXXXX',
	headless=False,
)


def create_twitter_agent(config: TwitterConfig) -> Agent:
	llm = ChatOpenAI(model=config.model, api_key=config.openai_api_key)

	browser_profile = BrowserProfile(
		headless=config.headless,
		executable_path=config.chrome_path,
	)
	browser_session = BrowserSession(browser_profile=browser_profile)

	controller = Controller()

	# Construct the full message with tag
	full_message = f'@{config.target_user} {config.message}'

	# Create the agent with detailed instructions
	agent = Agent(
		task=f"""Navigate to Twitter and create a post and reply to a tweet.

        Here are the specific steps:

        1. Go to {config.base_url}. See the text input field at the top of the page that says "What's happening?"
        2. Look for the text input field at the top of the page that says "What's happening?"
        3. Click the input field and type exactly this message:
        "{full_message}"
        4. Find and click the "Post" button (look for attributes: 'button' and 'data-testid="tweetButton"')
        5. Do not click on the '+' button which will add another tweet.

        6. Navigate to {config.reply_url}
        7. Before replying, understand the context of the tweet by scrolling down and reading the comments.
        8. Reply to the tweet under 50 characters.

        Important:
        - Wait for each element to load before interacting
        - Make sure the message is typed exactly as shown
        - Verify the post button is clickable before clicking
        - Do not click on the '+' button which will add another tweet
        """,
		llm=llm,
		controller=controller,
		browser_session=browser_session,
	)
	return agent


async def post_tweet(agent: Agent):
	try:
		await agent.run(max_steps=100)
		print('Tweet posted successfully!')
	except Exception as e:
		print(f'Error posting tweet: {str(e)}')


async def main():
	agent = create_twitter_agent(config)
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
