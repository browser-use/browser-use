"""
Token cost service that tracks LLM token usage and costs.

Fetches pricing data from LiteLLM repository and caches it for 1 day.
Automatically tracks token usage when LLMs are registered and invoked.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import aiofiles
import aiofiles.os
import httpx
from dotenv import load_dotenv

from browser_use.llm.base import BaseChatModel
from browser_use.llm.views import ChatInvokeUsage
from browser_use.tokens.views import CachedPricingData, ModelPricing, ModelUsageStats, TokenUsageEntry, UsageSummary

load_dotenv()

from browser_use.config import CONFIG

logger = logging.getLogger(__name__)
cost_logger = logging.getLogger('cost')


def xdg_cache_home() -> Path:
	default = Path.home() / '.cache'
	if CONFIG.XDG_CACHE_HOME and (path := Path(CONFIG.XDG_CACHE_HOME)).is_absolute():
		return path
	return default


class TokenCost:
	"""Service for tracking token usage and calculating costs"""

	CACHE_DIR_NAME = 'browser_use/token_cost'
	CACHE_DURATION = timedelta(days=1)
	PRICING_URL = 'https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json'

	def __init__(self, include_cost: bool = False):
		self.include_cost = include_cost or os.getenv('BROWSER_USE_CALCULATE_COST', 'false').lower() == 'true'

		self.usage_history: list[TokenUsageEntry] = []
		self.registered_llms: dict[str, BaseChatModel] = {}
		self._pricing_data: dict[str, Any] | None = None
		self._initialized = False
		self._cache_dir = xdg_cache_home() / self.CACHE_DIR_NAME

	async def initialize(self) -> None:
		"""Initialize the service by loading pricing data"""
		if not self._initialized:
			if self.include_cost:
				await self._load_pricing_data()
			self._initialized = True

	async def _load_pricing_data(self) -> None:
		"""Load pricing data from cache or fetch from GitHub"""
		# Try to find a valid cache file
		cache_file = await self._find_valid_cache()

		if cache_file:
			await self._load_from_cache(cache_file)
		else:
			await self._fetch_and_cache_pricing_data()

	async def _find_valid_cache(self) -> Path | None:
		"""Find the most recent valid cache file"""
		try:
			# Ensure cache directory exists
			self._cache_dir.mkdir(parents=True, exist_ok=True)

			# List all JSON files in the cache directory
			cache_files = list(self._cache_dir.glob('*.json'))

			if not cache_files:
				return None

			# Sort by modification time (most recent first)
			cache_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)

			# Check each file until we find a valid one
			for cache_file in cache_files:
				if await self._is_cache_valid(cache_file):
					return cache_file
				else:
					# Clean up old cache files
					try:
						os.remove(cache_file)
					except Exception:
						pass

			return None
		except Exception:
			return None

	async def _is_cache_valid(self, cache_file: Path) -> bool:
		"""Check if a specific cache file is valid and not expired"""
		try:
			if not cache_file.exists():
				return False

			# Read the cached data
			async with aiofiles.open(cache_file, 'r') as f:
				content = await f.read()
				cached = CachedPricingData.model_validate_json(content)

			# Check if cache is still valid
			return datetime.now() - cached.timestamp < self.CACHE_DURATION
		except Exception:
			return False

	async def _load_from_cache(self, cache_file: Path) -> None:
		"""Load pricing data from a specific cache file"""
		try:
			async with aiofiles.open(cache_file, 'r') as f:
				content = await f.read()
				cached = CachedPricingData.model_validate_json(content)
				self._pricing_data = cached.data
		except Exception as e:
			print(f'Error loading cached pricing data from {cache_file}: {e}')
			# Fall back to fetching
			await self._fetch_and_cache_pricing_data()

	async def _fetch_and_cache_pricing_data(self) -> None:
		"""Fetch pricing data from LiteLLM GitHub and cache it with timestamp"""
		try:
			async with httpx.AsyncClient() as client:
				response = await client.get(self.PRICING_URL, timeout=30)
				response.raise_for_status()

				self._pricing_data = response.json()

			# Create cache object with timestamp
			cached = CachedPricingData(timestamp=datetime.now(), data=self._pricing_data or {})

			# Ensure cache directory exists
			self._cache_dir.mkdir(parents=True, exist_ok=True)

			# Create cache file with timestamp in filename
			timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
			cache_file = self._cache_dir / f'pricing_{timestamp_str}.json'

			async with aiofiles.open(cache_file, 'w') as f:
				await f.write(cached.model_dump_json(indent=2))

		except Exception as e:
			print(f'Error fetching pricing data: {e}')
			# Fall back to empty pricing data
			self._pricing_data = {}

	async def get_model_pricing(self, model_name: str) -> ModelPricing | None:
		"""Get pricing information for a specific model"""
		# Ensure we're initialized
		if not self._initialized:
			await self.initialize()

		if not self._pricing_data or model_name not in self._pricing_data:
			return None

		data = self._pricing_data[model_name]
		return ModelPricing(
			model=model_name,
			input_cost_per_token=data.get('input_cost_per_token'),
			output_cost_per_token=data.get('output_cost_per_token'),
			max_tokens=data.get('max_tokens'),
			max_input_tokens=data.get('max_input_tokens'),
			max_output_tokens=data.get('max_output_tokens'),
		)

	def calculate_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> tuple[float, float]:
		"""Calculate cost for given token counts. Returns 0 if pricing data is not available or cost tracking is disabled."""
		if not self.include_cost or not self._pricing_data or model not in self._pricing_data:
			return 0.0, 0.0

		data = self._pricing_data[model]
		input_cost_per_token = data.get('input_cost_per_token', 0.0)
		output_cost_per_token = data.get('output_cost_per_token', 0.0)

		input_cost = prompt_tokens * input_cost_per_token
		output_cost = completion_tokens * output_cost_per_token

		return input_cost, output_cost

	def add_usage(self, model: str, usage: ChatInvokeUsage) -> TokenUsageEntry:
		"""Add token usage entry to history (without calculating cost)"""
		entry = TokenUsageEntry(
			model=model,
			timestamp=datetime.now(),
			prompt_tokens=usage.prompt_tokens,
			completion_tokens=usage.completion_tokens,
			total_tokens=usage.total_tokens,
			image_tokens=usage.image_tokens,
		)

		self.usage_history.append(entry)

		return entry

	async def _log_usage(self, model: str, usage: TokenUsageEntry) -> None:
		"""Log usage to the logger"""
		if not self._initialized:
			await self.initialize()

		# ANSI color codes
		C_CYAN = '\033[96m'
		C_YELLOW = '\033[93m'
		C_GREEN = '\033[92m'
		C_RESET = '\033[0m'

		# Format tokens with k notation
		prompt_tokens_fmt = self._format_tokens(usage.prompt_tokens)
		completion_tokens_fmt = self._format_tokens(usage.completion_tokens)

		# Format tokens with or without cost based on whether cost tracking is enabled
		if self.include_cost:
			input_cost, output_cost = self.calculate_cost(model, usage.prompt_tokens, usage.completion_tokens)
			cost = input_cost + output_cost

			if cost > 0:
				input_part = f'{C_YELLOW}{prompt_tokens_fmt} (${input_cost:.4f}){C_RESET}'
				output_part = f'{C_GREEN}{completion_tokens_fmt} (${output_cost:.4f}){C_RESET}'
			else:
				input_part = f'{C_YELLOW}{prompt_tokens_fmt}{C_RESET}'
				output_part = f'{C_GREEN}{completion_tokens_fmt}{C_RESET}'
		else:
			input_part = f'{C_YELLOW}{prompt_tokens_fmt}{C_RESET}'
			output_part = f'{C_GREEN}{completion_tokens_fmt}{C_RESET}'

		cost_logger.info(f'🧠 llm : {C_CYAN}{model}{C_RESET} | ⬅️ tokens: {input_part} | ➡️ tokens: {output_part}')

	def register_llm(self, llm: BaseChatModel) -> BaseChatModel:
		"""
		Register an LLM to automatically track its token usage

		@dev Guarantees that the same instance is not registered multiple times
		"""
		# Use instance ID as key to avoid collisions between multiple instances
		instance_id = str(id(llm))

		# Check if this exact instance is already registered
		if instance_id in self.registered_llms:
			logger.debug(f'LLM instance {instance_id} ({llm.provider}_{llm.model}) is already registered')
			return llm

		self.registered_llms[instance_id] = llm

		# Store the original method
		original_ainvoke = llm.ainvoke
		# Store reference to self for use in the closure
		token_cost_service = self

		# Create a wrapped version that tracks usage
		async def tracked_ainvoke(messages, output_format=None):
			# Call the original method
			result = await original_ainvoke(messages, output_format)

			# Track usage if available (no await needed since add_usage is now sync)
			if result.usage:
				usage = token_cost_service.add_usage(llm.model, result.usage)

				logger.debug(f'Token cost service: {usage}')

				asyncio.create_task(token_cost_service._log_usage(llm.model, usage))

			return result

		# Replace the method with our tracked version
		# Using setattr to avoid type checking issues with overloaded methods
		setattr(llm, 'ainvoke', tracked_ainvoke)

		return llm

	def get_usage_summary(
		self, model: str | None = None, since: datetime | None = None, calculate_cost: bool = True
	) -> UsageSummary:
		"""Get summary of token usage and costs (costs calculated on-the-fly)"""
		filtered_usage = self.usage_history

		if model:
			filtered_usage = [u for u in filtered_usage if u.model == model]

		if since:
			filtered_usage = [u for u in filtered_usage if u.timestamp >= since]

		if not filtered_usage:
			return UsageSummary(
				total_prompt_tokens=0,
				total_prompt_cost=0.0,
				total_completion_tokens=0,
				total_completion_cost=0.0,
				total_tokens=0,
				total_cost=0.0,
				entry_count=0,
			)

		# Calculate totals
		total_prompt = sum(u.prompt_tokens for u in filtered_usage)
		total_completion = sum(u.completion_tokens for u in filtered_usage)
		total_tokens = sum(u.total_tokens for u in filtered_usage)
		models = list({u.model for u in filtered_usage})

		# Calculate per-model stats with on-the-fly cost calculation
		model_stats: dict[str, ModelUsageStats] = {}
		total_prompt_cost = 0.0
		total_completion_cost = 0.0

		for entry in filtered_usage:
			if entry.model not in model_stats:
				model_stats[entry.model] = ModelUsageStats(model=entry.model)

			stats = model_stats[entry.model]
			stats.prompt_tokens += entry.prompt_tokens
			stats.completion_tokens += entry.completion_tokens
			stats.total_tokens += entry.total_tokens
			stats.invocations += 1

			if calculate_cost:
				# Calculate cost on-the-fly
				input_cost, output_cost = self.calculate_cost(entry.model, entry.prompt_tokens, entry.completion_tokens)
				total_prompt_cost += input_cost
				total_completion_cost += output_cost

		# Calculate averages
		for stats in model_stats.values():
			if stats.invocations > 0:
				stats.average_tokens_per_invocation = stats.total_tokens / stats.invocations

		return UsageSummary(
			total_prompt_tokens=total_prompt,
			total_prompt_cost=total_prompt_cost,
			total_completion_tokens=total_completion,
			total_completion_cost=total_completion_cost,
			total_tokens=total_tokens,
			total_cost=total_prompt_cost + total_completion_cost,
			entry_count=len(filtered_usage),
			models=models,
			by_model=model_stats,
		)

	def _format_tokens(self, tokens: int) -> str:
		"""Format token count with k suffix for thousands"""
		if tokens >= 1000:
			return f'{tokens / 1000:.1f}k'
		if tokens >= 1000000:
			return f'{tokens / 1000000:.1f}M'
		if tokens >= 1000000000:
			return f'{tokens / 1000000000:.1f}B'
		return str(tokens)

	async def log_usage_summary(self) -> None:
		"""Log a comprehensive usage summary per model with colors and nice formatting"""
		if not self.usage_history:
			return

		summary = self.get_usage_summary(calculate_cost=self.include_cost)

		if summary.entry_count == 0:
			return

		# ANSI color codes
		C_CYAN = '\033[96m'
		C_YELLOW = '\033[93m'
		C_GREEN = '\033[92m'
		C_BLUE = '\033[94m'
		C_MAGENTA = '\033[95m'
		C_RESET = '\033[0m'
		C_BOLD = '\033[1m'

		# Log overall summary
		total_tokens_fmt = self._format_tokens(summary.total_tokens)
		prompt_tokens_fmt = self._format_tokens(summary.total_prompt_tokens)
		completion_tokens_fmt = self._format_tokens(summary.total_completion_tokens)

		# Format cost breakdowns for input and output (only if cost tracking is enabled)
		if self.include_cost and summary.total_cost > 0:
			total_cost_part = f' (${C_MAGENTA}{summary.total_cost:.4f}{C_RESET})'
			prompt_cost_part = f' (${summary.total_prompt_cost:.4f})'
			completion_cost_part = f' (${summary.total_completion_cost:.4f})'
		else:
			total_cost_part = ''
			prompt_cost_part = ''
			completion_cost_part = ''

		if len(summary.by_model) > 1:
			cost_logger.info(
				f'💲 {C_BOLD}Total Usage Summary{C_RESET}: {C_BLUE}{total_tokens_fmt} tokens{C_RESET}{total_cost_part} | '
				f'⬅️ {C_YELLOW}{prompt_tokens_fmt}{prompt_cost_part}{C_RESET} | ➡️ {C_GREEN}{completion_tokens_fmt}{completion_cost_part}{C_RESET}'
			)

		# Log per-model breakdown
		cost_logger.info(f'📊 {C_BOLD}Per-Model Usage Breakdown{C_RESET}:')

		for model, stats in summary.by_model.items():
			# Format tokens
			model_total_fmt = self._format_tokens(stats.total_tokens)
			model_prompt_fmt = self._format_tokens(stats.prompt_tokens)
			model_completion_fmt = self._format_tokens(stats.completion_tokens)
			avg_tokens_fmt = self._format_tokens(int(stats.average_tokens_per_invocation))

			# Format cost display (only if cost tracking is enabled)
			if self.include_cost:
				# Calculate per-model costs on-the-fly
				total_model_cost = 0.0
				model_prompt_cost = 0.0
				model_completion_cost = 0.0

				# Calculate costs for this model
				for entry in self.usage_history:
					if entry.model == model:
						input_cost, output_cost = self.calculate_cost(entry.model, entry.prompt_tokens, entry.completion_tokens)
						model_prompt_cost += input_cost
						model_completion_cost += output_cost

				total_model_cost = model_prompt_cost + model_completion_cost

				if total_model_cost > 0:
					cost_part = f' (${C_MAGENTA}{total_model_cost:.4f}{C_RESET})'
					prompt_part = f'{C_YELLOW}{model_prompt_fmt} (${model_prompt_cost:.4f}){C_RESET}'
					completion_part = f'{C_GREEN}{model_completion_fmt} (${model_completion_cost:.4f}){C_RESET}'
				else:
					cost_part = ''
					prompt_part = f'{C_YELLOW}{model_prompt_fmt}{C_RESET}'
					completion_part = f'{C_GREEN}{model_completion_fmt}{C_RESET}'
			else:
				cost_part = ''
				prompt_part = f'{C_YELLOW}{model_prompt_fmt}{C_RESET}'
				completion_part = f'{C_GREEN}{model_completion_fmt}{C_RESET}'

			cost_logger.info(
				f'  🤖 {C_CYAN}{model}{C_RESET}: {C_BLUE}{model_total_fmt} tokens{C_RESET}{cost_part} | '
				f'⬅️ {prompt_part} | ➡️ {completion_part} | '
				f'📞 {stats.invocations} calls | 📈 {avg_tokens_fmt}/call'
			)

	def get_cost_by_model(self) -> dict[str, ModelUsageStats]:
		"""Get cost breakdown by model"""
		summary = self.get_usage_summary(calculate_cost=self.include_cost)
		return summary.by_model

	def clear_history(self) -> None:
		"""Clear usage history"""
		self.usage_history = []

	async def refresh_pricing_data(self) -> None:
		"""Force refresh of pricing data from GitHub"""
		if self.include_cost:
			await self._fetch_and_cache_pricing_data()

	async def clean_old_caches(self, keep_count: int = 3) -> None:
		"""Clean up old cache files, keeping only the most recent ones"""
		try:
			# List all JSON files in the cache directory
			cache_files = list(self._cache_dir.glob('*.json'))

			if len(cache_files) <= keep_count:
				return

			# Sort by modification time (oldest first)
			cache_files.sort(key=lambda f: f.stat().st_mtime)

			# Remove all but the most recent files
			for cache_file in cache_files[:-keep_count]:
				try:
					os.remove(cache_file)
				except Exception:
					pass
		except Exception as e:
			print(f'Error cleaning old cache files: {e}')

	async def ensure_pricing_loaded(self) -> None:
		"""Ensure pricing data is loaded in the background. Call this after creating the service."""
		if not self._initialized and self.include_cost:
			# This will run in the background and won't block
			await self.initialize()
