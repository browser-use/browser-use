import asyncio

from browser_use import ActionPolicy, Agent, ChatOpenAI, Tools


async def main():
	llm = ChatOpenAI(model='gpt-4.1-mini')

	# Good for research / monitoring tasks: the agent can inspect pages but cannot
	# click, type, upload files, or navigate outside the allowed domains.
	read_only_tools = Tools(
		action_policy=ActionPolicy(
			read_only=True,
			allowed_domains=['browser-use.com', '*.browser-use.com', 'github.com'],
		)
	)
	research_agent = Agent(
		task='Read the Browser Use docs and summarize what MCP tools are available.',
		llm=llm,
		tools=read_only_tools,
	)
	await research_agent.run()

	# For workflows that need clicks/forms, keep the domain boundary and still
	# block transactional actions such as file uploads unless explicitly allowed.
	scoped_tools = Tools(
		action_policy=ActionPolicy(
			allowed_domains=['example.com'],
			block_transactional=True,
		)
	)
	form_agent = Agent(
		task='Open example.com and interact only if needed to inspect the page.',
		llm=llm,
		tools=scoped_tools,
	)
	await form_agent.run()


if __name__ == '__main__':
	asyncio.run(main())
