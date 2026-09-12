<!-- mcp-name: com.browser-use/browser-use -->
<picture>
  <source media="(prefers-color-scheme: light)" srcset="https://github.com/user-attachments/assets/2ccdb752-22fb-41c7-8948-857fc1ad7e24">
  <source media="(prefers-color-scheme: dark)" srcset="https://github.com/user-attachments/assets/774a46d5-27a0-490c-b7d0-e65fcbbfa358">
  <img alt="Shows a black Browser Use Logo in light color mode and a white one in dark color mode." src="https://github.com/user-attachments/assets/2ccdb752-22fb-41c7-8948-857fc1ad7e24"  width="full">
</picture>

<div align="center">
    <picture>
    <source media="(prefers-color-scheme: light)" srcset="https://github.com/user-attachments/assets/9955dda9-ede3-4971-8ee0-91cbc3850125">
    <source media="(prefers-color-scheme: dark)" srcset="https://github.com/user-attachments/assets/6797d09b-8ac3-4cb9-ba07-b289e080765a">
    <img alt="The AI browser agent." src="https://github.com/user-attachments/assets/9955dda9-ede3-4971-8ee0-91cbc3850125"  width="400">
    </picture>
</div>

<div align="center">
<a href="https://cloud.browser-use.com?utm_source=github&utm_medium=readme-badge-downloads"><img src="https://media.browser-use.tools/badges/package" height="48" alt="Browser-Use Package Download Statistics"></a>
</div>

---

<div align="center">
<a href="#navigate-the-web-like-a-human-does"><img src="https://media.browser-use.tools/badges/demos" alt="Demos"></a>
<img width="16" height="1" alt="">
<a href="https://docs.browser-use.com"><img src="https://media.browser-use.tools/badges/docs" alt="Docs"></a>
<img width="16" height="1" alt="">
<a href="https://browser-use.com/posts"><img src="https://media.browser-use.tools/badges/blog" alt="Blog"></a>
<img width="16" height="1" alt="">
<a href="https://browsermerch.com"><img src="https://media.browser-use.tools/badges/merch" alt="Merch"></a>
<img width="100" height="1" alt="">
<a href="https://github.com/browser-use/browser-use"><img src="https://media.browser-use.tools/badges/github" alt="Github Stars"></a>
<img width="4" height="1" alt="">
<a href="https://x.com/intent/user?screen_name=browser_use"><img src="https://media.browser-use.tools/badges/twitter" alt="Twitter"></a>
<img width="4" height="1" alt="">
<a href="https://link.browser-use.com/discord"><img src="https://media.browser-use.tools/badges/discord" alt="Discord"></a>
<img width="4" height="1" alt="">
<a href="https://cloud.browser-use.com?utm_source=github&utm_medium=readme-badge-cloud"><img src="https://media.browser-use.tools/badges/cloud" height="48" alt="Browser-Use Cloud"></a>
</div>

<br/>

<div align="center">
  <a href="https://browser-use.com">
    <img src="https://browser-use.com/lander/plates/browsers-8dd60aa0.jpg" alt="A person crossing an orange canyon on a giant key-shaped bridge, from the Browser Use website." width="720">
  </a>
</div>

<br/>

# Navigate the web like a human does.

Find an available slot, pick a date and time, handle the CAPTCHA, and book a driving test.

