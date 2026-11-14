import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from dotenv import load_dotenv

load_dotenv()

from telegram import Update  # type: ignore
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes  # type: ignore

from browser_use.agent.service import Agent
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.llm import BaseChatModel


class TelegramBot:
	"""Telegram bot implementation for Browser-Use tasks.

	This bot allows users to run browser automation tasks through Telegram messages.
	Processes tasks asynchronously in background workers and sends results back to the chat.

	Commands:
		/browse <task> or /bu <task> - Run a browser automation task
		/start - Display welcome message and instructions
		/help - Display help message

	Args:
		llm (BaseChatModel): Language model instance to use for task processing
		ack (bool, optional): Whether to acknowledge task receipt with an immediate status message. Defaults to True
		browser_profile (BrowserProfile, optional): Browser profile settings. Defaults to headless mode
		allowed_user_ids (list[int] | None, optional): Optional list of allowed Telegram user IDs. Defaults to None (open to all)
		allowed_chat_ids (list[int] | None, optional): Optional list of allowed Telegram chat IDs. Defaults to None (open to all)

	Usage:
		```python
	        from browser_use.llm import ChatGoogle
	        from examples.integrations.telegram.telegram_api import TelegramBot

	        llm = ChatGoogle(model='gemini-2.0-flash-exp')
	        bot = TelegramBot(llm=llm, ack=True, allowed_user_ids=[123456789])
	        bot.run('YOUR_TELEGRAM_BOT_TOKEN')
		```
	"""

	def __init__(
		self,
		llm: BaseChatModel,
		ack: bool = True,
		browser_profile: BrowserProfile = BrowserProfile(headless=True),
		allowed_user_ids: list[int] | None = None,
		allowed_chat_ids: list[int] | None = None,
	):
		self.llm = llm
		self.ack = ack
		self.browser_profile = browser_profile
		self.allowed_user_ids = allowed_user_ids
		self.allowed_chat_ids = allowed_chat_ids
		self._active_tasks: set[asyncio.Task] = set()

	def _is_authorized(self, update: Update) -> bool:
		"""Checks whether the update sender and chat are in the allowlist."""
		user_id = update.effective_user.id if update.effective_user else None
		chat_id = update.effective_chat.id if update.effective_chat else None

		if self.allowed_user_ids is not None:
			if user_id is None or user_id not in self.allowed_user_ids:
				return False

		if self.allowed_chat_ids is not None:
			if chat_id is None or chat_id not in self.allowed_chat_ids:
				return False

		return True

	async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
		"""Handles the /start command."""
		if not update.effective_message:
			return

		if not self._is_authorized(update):
			await update.effective_message.reply_text('Unauthorized: You are not authorized to interact with this bot.')
			return

		await update.effective_message.reply_text(
			'👋 Welcome to Browser-Use Telegram Bot!\n\n'
			'Send me a task using:\n'
			'• `/browse <task>`\n'
			'• `/bu <task>`\n\n'
			'Example: `/browse Find the current weather in Tokyo`',
			parse_mode='Markdown',
		)

	async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
		"""Handles the /help command."""
		if not update.effective_message:
			return

		if not self._is_authorized(update):
			await update.effective_message.reply_text('Unauthorized: You are not authorized to interact with this bot.')
			return

		await update.effective_message.reply_text(
			'🤖 *Browser-Use Bot Help*\n\n'
			'*Commands:*\n'
			'• `/browse <task>` - Execute a web browsing task\n'
			'• `/bu <task>` - Short alias for /browse\n'
			'• `/help` - Show this message\n\n'
			'*Examples:*\n'
			'`/browse Check the top trending repositories on GitHub`\n'
			'`/bu Search for the latest news about Artificial Intelligence`',
			parse_mode='Markdown',
		)

	async def handle_browse(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
		"""Handles /browse and /bu commands by dispatching execution to a background worker."""
		if not update.effective_message or not update.effective_message.text:
			return

		if not self._is_authorized(update):
			await update.effective_message.reply_text('Unauthorized: You are not authorized to run browser tasks on this bot.')
			return

		message_text = update.effective_message.text.strip()
		parts = message_text.split(maxsplit=1)

		if len(parts) < 2 or not parts[1].strip():
			await update.effective_message.reply_text(
				'⚠️ Please provide a task.\nExample: `/browse search python documentation`',
				parse_mode='Markdown',
			)
			return

		task = parts[1].strip()

		if self.ack:
			try:
				await update.effective_message.reply_text('🚀 Starting browser-use task in the background...')
			except Exception as e:
				print(f'Error sending ack message: {e}')

		# Run the agent in a retained background task so asyncio does not garbage-collect it
		task_obj = asyncio.create_task(self._execute_task_and_reply(update, task))
		self._active_tasks.add(task_obj)
		task_obj.add_done_callback(self._active_tasks.discard)

	async def _execute_task_and_reply(self, update: Update, task: str) -> None:
		"""Executes the agent and sends the result back to the user."""
		try:
			agent_message = await self.run_agent(task)
			if not update.effective_message:
				return

			# Telegram messages are limited to 4096 characters
			if len(agent_message) > 4000:
				for i in range(0, len(agent_message), 4000):
					chunk = agent_message[i : i + 4000]
					await update.effective_message.reply_text(chunk)
			else:
				await update.effective_message.reply_text(agent_message)
		except Exception as e:
			print(f'Error during task execution: {e}')
			if update.effective_message:
				try:
					await update.effective_message.reply_text(f'❌ Error during task execution: {e}')
				except Exception:
					pass

	async def run_agent(self, task: str) -> str:
		"""Runs the Browser-Use agent on the requested task."""
		try:
			browser_session = BrowserSession(browser_profile=self.browser_profile)
			agent = Agent(task=task, llm=self.llm, browser_session=browser_session)
			result = await agent.run()

			agent_message = None
			if result.is_done():
				agent_message = result.final_result()

			if not agent_message:
				agent_message = (
					'Task completed, but no explicit content was extracted.'
					if result.is_done()
					else 'Agent stopped without completing the task.'
				)

			return agent_message
		except Exception as e:
			raise Exception(f'Browser-use task failed: {e}') from e

	def run(self, token: str) -> None:
		"""Starts the Telegram bot polling."""
		app = ApplicationBuilder().token(token).build()

		app.add_handler(CommandHandler('start', self.start_command))
		app.add_handler(CommandHandler('help', self.help_command))
		app.add_handler(CommandHandler('browse', self.handle_browse))
		app.add_handler(CommandHandler('bu', self.handle_browse))

		print('Telegram bot is starting polling...')
		app.run_polling()
