"""Expose the shared Bash executor through OpenAI's tool runner."""

import sys
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from browser_use.integrations.anthropic.bash import run_bash
from openai import pydantic_responses_function_tool
from openai.lib.responses_tool_runner import AsyncRegisteredFunction


class BashInput(BaseModel):
	model_config = ConfigDict(extra='forbid')
	command: str


def Bash(
	*,
	output_dir: str | Path = 'outputs',
	timeout_seconds: float = 120,
	max_output_bytes: int = 10_000,
	python_executable: str | Path | None = None,
) -> AsyncRegisteredFunction:
	"""Create an OpenAI Bash tool with bounded execution and output."""

	root = Path(output_dir).expanduser().absolute()

	async def execute(args: BashInput) -> str:
		return await run_bash(
			args.command,
			output_dir=output_dir,
			timeout_seconds=timeout_seconds,
			max_output_bytes=max_output_bytes,
			python_executable=python_executable or sys.executable,
			home_dir=root / '.tmp' / 'home',
		)

	return AsyncRegisteredFunction.from_tool(
		pydantic_responses_function_tool(
			BashInput,
			name='bash',
			description='Run Bash for computation and create files in the output directory. Use browser tools for browser actions.',
		),
		execute=execute,
	)
