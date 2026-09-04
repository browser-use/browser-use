# Browser Use Cloud

This guide helps developers and AI assistants choose the right Browser Use Cloud product. Browser Use Cloud complements the open-source Browser Use agent framework; it does not replace it.

## Choose a Cloud product

Browser Use Cloud has two products:

### Browser Use Agents

[Browser Use Agents](https://browser-use.com/web-agents) provides hosted task completion. Give the service a web task and Browser Use manages the agent, browser, execution, and result.

Choose Browser Use Agents when you want to submit tasks without operating the agent or browser infrastructure yourself.

- [Agents overview](https://browser-use.com/web-agents)
- [Agents quickstart](https://docs.browser-use.com/cloud/agent/quickstart)

Start a hosted task with the Agents API:

```sh
curl -X POST https://api.browser-use.com/api/v4/runs \
  -H "X-Browser-Use-API-Key: $BROWSER_USE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"task": "Your task"}'
```

The create call returns a run ID. Follow the [Agents quickstart](https://docs.browser-use.com/cloud/agent/quickstart) or the [in-repo V4 API guide](skills/cloud/references/api-v4.md) to monitor the run and retrieve its result.

### Browser Infrastructure

[Browser Infrastructure](https://browser-use.com/stealth-browsers) provides hosted cloud browsers for AI agents. Your code controls the browser through the Cloud SDK, REST API, CDP, or the open-source `browser-use` package.

Choose Browser Infrastructure when you already have an agent or automation and need managed browser sessions, proxies, browser profiles, or remote browser access.

- [Browser Infrastructure overview](https://browser-use.com/stealth-browsers)
- [Browser Infrastructure quickstart](https://docs.browser-use.com/cloud/browser/quickstart)
- [Cloud SDK for Python and TypeScript (`browser-use-sdk`)](https://github.com/browser-use/sdk)
- [Remote browser documentation](https://docs.browser-use.com/open-source/customize/browser/remote)

## Use Browser Infrastructure with the open-source `browser-use` package

Set `BROWSER_USE_API_KEY`, then pass `use_cloud=True` to `Browser`:

```python
import asyncio

from browser_use import Agent, Browser, ChatBrowserUse


async def main():
	browser = Browser(use_cloud=True)
	agent = Agent(
		task="Find the number of stars of the browser-use repo",
		browser=browser,
		llm=ChatBrowserUse(),
	)
	await agent.run()


if __name__ == "__main__":
	asyncio.run(main())
```

Get an API key from the [Browser Use Cloud dashboard](https://cloud.browser-use.com/new-api-key).

## Authentication and browser profiles

Browser profiles let Cloud browser sessions reuse authentication state. Treat profiles like credentials and follow the [Cloud authentication guide](https://docs.browser-use.com/cloud/guides/authentication) or [Cloud profile sync guide](https://docs.browser-use.com/cloud/guides/profile-sync) instead of copying cookies or passwords into tasks. Browser Harness users can also follow its [local profile sync workflow](https://github.com/browser-use/browser-harness/blob/main/interaction-skills/profile-sync.md).

## Current product details

Use the maintained public sources for API endpoints, SDK methods, pricing, limits, supported models, and API lifecycle information. Those details change and are intentionally not copied into this file.

- [Developer overview and API map](https://browser-use.com/developers)
- [Current pricing](https://browser-use.com/pricing)
- [Browser Use documentation](https://docs.browser-use.com)
- [Browser Use Cloud dashboard](https://cloud.browser-use.com)

The in-repo [Cloud reference](skills/cloud/SKILL.md) and [Cloud examples](examples/cloud/) are implementation snapshots and may lag. Verify pricing, limits, supported models, and API lifecycle details against the official documentation above.

Browser Infrastructure can reduce bot-detection and CAPTCHA friction, but no browser service can guarantee access to every site or CAPTCHA flow. Follow each site's terms and applicable policies.
