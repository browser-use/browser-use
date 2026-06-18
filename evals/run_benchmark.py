from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from browser_use import Agent

logger = logging.getLogger(__name__)


class EvalMetrics(BaseModel):
	success: bool
	steps: int
	latency_seconds: float


async def run_checkout_eval() -> EvalMetrics:
	current_dir = Path(__file__).parent.resolve()
	file_url = f'file://{current_dir / "dummy_checkout.html"}'

	task = (
		f'Navigate to {file_url}. '
		"Fill out the email field with 'eval@browser-use.com', "
		"select 'Express (2 Days)' from the shipping dropdown, "
		"and click the 'Complete Purchase' button. "
		"Stop when the text 'Order Submitted!' appears on the page."
	)

	llm = ChatOpenAI(model='gpt-4o-mini')

	# --- ZERO-DAY BUG PATCH ---
	# Bypass Pyright strict typing for the zero-day provider bug
	llm.provider = 'openai'  # type: ignore
	# --------------------------

	agent = Agent(task=task, llm=llm)  # type: ignore

	logger.info('Starting deterministic evaluation run on %s', file_url)
	start_time = time.time()

	history = await agent.run()

	latency = time.time() - start_time
	# Explicitly handle the Optional[bool] to satisfy Pyright
	success = history.is_successful() is True

	metrics = EvalMetrics(
		success=success,
		steps=history.number_of_steps(),
		latency_seconds=latency,
	)

	_print_results(metrics)
	return metrics


def _print_results(metrics: EvalMetrics) -> None:
	print('\n' + '=' * 40)
	print(' BROWSER USE EVALUATION RESULTS')
	print('=' * 40)
	print(f' Task Success : {"PASSED" if metrics.success else "FAILED"}')
	print(f' Steps Taken  : {metrics.steps}')
	print(f' Latency      : {metrics.latency_seconds:.2f}s')
	print('=' * 40 + '\n')


if __name__ == '__main__':
	logging.basicConfig(level=logging.INFO)
	asyncio.run(run_checkout_eval())
