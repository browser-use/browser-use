"""
Simple example of using MCP client with browser-use.

This example shows how to connect to an MCP server and use its tools with an agent.
"""

import asyncio
import os

from browser_use import Agent, Controller
from browser_use.llm.openai.chat import ChatOpenAI
from browser_use.mcp.client import MCPClient


async def main():
	# Initialize controller
	controller = Controller()

	# Connect to a filesystem MCP server
	# This server provides tools to read/write files in a directory
	mcp_client = MCPClient(
		server_name='filesystem', command='npx', args=['@modelcontextprotocol/server-filesystem', os.path.expanduser('~/Desktop')]
	)

	# Connect and register MCP tools
	await mcp_client.connect()
	await mcp_client.register_to_controller(controller)

	# Create agent with MCP-enabled controller
	agent = Agent(
		task='List all files on the Desktop and read the content of any .txt files you find',
		llm=ChatOpenAI(model='gpt-4o'),
		controller=controller,
	)

	# Run the agent - it now has access to filesystem tools
	await agent.run()

	# Disconnect when done
	await mcp_client.disconnect()


if __name__ == '__main__':
	asyncio.run(main())
