<img src="./static/browser-use.png" alt="Browser Use Logo" width="full"/>

<br/>

[![GitHub stars](https://img.shields.io/github/stars/gregpr07/browser-use?style=social)](https://github.com/gregpr07/browser-use/stargazers)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Discord](https://img.shields.io/discord/1303749220842340412?color=7289DA&label=Discord&logo=discord&logoColor=white)](https://link.browser-use.com/discord)
[![Twitter Follow](https://img.shields.io/twitter/follow/gregpr07?style=social)](https://x.com/gregpr07)

Make websites accessible for AI agents 🤖.

Browser use is the easiest way to connect your AI agents with the browser. If you have used Browser Use for your project feel free to show it off in our [Discord](https://link.browser-use.com/discord).

# Quick start

With pip:

```bash
pip install browser-use
```

(optional) install playwright:

```bash
playwright install
```

Spin up your agent:

```python
from langchain_openai import ChatOpenAI
from browser_use import Agent
import asyncio

async def main():
    agent = Agent(
        task="Find a one-way flight from Bali to Oman on 12 January 2025 on Google Flights. Return me the cheapest option.",
        llm=ChatOpenAI(model="gpt-4o"),
    )
    result = await agent.run()
    print(result)

asyncio.run(main())
```

And don't forget to add your API keys to your `.env` file.

```bash
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
```

# Demos

[Prompt](https://github.com/browser-use/browser-use/blob/main/examples/real_browser.py): Write a letter in Google Docs to my Papa, thanking him for everything, and save the document as a PDF.

![Letter to Papa](https://github.com/user-attachments/assets/242ade3e-15bc-41c2-988f-cbc5415a66aa)

<br/><br/>

[Prompt](https://github.com/browser-use/browser-use/blob/main/examples/find_and_apply_to_jobs.py): Read my CV & find ML jobs, save them to a file, and then start applying for them in new tabs, if you need help, ask me.'

https://github.com/user-attachments/assets/171fb4d6-0355-46f2-863e-edb04a828d04

<br/><br/>

Prompt: Find flights on kayak.com from Zurich to Beijing from 25.12.2024 to 02.02.2025. 

![flight search 8x 10fps](https://github.com/user-attachments/assets/ea605d4a-90e6-481e-a569-f0e0db7e6390)

<br/><br/>

[Prompt](https://github.com/browser-use/browser-use/blob/main/examples/save_to_file_hugging_face.py): Look up models with a license of cc-by-sa-4.0 and sort by most likes on Hugging face, save top 5 to file.

https://github.com/user-attachments/assets/de73ee39-432c-4b97-b4e8-939fd7f323b3

# Features ⭐

- Vision + html extraction
- Automatic multi-tab management
- Extract clicked elements XPaths and repeat exact LLM actions
- Add custom actions (e.g. save to file, push to database, notify me, get human input)
- Self-correcting
- Use any LLM supported by LangChain (e.g. gpt4o, gpt4o mini, claude 3.5 sonnet, llama 3.1 405b, etc.)
- Parallelize as many agents as you want

## Register custom actions

If you want to add custom actions your agent can take, you can register them like this:

You can use BOTH sync or async functions.

```python
from browser_use.agent.service import Agent
from browser_use.browser.service import Browser
from browser_use.controller.service import Controller

# Initialize controller first
controller = Controller()

@controller.action('Ask user for information')
def ask_human(question: str, display_question: bool) -> str:
	return input(f'\n{question}\nInput: ')
```

Or define your parameters using Pydantic

```python
class JobDetails(BaseModel):
  title: str
  company: str
  job_link: str
  salary: Optional[str] = None

@controller.action('Save job details which you found on page', param_model=JobDetails, requires_browser=True)
async def save_job(params: JobDetails, browser: Browser):
	print(params)

  # use the browser normally
  page = browser.get_current_page()
	page.go_to(params.job_link)
```

and then run your agent:

```python
model = ChatAnthropic(model_name='claude-3-5-sonnet-20240620', timeout=25, stop=None, temperature=0.3)
agent = Agent(task=task, llm=model, controller=controller)

await agent.run()
```

## Parallelize agents

In 99% cases you should use 1 Browser instance and parallelize the agents with 1 context per agent.
You can also reuse the context after the agent finishes.

```python
browser = Browser()
```

```python
for i in range(10):
    # This create a new context and automatically closes it after the agent finishes (with `__aexit__`)
    async with browser.new_context() as context:
        agent = Agent(task=f"Task {i}", llm=model, browser_context=context)

        # ... reuse context
```

If you would like to learn more about how this works under the hood you can learn more at [playwright browser-context](https://playwright.dev/python/docs/api/class-browsercontext).

### Context vs Browser

If you don't specify a `browser` or `browser_context` the agent will create a new browser instance and context.

## Get XPath history

To get the entire history of everything the agent has done, you can use the output of the `run` method:

```python
history: list[AgentHistory] = await agent.run()

print(history)
```

## Browser configuration

You can configure the browser using the `BrowserConfig` and `BrowserContextConfig` classes.

The most important options are:

- `headless`: Whether to run the browser in headless mode
- `keep_open`: Whether to keep the browser open after the script finishes
- `disable_security`: Whether to disable browser security features (very useful if dealing with cross-origin requests like iFrames)
- `cookies_file`: Path to a cookies file for persistence
- `minimum_wait_page_load_time`: Minimum time to wait before getting the page state for the LLM input
- `wait_for_network_idle_page_load_time`: Time to wait for network requests to finish before getting the page state
- `maximum_wait_page_load_time`: Maximum time to wait for the page to load before proceeding anyway
- `browserbase_api_key`: API key for Browserbase integration
- `browserbase_project_id`: Project ID for Browserbase integration

## More examples

For more examples see the [examples](examples) folder or join the [Discord](https://link.browser-use.com/discord) and show off your project.

## Telemetry

We collect anonymous usage data to help us understand how the library is being used and to identify potential issues. There is no privacy risk, as no personal information is collected. We collect data with PostHog.

You can opt out of telemetry by setting the `ANONYMIZED_TELEMETRY=false` environment variable.

# Contributing

Contributions are welcome! Feel free to open issues for bugs or feature requests.

## Local Setup

1. Create a virtual environment and install dependencies:

```bash
# To install all dependencies including dev
pip install . ."[dev]"
```

2. Add your API keys to the `.env` file:

```bash
cp .env.example .env
```

or copy the following to your `.env` file:

```bash
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
```

You can use any LLM model supported by LangChain by adding the appropriate environment variables. See [langchain models](https://python.langchain.com/docs/integrations/chat/) for available options.

### Building the package

```bash
hatch build
```

Feel free to join the [Discord](https://link.browser-use.com/discord) for discussions and support.

---

<div align="center">
  <b>Star ⭐ this repo if you find it useful!</b><br>
  Made with ❤️ by the Browser-Use team
</div>
