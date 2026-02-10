#!/usr/bin/env python3
"""CLI entrypoint for multi-agent browser-use orchestration.

Usage:
    python scripts/run_multiagent.py --config configs/multiagent_default.yaml --task "Search for the latest Python release"
    python scripts/run_multiagent.py --config configs/multiagent_azure.yaml --task "Find the price of ..." --headless
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# Ensure project root is on path
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
	sys.path.insert(0, project_root)


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description='Run a browser task with multi-agent orchestration (Planner/Searcher/Critic).',
	)
	parser.add_argument(
		'--config',
		type=str,
		required=True,
		help='Path to the multi-agent YAML config file.',
	)
	parser.add_argument(
		'--task',
		type=str,
		required=True,
		help='The task instruction string (same format as browser-use single-agent).',
	)
	parser.add_argument(
		'--headless',
		action='store_true',
		default=False,
		help='Run the browser in headless mode.',
	)
	parser.add_argument(
		'--max-steps',
		type=int,
		default=None,
		help='Override max_steps from config.',
	)
	parser.add_argument(
		'--log-level',
		type=str,
		default=None,
		choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
		help='Override log level from config.',
	)
	return parser.parse_args()


async def main() -> None:
	args = parse_args()

	# Set up basic logging before config is loaded
	logging.basicConfig(
		level=logging.INFO,
		format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
	)

	from browser_use.browser.profile import BrowserProfile
	from multiagent.config import load_config
	from multiagent.orchestrator import MultiAgentOrchestrator

	# Load and optionally override config
	config = load_config(args.config)

	if args.max_steps is not None:
		config.orchestrator.max_steps = args.max_steps

	if args.log_level is not None:
		config.logging.log_level = args.log_level

	# Create browser profile
	browser_profile = BrowserProfile(headless=args.headless)

	# Run orchestrator
	orchestrator = MultiAgentOrchestrator(
		task=args.task,
		config=config,
		config_path=args.config,
		browser_profile=browser_profile,
	)

	result = await orchestrator.run()

	# Print result summary
	print('\n' + '=' * 60)
	print('MULTI-AGENT RUN COMPLETE')
	print('=' * 60)
	print(f'Steps taken:  {len(result.history)}')
	print(f'Task done:    {result.is_done()}')
	print(f'Successful:   {result.is_successful()}')

	final = result.final_result()
	if final:
		print(f'Final result: {final}')

	errors = [e for e in result.errors() if e]
	if errors:
		print(f'Errors:       {errors}')

	print(f'Logs:         {orchestrator.run_logger.run_dir}')
	print('=' * 60)


if __name__ == '__main__':
	asyncio.run(main())