![Browser Use V4 booking a driving test](https://github.com/user-attachments/assets/135885e8-1141-4e10-b719-bf690ae7d260)

[Explore more demos and prompts ↗](https://browser-use.com/showcase)

<br/>

# Which Browser Use do I need?

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="static/readme/which-product-dark.svg">
  <img alt="Three ways to use Browser Use: fully hosted cloud; your existing agent with Browser Use CLI; or the open source Browser Use agent, available as a Python library. The CLI and library each connect to a local or cloud browser." src="static/readme/which-product-light.svg" width="100%">
</picture>

- **[Path 1: Fully Hosted Cloud](#path-1-fully-hosted-cloud):** Scale up with a fully hosted agent and browser.
- **[Path 2: CLI](#path-2-cli):** Automate your own browser tasks.
- **[Path 3: Python Library](#path-3-python-library):** Run the open source Browser Use agent locally from your own code.

# Quickstart

## Path 1: Fully Hosted Cloud

Scale browser automation with our hosted agent, stealth browsers, and infrastructure for profiles, recordings, and data policies.

[Get started with the API ↗](https://docs.browser-use.com/cloud/agent/quickstart)

New Google, GitHub, or Microsoft signups get **$15 cloud credit**.

<br/>

## Path 2: CLI

Paste this prompt into Claude Code, Codex, Hermes, OpenClaw, or your favorite agent.

```text
Install or upgrade browser-use to the latest stable version with uv using Python 3.12, run `browser-use skill install` to register the skill, and connect it to my browser. If setup or connection fails, follow https://github.com/browser-use/browser-harness/blob/main/install.md.
```

<br/>

## Path 3: Python Library

Run the Browser Use agent locally from Python, with your choice of model and a local or cloud browser:

**1. Install Browser Use (Python >= 3.11):**

With [uv](https://docs.astral.sh/uv/getting-started/installation/) installed, run `uv init --python 3.12` first if you're starting a new project.

```bash
uv add browser-use
```

**2. Add your [OpenAI API key](https://platform.openai.com/api-keys) to `.env`:**

```bash
# .env
OPENAI_API_KEY=your-key
# BROWSER_USE_API_KEY=your-key  # Optional: BU2 model or cloud browser
```

For either optional Browser Use service, get a [Browser Use API key](https://cloud.browser-use.com/new-api-key).

**3. Save this as `agent.py`:**

```python
import asyncio

from browser_use import Agent, Browser, ChatBrowserUse, ChatOpenAI
from dotenv import load_dotenv

load_dotenv()

async def main():
    llm = ChatOpenAI(model='gpt-5.6-luna', reasoning_effort='xhigh')
    # llm = ChatBrowserUse(model='bu-2-0')  # Use BU2 instead; requires BROWSER_USE_API_KEY
    agent = Agent(
        task="Find the number of stars of the browser-use repo",
        llm=llm,
        # browser=Browser(use_cloud=True),  # Use a cloud browser; requires BROWSER_USE_API_KEY
    )
    history = await agent.run()
    print(history.final_result())

if __name__ == "__main__":
    asyncio.run(main())
```

To use BU2, replace the `ChatOpenAI` line with the commented `ChatBrowserUse` line. The cloud-browser option works with either model.

**4. Run it:**

```bash
uv run agent.py
```

The agent opens a browser, looks up the repository, and prints its answer.

[Python library docs ↗](https://docs.browser-use.com/open-source/introduction)

<br/>

# Browser Use Benchmark v2

<img alt="Browser Use Benchmark v2 - Mean rubric score by model and cost per task" src="static/hard_benchmark_v2.jpg" width="100%">

This [very hard benchmark](https://github.com/browser-use/benchmark) targets the hardest browser tasks. On easier tasks, even smaller models can achieve very high success rates. Results shown are from a 60-task subset of BU Bench V2.

## Integrations, hosting, custom tools, MCP, and more on our [Docs ↗](https://docs.browser-use.com)

<br/>

# FAQ

<details>
<summary><b>Should I use the fully hosted cloud, CLI, or Python library?</b></summary>

- **[Fully Hosted Cloud](#path-1-fully-hosted-cloud):** Send tasks through the API and let Browser Use run the agent, browser, and infrastructure.
- **[CLI](#path-2-cli):** Give an existing agent (Claude Code, Codex, Hermes, OpenClaw, Pi, Cursor, etc.) browser access. You can use it interactively or in scripts.
- **[Python Library](#path-3-python-library):** Run the open source agent in your own application, with custom tools, structured output, and your choice of model.

The CLI and Python library can each connect to a local or cloud browser. A cloud browser hosts the browser; the fully hosted API runs the agent as well.
</details>

<details>
<summary><b>What's the best model to use?</b></summary>

We recommend **BU2**, our model optimized for browser automation: `ChatBrowserUse(model='bu-2-0')`. It uses `BROWSER_USE_API_KEY`; `ChatBrowserUse()` currently selects the same model.

The best choice depends on your tasks, latency, and budget. See the [BU2 model card](https://docs.browser-use.com/open-source/bu-2-0-model-card), [benchmark](https://github.com/browser-use/benchmark), and [supported models and pricing](https://docs.browser-use.com/open-source/supported-models) to compare options.
</details>

<details>
<summary><b>Can I use Claude / GPT / Gemini through ChatBrowserUse?</b></summary>

Yes. `ChatBrowserUse` accepts provider-prefixed model IDs through the Browser Use gateway, using `BROWSER_USE_API_KEY`:

```python
from browser_use import Agent, ChatBrowserUse

llm = ChatBrowserUse(model='anthropic/claude-sonnet-4-6')  # or 'google/gemini-3-pro'
agent = Agent(task='...', llm=llm)
```

You can also use providers directly through wrappers such as `ChatOpenAI`, `ChatAnthropic`, and `ChatGoogle`, with each provider's own API key. See [supported models](https://docs.browser-use.com/open-source/supported-models).
</details>

<details>
<summary><b>Do I need to provide a system prompt?</b></summary>

No. `Agent(...)` supplies the Browser Use system prompt automatically, including when you change models. Put your task in `task=`. Use `extend_system_message` to add instructions or `override_system_message` to replace the default prompt when you need custom behavior.

See the [custom system prompt example](https://github.com/browser-use/browser-use/blob/main/examples/features/custom_system_prompt.py).
</details>

<details>
<summary><b>Can I use custom tools with the agent?</b></summary>

Yes. Register a function with `Tools` and pass it to the agent. This example adds a tool for the current UTC time and uses `BROWSER_USE_API_KEY` from `.env`:

```python
import asyncio
from datetime import datetime, timezone

from browser_use import ActionResult, Agent, ChatBrowserUse, Tools
from dotenv import load_dotenv

load_dotenv()
tools = Tools()

@tools.action(description='Get the current date and time in UTC.')
def get_current_time() -> ActionResult:
    return ActionResult(extracted_content=datetime.now(timezone.utc).isoformat())

async def main():
    agent = Agent(
        task="What is the current UTC time?",
        llm=ChatBrowserUse(model='bu-2-0'),
        tools=tools,
    )
    history = await agent.run()
    print(history.final_result())

if __name__ == "__main__":
    asyncio.run(main())
```

</details>

<details>
<summary><b>Can I use this for free?</b></summary>

The Python library is free and [MIT-licensed](LICENSE). Model inference and hosted browsers are separate: API providers, including `ChatBrowserUse`, and Browser Use Cloud charge for usage. You can also use a local browser and a local model through [Ollama](https://docs.browser-use.com/open-source/supported-models#ollama), subject to your hardware and model requirements.
</details>

<details>
<summary><b>Terms of Service</b></summary>

This open-source library is licensed under the MIT License. For Browser Use services & data policy, see our [Terms of Service](https://browser-use.com/legal/terms-of-service) and [Privacy Policy](https://browser-use.com/privacy/).
</details>

<details>
<summary><b>How do I handle authentication?</b></summary>

- **Local browser:** Use `Browser.from_system_chrome()` to reuse a Chrome profile. See the [real-browser guide](https://docs.browser-use.com/open-source/customize/browser/real-browser) and [example](https://github.com/browser-use/browser-use/blob/main/examples/browser/real_browser.py).
- **Cloud browser:** Follow the [profile sync guide](https://github.com/browser-use/browser-harness/blob/main/interaction-skills/profile-sync.md), then use `Browser(use_cloud=True, cloud_profile_id='your-profile-id')`.

Profile sync transfers cookies, not local storage, IndexedDB, or extensions. Some sites may require you to sign in again.
</details>

<details>
<summary><b>How do I solve CAPTCHAs?</b></summary>

[Browser Use Cloud](https://docs.browser-use.com/cloud/browser/quickstart) provides stealth browsers and proxies designed to reduce bot detection and CAPTCHA challenges. With the Python library, enable a cloud browser with `Browser(use_cloud=True)` and set `BROWSER_USE_API_KEY`.

Results depend on the site and challenge; no browser configuration guarantees that every CAPTCHA can be avoided or solved.
</details>

<details>
<summary><b>How do I go into production?</b></summary>

Choose how much you want to manage:

- **Keep your agent code:** Connect the CLI or Python library to [cloud browsers](https://docs.browser-use.com/cloud/browser/quickstart) for managed browser infrastructure, stealth, profiles, and recordings.
- **Have us run the agent too:** Use the [fully hosted Cloud API](https://docs.browser-use.com/cloud/agent/quickstart) to submit tasks and retrieve results.

You can also host the Python library and browsers on your own infrastructure.
</details>

<br/>

## Related Repositories

| Repository | What it's for |
| --- | --- |
| [Browser Harness](https://github.com/browser-use/browser-harness) | Our CLI for giving AI agents control of your browser. |
| [Browser Harness JS](https://github.com/browser-use/browser-harness-js) | Give your JavaScript agent control of a real browser. |
| [Browser Use Pi](https://github.com/browser-use/browser-use-pi) | Run a TypeScript browser agent built on Pi. |
| [Cloud SDK](https://github.com/browser-use/sdk) | Integrate Browser Use Cloud into your application. |
| [Video Use](https://github.com/browser-use/video-use) | Edit videos with your coding agent. |
| [macOS Harness](https://github.com/browser-use/macos-harness) | Give your agent control of Mac apps, browsers, and files. |
| [Benchmark](https://github.com/browser-use/benchmark) | Explore browser tasks and compare agent performance. |

<br/>

## Citation

If you use Browser Use in your research or project, please cite:

```bibtex
@software{browser_use2024,
  author = {Müller, Magnus and Žunič, Gregor},
  title = {Browser Use: Enable AI to control your browser},
  year = {2024},
  publisher = {GitHub},
  url = {https://github.com/browser-use/browser-use}
}
```

<br/>

<div align="center">

**Tell your computer what to do, and it gets it done.**

<img src="https://github.com/user-attachments/assets/06fa3078-8461-4560-b434-445510c1766f" width="400"/>

[![Twitter Follow](https://img.shields.io/twitter/follow/Magnus?style=social)](https://x.com/intent/user?screen_name=mamagnus00)
&emsp;&emsp;&emsp;
[![Twitter Follow](https://img.shields.io/twitter/follow/Gregor?style=social)](https://x.com/intent/user?screen_name=gregpr07)

</div>

<div align="center"> Made with ❤️ in Zurich and San Francisco </div>
