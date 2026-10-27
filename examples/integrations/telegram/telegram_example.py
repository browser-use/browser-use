import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from dotenv import load_dotenv

load_dotenv()

from browser_use.browser import BrowserProfile
from browser_use.llm import ChatGoogle
from examples.integrations.telegram.telegram_api import TelegramBot

# Load credentials from environment variables
bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
if not bot_token:
	raise ValueError('TELEGRAM_BOT_TOKEN not found in .env file.')

api_key = os.getenv('GOOGLE_API_KEY')
if not api_key:
	raise ValueError('GOOGLE_API_KEY is not set')

llm = ChatGoogle(model='gemini-2.0-flash-exp', api_key=api_key)

bot = TelegramBot(
	llm=llm,
	ack=True,
	browser_profile=BrowserProfile(headless=True),
)

if __name__ == '__main__':
	bot.run(token=bot_token)
