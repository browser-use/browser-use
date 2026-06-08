"""
TWZRD Agent Intel — trust verification before x402 browser agent payments.

This example shows how to use the TWZRD Agent Intel MCP server with browser-use
to verify agent trust scores before authorizing autonomous x402 micropayments.

The TWZRD Agent Intel server exposes:
  - score_agent(wallet)      — returns 0-100 trust score + risk flags (free)
  - preflight_check(wallet)  — PASS/FAIL gate for x402 payment flows (free)
  - get_trust_receipt(wallet) — signed trust receipt, HTTP 402 paid endpoint

MCP endpoint: https://intel.twzrd.xyz/mcp  (streamable-http, no auth required)

Install:
    pip install browser-use mcp

Usage:
    python examples/twzrd_agent_intel.py
"""

import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from browser_use import Agent
from langchain_openai import ChatOpenAI


async def check_agent_trust(wallet: str) -> dict:
    """Check agent trust score via TWZRD Agent Intel MCP server."""
    async with streamablehttp_client("https://intel.twzrd.xyz/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Get trust score (0-100)
            score = await session.call_tool("score_agent", {"wallet": wallet})

            # Get PASS/FAIL preflight result
            preflight = await session.call_tool("preflight_check", {"wallet": wallet})

            return {
                "score": score.content[0].text if score.content else None,
                "preflight": preflight.content[0].text if preflight.content else None,
            }


async def run_trusted_browser_agent(task: str, agent_wallet: str):
    """
    Run a browser-use agent, but only after verifying its trust score.

    This pattern is useful when your browser agent needs to make x402
    micropayments — you can gate payment authorization on the trust score.
    """
    print(f"Checking trust for agent wallet: {agent_wallet[:8]}...")
    trust = await check_agent_trust(agent_wallet)
    print(f"Trust score: {trust['score']}")
    print(f"Preflight: {trust['preflight']}")

    # Gate on preflight result
    if trust["preflight"] and "PASS" not in trust["preflight"].upper():
        print("Agent failed trust check — aborting task.")
        return

    print(f"\nTrust check passed. Running browser task: {task}")

    # Run the browser agent with a trust-aware system prompt
    agent = Agent(
        task=task,
        llm=ChatOpenAI(model="gpt-4o"),
        # Inject trust context so the agent knows its own trust score
        extend_system_message=(
            f"Your trust score is {trust['score']}. "
            "You have been authorized to proceed with this task."
        ),
    )
    result = await agent.run()
    return result


if __name__ == "__main__":
    # Example: verify an agent wallet before authorizing a paid API task
    example_wallet = "4LkEFjHsF2ubC8K4oF2r3rCFqPZQVGBjL9mV6xkNPZdf"
    asyncio.run(
        run_trusted_browser_agent(
            task="Search for the current price of Solana and return it.",
            agent_wallet=example_wallet,
        )
    )
