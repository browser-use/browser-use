# Telegram Integration

This integration demonstrates how to run Browser-Use tasks directly from a Telegram Bot.

## Features

- `/browse <task>` or `/bu <task>`: Run an autonomous browser automation agent from Telegram.
- Asynchronous task processing with immediate acknowledgment (`ack`).
- Support for chunked response messages (respecting Telegram's 4096-character limit).
- Headless or headful browser configuration via `BrowserProfile`.

## Prerequisites

1. **Telegram Bot Token**:
   - Open Telegram and message [@BotFather](https://t.me/BotFather).
   - Send `/newbot` and follow instructions to name your bot.
   - Copy the generated API token.

2. **LLM API Key**:
   - `GOOGLE_API_KEY` (or `OPENAI_API_KEY`).

3. **Install Dependencies**:
   ```bash
   pip install python-telegram-bot
   ```
   Or using `uv`:
   ```bash
   uv pip install python-telegram-bot
   ```

## Setup

1. Create a `.env` file in your project root or set environment variables:
   ```env
   TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
   GOOGLE_API_KEY=your_google_api_key_here
   ```

2. Run the example:
   ```bash
   python examples/integrations/telegram/telegram_example.py
   ```
   Or with `uv`:
   ```bash
   uv run python examples/integrations/telegram/telegram_example.py
   ```

## Usage in Telegram

Open your bot in Telegram and send:
- `/start` - Get welcome and help instructions.
- `/browse What are the top 5 trending repositories on GitHub today?`
- `/bu Search for current weather in Tokyo`
