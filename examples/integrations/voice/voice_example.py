import asyncio
import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv

load_dotenv()

import click

from browser_use.cli import run_prompt_mode
from browser_use.voice import capture_voice_command


async def main() -> None:
	"""Capture a spoken command and run browser-use with it."""
	text = await capture_voice_command()
	await run_prompt_mode(text, click.Context(run_prompt_mode))  # type: ignore[arg-type]


if __name__ == "__main__":
	asyncio.run(main())
