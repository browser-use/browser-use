import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()


from browser_use.browser import BrowserProfile
from browser_use.llm import ChatGoogle
from examples.integrations.slack.slack_api import SlackBot, app

# load credentials from environment variables
bot_token = os.getenv('SLACK_BOT_TOKEN')
if not bot_token:
	raise ValueError('Slack bot token not found in .env file.')

signing_secret = os.getenv('SLACK_SIGNING_SECRET')
if not signing_secret:
	raise ValueError('Slack signing secret not found in .env file.')

api_key = os.getenv('GOOGLE_API_KEY')
if not api_key:
	raise ValueError('GOOGLE_API_KEY is not set')

llm = ChatGoogle(model='gemini-2.0-flash-exp', api_key=api_key)

slack_bot = SlackBot(
	llm=llm,  # required; instance of BaseChatModel
	bot_token=bot_token,  # required; Slack bot token
	signing_secret=signing_secret,  # required; Slack signing secret
	ack=True,  # optional; whether to acknowledge task receipt with a message, defaults to False
	browser_profile=BrowserProfile(
		headless=True
	),  # optional; useful for changing headless mode or other browser configs, defaults to headless mode
)

app.dependency_overrides[SlackBot] = lambda: slack_bot

if __name__ == '__main__':
	import uvicorn

	uvicorn.run('integrations.slack.slack_api:app', host='0.0.0.0', port=3000)
