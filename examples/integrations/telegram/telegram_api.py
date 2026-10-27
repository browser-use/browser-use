import os
import sys
from typing import Optional

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from dotenv import load_dotenv

load_dotenv()

import telegram  # type: ignore
from telegram import Update  # type: ignore
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters  # type: ignore

from browser_use.agent.service import Agent
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.llm import BaseChatModel


class TelegramBot:
	"""Telegram bot implementation for Browser-Use tasks.

	This bot allows users to run browser automation tasks through Telegram messages.
	Processes tasks asynchronously and sends the result back to the chat.

	Commands:
	    /browse <task> or /bu <task> - Run a browser automation task
	    /start - Display welcome message and instructions
	    /help - Display help message

	Args:
	    llm (BaseChatModel): Language model instance to use for task processing
	    ack (bool, optional): Whether to acknowledge task receipt with an immediate status message. Defaults to True
	    browser_profile (BrowserProfile, optional): Browser profile settings. Defaults to headless mode

	Usage:
	    ```python
	    from browser_use.llm import ChatGoogle
	    from examples.integrations.telegram.telegram_api import TelegramBot

	    llm = ChatGoogle(model='gemini-2.0-flash-exp')
	    bot = TelegramBot(llm=llm, ack=True)
	    bot.run('YOUR_TELEGRAM_BOT_TOKEN')
	    ```
	"""

	def __init__(
		self,
		llm: BaseChatModel,
		ack: bool = True,
		browser_profile: BrowserProfile = BrowserProfile(headless=True),
	):
		self.llm = llm
		self.ack = ack
		self.browser_profile = browser_profile

	async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
		"""Handles the /start command."""
		if not update.effective_message:
			return
		welcome_text = (
			'👋 *Welcome to Browser-Use Telegram Bot!*\n\n'
			'Send me a task to browse the web for you:\n'
			'`/browse <task>` or `/bu <task>`\n\n'
			'Example:\n'
			'`/browse What is the price of Bitcoin today?`\n'
			'`/browse Search for latest AI news on Hacker News`'
		)
		await update.effective_message.reply_text(welcome_text, parse_mode='Markdown')

	async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
		"""Handles the /help command."""
		if not update.effective_message:
			return
		help_text = (
			'📖 *Browser-Use Bot Help*\n\n'
			'Commands:\n'
			'• `/browse <task>`: Run an autonomous browser task\n'
			'• `/bu <task>`: Short alias for browse\n'
			'• `/help`: Show this help message\n\n'
			'The bot will launch an autonomous agent, perform actions on the web, and reply with the findings.'
		)
		await update.effective_message.reply_text(help_text, parse_mode='Markdown')

	async def handle_browse(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
		"""Handles /browse and /bu commands."""
		if not update.effective_message or not update.effective_message.text:
			return

		text = update.effective_message.text.strip()
		parts = text.split(maxsplit=1)
		if len(parts) < 2 or not parts[1].strip():
			await update.effective_message.reply_text(
				'⚠️ Please provide a task to browse.\nExample: `/browse search for trending GitHub repos`',
				parse_mode='Markdown',
			)
			return

		task = parts[1].strip()

		if self.ack:
			try:
				await update.effective_message.reply_text(
					f'⏳ *Starting Browser-Use task:*\n_{task}_\n\nPlease wait while the agent browses the web...',
					parse_mode='Markdown',
				)
			except Exception as e:
				print(f'Error sending ack message: {e}')

		try:
			agent_message = await self.run_agent(task)
			if len(agent_message) > 4000:
				for i in range(0, len(agent_message), 4000):
					await update.effective_message.reply_text(agent_message[i : i + 4000])
			else:
				await update.effective_message.reply_text(agent_message)
		except Exception as e:
			await update.effective_message.reply_text(f'❌ Task failed: {str(e)}')

	async def run_agent(self, task: str) -> str:
		"""Executes the browser agent task asynchronously."""
		try:
			browser_session = BrowserSession(browser_profile=self.browser_profile)
			agent = Agent(task=task, llm=self.llm, browser_session=browser_session)
			result = await agent.run()

			agent_message = None
			if result.is_done():
				agent_message = result.history[-1].result[0].extracted_content

			if agent_message is None:
				agent_message = 'Task completed, but no explicit content was extracted.'

			return agent_message
		except Exception as e:
			raise Exception(f'Browser-use task error: {str(e)}')

	def run(self, token: str) -> None:
		"""Starts the Telegram bot polling."""
		app = ApplicationBuilder().token(token).build()

		app.add_handler(CommandHandler('start', self.start_command))
		app.add_handler(CommandHandler('help', self.help_command))
		app.add_handler(CommandHandler('browse', self.handle_browse))
		app.add_handler(CommandHandler('bu', self.handle_browse))

		print('🚀 Telegram bot started. Listening for /browse commands...')
		app.run_polling()
