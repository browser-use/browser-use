"""
This examples requires you to have a Discord bot token and the bot already added to a server.

Five Steps to create and invite a Discord bot:

1. Create a Discord Application:
    *   Go to the Discord Developer Portal: https://discord.com/developers/applications
    *   Log in to the Discord website.
    *   Click on "New Application".
    *   Give the application a name and click "Create".
2. Configure the Bot:
    *   Navigate to the "Bot" tab on the left side of the screen.
    *   Make sure "Public Bot" is ticked if you want others to invite your bot.
	*	Generate your bot token by clicking on "Reset Token", Copy the token and save it securely.
        *   Do not share the bot token. Treat it like a password. If the token is leaked, regenerate it.
3. Enable Privileged Intents:
    *   Scroll down to the "Privileged Gateway Intents" section.
    *   Enable the necessary intents (e.g., "Server Members Intent" and "Message Content Intent").
   -->  Note: Enabling privileged intents for bots in over 100 guilds requires bot verification. You may need to contact Discord support to enable privileged intents for verified bots.
4. Generate Invite URL:
    *   Go to "OAuth2" tab and "OAuth2 URL Generator" section.
    *   Under "scopes", tick the "bot" checkbox.
    *   Tick the permissions required for your bot to function under “Bot Permissions”.
		*	e.g. "Send Messages", "Send Messages in Threads", "Read Message History",  "Mention Everyone".
    *   Copy the generated URL under the "GENERATED URL" section at the bottom.
5. Invite the Bot:
    *   Paste the URL into your browser.
    *   Choose a server to invite the bot to.
    *   Click “Authorize”.
   -->  Note: The person adding the bot needs "Manage Server" permissions.
6. Run the code below to start the bot with your bot token.
7. Write e.g. "/bu what's the weather in Tokyo?" to start a browser-use task and get a response inside the Discord channel.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from dotenv import load_dotenv

load_dotenv()

from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import SecretStr

from browser_use.browser import BrowserProfile
from examples.integrations.discord.discord_api import DiscordBot

# load credentials from environment variables
bot_token = os.getenv('DISCORD_BOT_TOKEN')
if not bot_token:
	raise ValueError('Discord bot token not found in .env file.')

api_key = os.getenv('GOOGLE_API_KEY')
if not api_key:
	raise ValueError('GOOGLE_API_KEY is not set')

llm = ChatGoogleGenerativeAI(model='gemini-2.0-flash-exp', api_key=SecretStr(api_key))

bot = DiscordBot(
	llm=llm,  # required; instance of BaseChatModel
	prefix='$bu',  # optional; prefix of messages to trigger browser-use, defaults to "$bu"
	ack=True,  # optional; whether to acknowledge task receipt with a message, defaults to False
	browser_profile=BrowserProfile(
		headless=False
	),  # optional; useful for changing headless mode or other browser configs, defaults to headless mode
)

bot.run(
	token=bot_token,  # required; Discord bot token
)
