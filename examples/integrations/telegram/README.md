# Telegram Integration

This integration demonstrates how to run Browser-Use tasks directly from a Telegram Bot.

## Features

- `/browse <task>` or `/bu <task>`: Run an autonomous browser automation agent from Telegram.
- Non-blocking background task processing with immediate status acknowledgment (`ack`).
- Security allowlists (`allowed_user_ids` and `allowed_chat_ids`) to prevent unauthorized bot usage.
- Support for chunked response messages (respecting Telegram's 4096-character limit).
- Headless or headful browser configuration via `BrowserProfile`.

## Prerequisites

1. **Telegram Bot Token**:
   - Open Telegram and message [@BotFather](https://t.me/BotFather).
   - Send `/newbot` and follow the instructions to name your bot.
   - Copy the generated API token.

2. **LLM API Key**:
   - `GOOGLE_API_KEY` (used in the provided `ChatGoogle` example).

3. **Install Dependencies**:
   Clone the repository and set up the development environment from the repo root:
   ```bash
   git clone https://github.com/browser-use/browser-use.git
   cd browser-use
   uv sync
   ```
   Install the optional `python-telegram-bot` package:
   ```bash
   uv pip install python-telegram-bot
   ```
   Or using standard `pip`:
   ```bash
   pip install python-telegram-bot
   ```

## Setup

1. Create a `.env` file in your project root or set environment variables:
   ```env
   TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
   GOOGLE_API_KEY=your_google_api_key_here
   # Optional: restrict bot access to specific Telegram user IDs (comma-separated)
   ALLOWED_USER_IDS=123456789,987654321
   ```

2. Run the example:
   ```bash
   uv run python examples/integrations/telegram/telegram_example.py
   ```
   Or with standard python:
   ```bash
   python examples/integrations/telegram/telegram_example.py
   ```

## Usage in Telegram

Open your bot in Telegram and send:

- `/start` - View welcome instructions
- `/help` - View available commands
- `/browse <task>` or `/bu <task>` - Execute a browsing task

Example:
```text
/browse Find the top trending repositories on GitHub and summarize their descriptions
```
