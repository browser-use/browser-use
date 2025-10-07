"""
Example: Using browser-use with llm-use cloud service

This example demonstrates how to connect browser-use to a remote llm-use
cloud service instead of calling Google Gemini directly.

Benefits:
- Centralized LLM cost tracking and management
- Optimized unstructured output parsing on the server
- Credit-based billing system
- Support for multiple API keys with isolated credits

Requirements:
- llm-use service deployed (e.g., on Railway)
- Valid API key configured in the service
"""

import asyncio
import os
from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel

from browser_use import Agent
from browser_use.browser.session import BrowserSession
from browser_use.llm.base import BaseChatModel
from browser_use.llm.messages import BaseMessage, SystemMessage
from browser_use.llm.views import ChatInvokeCompletion, ChatInvokeUsage

T = TypeVar("T", bound=BaseModel)


@dataclass
class ChatLLMUseCloud(BaseChatModel):
	"""
	Browser-use compatible client for llm-use cloud service.

	This client wraps the llm-use HTTP API and makes it compatible with
	browser-use's LLM interface.
	"""

	api_url: str
	api_key: str
	super_fast: bool = True
	model: str = "gemini-flash-lite-latest"  # Required by BaseChatModel

	def __post_init__(self):
		"""Normalize API URL"""
		self.api_url = self.api_url.rstrip("/")

	@property
	def provider(self) -> str:
		return "llm-use-cloud"

	@property
	def name(self) -> str:
		return f"llm-use-cloud/{self.model}"

	def _convert_messages(self, messages: list[BaseMessage]) -> list[dict]:
		"""Convert browser-use messages to llm-use format"""
		converted = []
		for msg in messages:
			if isinstance(msg, SystemMessage):
				converted.append({"role": "system", "content": msg.content})
			elif hasattr(msg, "role"):
				converted.append({"role": msg.role, "content": msg.content})
			else:
				converted.append({"role": "user", "content": str(msg)})
		return converted

	async def ainvoke(
		self,
		messages: list[BaseMessage],
		output_format: type[T] | None = None,
	) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
		"""
		Call the llm-use cloud service.

		Args:
			messages: List of messages to send
			output_format: Optional Pydantic model for structured output

		Returns:
			ChatInvokeCompletion with completion, usage, and cost
		"""
		import httpx

		# Convert messages to dict format
		messages_dict = self._convert_messages(messages)

		# Extract schema if output format provided
		output_schema = None
		if output_format is not None:
			output_schema = output_format.model_json_schema()

		# Make HTTP request to llm-use service
		async with httpx.AsyncClient() as client:
			response = await client.post(
				f"{self.api_url}/v1/chat/completions",
				json={
					"messages": messages_dict,
					"super_fast": self.super_fast,
					"output_format": output_schema,
				},
				headers={"Authorization": f"Bearer {self.api_key}"},
				timeout=120.0,  # 2 minute timeout for LLM calls
			)

			if response.status_code == 401:
				raise ValueError("Invalid API key")
			elif response.status_code == 402:
				raise ValueError("Insufficient credits")
			elif response.status_code != 200:
				raise ValueError(f"API error: {response.text}")

			result = response.json()

			# Parse usage info
			usage_data = result.get("usage", {})
			usage = ChatInvokeUsage(
				prompt_tokens=usage_data.get("prompt_tokens", 0),
				prompt_cached_tokens=usage_data.get("prompt_cached_tokens", 0),
				prompt_cache_creation_tokens=usage_data.get("prompt_cache_creation_tokens", 0),
				prompt_image_tokens=usage_data.get("prompt_image_tokens", 0),
				completion_tokens=usage_data.get("completion_tokens", 0),
				total_tokens=usage_data.get("total_tokens", 0),
			)

			# Parse completion
			completion_data = result["completion"]
			if output_format is not None:
				# Parse dict into Pydantic model
				completion = output_format.model_validate(completion_data)
			else:
				completion = completion_data

			# Return in format expected by browser-use
			return ChatInvokeCompletion(
				completion=completion,
				usage=usage,
			)

	async def check_credits(self) -> float:
		"""Check remaining credits for this API key"""
		import httpx

		async with httpx.AsyncClient() as client:
			response = await client.get(
				f"{self.api_url}/v1/credits",
				headers={"Authorization": f"Bearer {self.api_key}"},
				timeout=10.0,
			)

			if response.status_code != 200:
				raise ValueError(f"Failed to check credits: {response.text}")

			result = response.json()
			return result["credits_usd"]


async def main():
	"""Example usage of llm-use cloud client with browser-use"""

	# Configure llm-use cloud client
	llm_use_url = os.getenv("LLM_USE_URL", "http://localhost:8000")
	api_key = os.getenv("LLM_USE_API_KEY", "12345678")

	llm = ChatLLMUseCloud(
		api_url=llm_use_url,
		api_key=api_key,
		super_fast=True,  # Use fastest model
	)

	# Check credits before starting
	try:
		credits = await llm.check_credits()
		print(f"💰 Available credits: ${credits:.2f}")
	except Exception as e:
		print(f"⚠️  Could not check credits: {e}")

	# Create browser session
	browser_session = BrowserSession()
	try:
		# Create agent with cloud LLM
		agent = Agent(
			task="Find the number of GitHub stars for the browser-use repository",
			llm=llm,
			browser_session=browser_session,
		)

		# Run the task
		result = await agent.run()
		print(f"✅ Result: {result}")
	finally:
		await browser_session.stop()

	# Check credits after task
	try:
		credits_after = await llm.check_credits()
		print(f"💰 Remaining credits: ${credits_after:.2f}")
		print(f"💸 Cost: ${credits - credits_after:.4f}")
	except Exception as e:
		print(f"⚠️  Could not check credits: {e}")


if __name__ == "__main__":
	asyncio.run(main())
