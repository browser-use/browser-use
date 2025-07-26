"""
Advanced example: Using multiple MCP servers together.

This example demonstrates how to:
1. Connect multiple MCP servers (Gmail + Filesystem) to browser-use
2. Sign up for a new account on a website
3. Save registration details to a file
4. Retrieve the verification link from Gmail
5. Complete the verification process
"""

import asyncio
import os

from browser_use import Agent, Controller
from browser_use.llm.openai.chat import ChatOpenAI
from browser_use.mcp.client import MCPClient


async def main():
	"""Sign up for account, save details, and verify via Gmail."""

	# Initialize controller
	controller = Controller()

	# Connect to Gmail MCP Server
	# Requires Gmail API credentials - see: https://github.com/GongRzhe/Gmail-MCP-Server#setup
	gmail_env = {}
	if client_id := os.getenv('GMAIL_CLIENT_ID'):
		gmail_env['GMAIL_CLIENT_ID'] = client_id
	if client_secret := os.getenv('GMAIL_CLIENT_SECRET'):
		gmail_env['GMAIL_CLIENT_SECRET'] = client_secret
	if refresh_token := os.getenv('GMAIL_REFRESH_TOKEN'):
		gmail_env['GMAIL_REFRESH_TOKEN'] = refresh_token

	gmail_client = MCPClient(server_name='gmail', command='npx', args=['gmail-mcp-server'], env=gmail_env)

	# Connect to Filesystem MCP Server for saving registration details
	filesystem_client = MCPClient(
		server_name='filesystem',
		command='npx',
		args=['-y', '@modelcontextprotocol/server-filesystem', os.path.expanduser('~/Desktop')],
	)

	# Connect and register tools from both servers
	print('Connecting to Gmail MCP server...')
	await gmail_client.connect()
	await gmail_client.register_to_controller(controller)

	print('Connecting to Filesystem MCP server...')
	await filesystem_client.connect()
	await filesystem_client.register_to_controller(controller)

	# Create agent with extended system prompt for using multiple MCP servers
	agent = Agent(
		task='Sign up for a new Anthropic account using the email example@gmail.com, save the registration details to a file',
		llm=ChatOpenAI(model='gpt-4o'),
		controller=controller,
		extend_system_message="""
You have access to both Gmail and Filesystem tools through MCP servers. When signing up for accounts:

1. Fill out registration forms with the provided email address
2. Use the filesystem tools to create a file called 'anthropic_registration.txt' on the Desktop containing:
   - Email used for registration
   - Timestamp of registration
   - Any username or account details
3. After submitting the registration, use the Gmail MCP tools to check for verification emails
4. Search for recent emails (within the last 5 minutes) from the service you're signing up for
5. Look for verification links or codes in those emails
6. Append the verification details to the registration file
7. Use any verification links or codes found to complete the account setup
8. Update the file with the final account status

Available tools include:
Gmail tools:
- search_emails: Search for emails by query (e.g., "from:noreply@anthropic.com")
- get_email: Get full email content by ID
- list_emails: List recent emails

Filesystem tools:
- read_file: Read content from a file
- write_file: Write content to a file
- list_directory: List files in a directory

Always wait a few seconds after submitting a form before checking Gmail to allow the email to arrive.
""",
	)

	# Run the agent
	result = await agent.run()

	print('\nTask completed!')
	print(f'Result: {result}')

	# Disconnect both MCP clients
	await gmail_client.disconnect()
	await filesystem_client.disconnect()


if __name__ == '__main__':
	# Prerequisites:
	# 1. Install both MCP servers:
	#    npm install -g gmail-mcp-server
	#    npm install -g @modelcontextprotocol/server-filesystem
	# 2. Set up Gmail API credentials following: https://github.com/GongRzhe/Gmail-MCP-Server#setup
	# 3. Set these environment variables:
	#    export GMAIL_CLIENT_ID="your-client-id"
	#    export GMAIL_CLIENT_SECRET="your-client-secret"
	#    export GMAIL_REFRESH_TOKEN="your-refresh-token"

	asyncio.run(main())
