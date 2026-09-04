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
<a href="#what-can-browser-use-do"><img src="https://media.browser-use.tools/badges/demos" alt="Demos"></a>
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

</br>

# What can Browser Use do?

Browser Use lets an AI agent use a web browser the same way humans do — it opens pages, clicks buttons, types, and fills in forms. You describe the task, and it completes it. For example, you can have it:


### 📋 Fill Forms
#### Task: "Fill in this job application with my resume and information."

![Job Application Demo](https://github.com/user-attachments/assets/57611d8e-0474-4de6-84b7-37a0c0cd27e7)

[Example code ↗](https://github.com/browser-use/browser-use/blob/main/examples/use-cases/apply_to_job.py)


### 🍎 Extract data
#### Task: "Extract structured data about my followers and export it as a CSV."

https://github.com/user-attachments/assets/485fd3ec-61b9-4afc-9e86-ee9b85acb592

[Browser Use Cloud Docs ↗](https://docs.browser-use.com/cloud/quickstart)


<br/>

# Quickstart

If you want to use Browser Use in your agent (Claude Code, Codex, Cursor, Hermes, OpenClaw, etc.), paste this prompt, and it sets everything up itself:

```text
Install or upgrade browser-use to the latest stable version with uv using Python 3.12, run `browser-use skill install` to register the skill, and connect it to my browser. If setup or connection fails, follow https://github.com/browser-use/browser-harness/blob/main/install.md.
```

Then tell your agent what you want done.

<br/>

# Python library: automate the web from your own code

Want to automate the web at scale with your preferred supported LLM? Use the Python library:

**1. Install Browser Use (Python >= 3.11):**

```bash
uv add browser-use
# or: pip install browser-use
```

**2. Add your LLM API key to `.env`**. Get one from [Browser Use Cloud](https://cloud.browser-use.com/new-api-key?utm_source=github&utm_medium=readme-quickstart-api-key), or bring your own provider key:

```bash
# .env
BROWSER_USE_API_KEY=your-key
# GOOGLE_API_KEY=your-key
# ANTHROPIC_API_KEY=your-key
```

**3. Run your first agent:**

```python
import asyncio

from browser_use import Agent, ChatBrowserUse

async def main():
    agent = Agent(
        task="Find the number of stars of the browser-use repo",
        llm=ChatBrowserUse(model='openai/gpt-5.5'),
        # llm=ChatBrowserUse(model='bu-2-0-mini-preview'),  # Browser Use's optimized model
        # llm=ChatOpenAI(model='gpt-5.5'),
        # llm=ChatAnthropic(model='claude-opus-4-8'),  # Sonnet also works well
    )
    history = await agent.run()

if __name__ == "__main__":
    asyncio.run(main())
```

Check out the [library docs](https://docs.browser-use.com/open-source/introduction) and the [cloud docs](https://docs.browser-use.com/cloud/quickstart?utm_source=github&utm_medium=readme-cloud-docs) for more!

<br/>

# Open source and Browser Use Cloud

<picture>
  <source media="(prefers-color-scheme: light)" srcset="static/accuracy_by_model_light.png">
  <source media="(prefers-color-scheme: dark)" srcset="static/accuracy_by_model_dark.png">
  <img alt="BU Bench V1 - LLM Success Rates" src="static/accuracy_by_model_light.png" width="100%">
</picture>

We benchmark Browser Use across 100 real-world browser tasks. Full benchmark is open source: **[browser-use/benchmark](https://github.com/browser-use/benchmark)**.

See the [Browser Use benchmark index](https://browser-use.com/benchmarks) for dated agent and browser results, task counts, comparisons, sources, and methodology.

**Use the open-source agent**
- Free, and runs on your own machine
- Deep code-level integration and control: pick your LLM, customize the agent's behavior
- Pair it with a local browser, your own remote browser, or [Browser Infrastructure](https://browser-use.com/stealth-browsers?utm_source=github&utm_medium=readme-oss-browser-infrastructure) for managed cloud browsers, proxies, and browser profiles ([setup guide](https://docs.browser-use.com/open-source/customize/browser/remote))

**Use Browser Use Cloud** when you want managed execution or hosted browser infrastructure:

- **[Browser Use Agents](https://browser-use.com/web-agents?utm_source=github&utm_medium=readme-hosted-agent&utm_campaign=agents)** — give a task to a fully hosted agent. Browser Use manages the agent, browser, execution, and results.
- **[Browser Infrastructure](https://browser-use.com/stealth-browsers?utm_source=github&utm_medium=readme-cloud-infrastructure&utm_campaign=browser-infrastructure)** — provision hosted cloud browsers for AI agents and control them with the [Cloud SDK](https://github.com/browser-use/sdk), REST API, CDP, or the open-source `browser-use` package.

Browser Use Agents support managed integrations, persistent files and memory, and rerunnable scripts ([guide](https://docs.browser-use.com/cloud/agent/scripts)):

```sh
curl -X POST https://api.browser-use.com/api/v4/runs \
  -H "X-Browser-Use-API-Key: $BROWSER_USE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"task": "Your task"}'
```

Get a key in the [Cloud dashboard](https://cloud.browser-use.com/new-api-key?utm_source=github&utm_medium=readme-cloud-api-key), then follow the [Agents quickstart](https://docs.browser-use.com/cloud/agent/quickstart) to monitor the run and retrieve its result.

<br/>

## Integrations, hosting, custom tools, MCP, and more on our [Docs ↗](https://docs.browser-use.com)

<br/>

# FAQ

<details>
<summary><b>Should I use the CLI vs. the Python library?</b></summary>

**Use the CLI** if you already have an agent (Claude Code, Codex, Cursor, Hermes, OpenClaw, etc.) that you want to complete browser tasks for you. The agent installs the skill once (see [Quickstart](#quickstart)) and can then control the browser. Examples:
- "Upload this video to YouTube"
- "Compare these three laptops and give me a table with prices"
- "Fill in this job application with my resume"

**Use the Python library** when you are building software that automates the web. Examples:
- Run many tasks on a schedule or in parallel (scraping, monitoring, QA)
- Embed a browser agent into your own product
- Custom tools, custom system prompts, structured output, fine-grained browser control

Rule of thumb: one-off tasks through an agent → CLI. Repeatable automation in code → Python library.
</details>

<details>
<summary><b>What's the best model to use?</b></summary>

We optimized **ChatBrowserUse()** specifically for browser automation tasks and recommend it as the default Browser Use model.

For pricing and other LLM providers, see our [supported models documentation](https://docs.browser-use.com/open-source/supported-models).
</details>

<details>
<summary><b>Can I use Claude / GPT / Gemini through ChatBrowserUse?</b></summary>

Yes. `ChatBrowserUse` accepts provider-prefixed model ids, so a single `BROWSER_USE_API_KEY` reaches all of them — no separate OpenAI/Anthropic/Google keys required:

```python
from browser_use import Agent, ChatBrowserUse

llm = ChatBrowserUse(model='anthropic/claude-sonnet-4-6')  # or 'openai/gpt-5.5', 'google/gemini-3-pro'
agent = Agent(task='...', llm=llm)
```

For our recommended default, use the `bu-*` models.
</details>

<details>
<summary><b>Should I use the Browser Use system prompt with the open-source preview model?</b></summary>

Yes. If you use `ChatBrowserUse(model='browser-use/bu-30b-a3b-preview')` with a normal `Agent(...)`, Browser Use still sends its default agent system prompt for you.

You do **not** need to add a separate custom "Browser Use system message" just because you switched to the open-source preview model. Only use `extend_system_message` or `override_system_message` when you intentionally want to customize the default behavior for your task.

For the recommended default, use the hosted `bu-*` models. If you want the open-source preview model, the setup stays the same apart from the `model=` value.
</details>

<details>
<summary><b>Can I use custom tools with the agent?</b></summary>

Yes! You can add custom tools to extend the agent's capabilities:

```python
from browser_use import Tools

tools = Tools()

@tools.action(description='Description of what this tool does.')
def custom_tool(param: str) -> str:
    return f"Result: {param}"

agent = Agent(
    task="Your task",
    llm=llm,
    browser=browser,
    tools=tools,
)
```

</details>

<details>
<summary><b>Can I use this for free?</b></summary>

Yes! Browser-Use is open source and free to use. You only need to choose an LLM provider (like OpenAI, Google, ChatBrowserUse, or run local models with Ollama).
</details>

<details>
<summary><b>Terms of Service</b></summary>

This open-source library is licensed under the MIT License. For Browser Use services & data policy, see our [Terms of Service](https://browser-use.com/legal/terms-of-service) and [Privacy Policy](https://browser-use.com/privacy/).
</details>

<details>
<summary><b>How do I handle authentication?</b></summary>

Check out our authentication examples:
- [Using real browser profiles](https://github.com/browser-use/browser-use/blob/main/examples/browser/real_browser.py) - Reuse your existing Chrome profile with saved logins
- If you want to use temporary accounts with inbox, choose AgentMail
- To sync your auth profile with a remote browser, install `profile-use` for your platform from the [official releases](https://github.com/browser-use/profile-use-releases/releases/latest), then follow the [profile sync guide](https://github.com/browser-use/browser-harness/blob/main/interaction-skills/profile-sync.md).

These examples show how to maintain sessions and handle authentication seamlessly.
</details>

<details>
<summary><b>How do I solve CAPTCHAs?</b></summary>

For sites with bot detection, [Browser Infrastructure](https://browser-use.com/stealth-browsers?utm_source=github&utm_medium=readme-faq-captcha) provides managed browser fingerprints and proxies. No browser service can guarantee access to every site or CAPTCHA flow.
</details>

<details>
<summary><b>How do I go into production?</b></summary>

Chrome can consume a lot of memory, and running many agents in parallel can be tricky to manage.

For production use cases, choose:

- [Browser Use Agents](https://browser-use.com/web-agents?utm_source=github&utm_medium=readme-faq-production&utm_campaign=agents) for hosted agent execution, persistent files and memory, and managed task results
- [Browser Infrastructure](https://browser-use.com/stealth-browsers?utm_source=github&utm_medium=readme-faq-production&utm_campaign=browser-infrastructure) when your code needs managed browser sessions, proxies, browser fingerprints, and parallel browser execution
</details>

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
