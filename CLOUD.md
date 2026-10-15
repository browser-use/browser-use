# Browser Use Cloud

Browser Use Cloud is the hosted product from Browser Use. It has two parts:

- **Cloud browsers:** managed Chromium you drive over CDP with Playwright, Puppeteer, or any CDP client.
- **Agents API:** send a task, a hosted agent does it in a cloud browser and returns the result.

Browser Use Cloud is hosted only. The open-source parts are this repo's [browser-use](README.md) Python library and [Browser Harness](https://github.com/browser-use/browser-harness), both MIT. The library can also run on a cloud browser with `Browser(use_cloud=True)`.

Current docs: [docs.browser-use.com/llms.txt](https://docs.browser-use.com/llms.txt). Current prices: [browser-use.com/pricing.md](https://browser-use.com/pricing.md).

## Cloud browsers

| | |
|---|---|
| Price | $0.02 per browser-hour, billed by the minute, 1 minute minimum. No subscription. [Pricing](https://browser-use.com/pricing.md) |
| Proxy | US residential proxy on by default, other countries by `proxyCountryCode`. $5/GB managed residential, $0.20/GB direct or your own proxy. [Proxies](https://docs.browser-use.com/cloud/browser/proxies) |
| CAPTCHAs | Solved automatically by default. Set `"solveCaptchas": false` to handle them yourself. Not guaranteed for every challenge. [CAPTCHA handling](https://docs.browser-use.com/cloud/browser/captcha-handling) |
| Profiles | Save cookies, local storage and login state, then start new browsers already logged in. [Profiles](https://docs.browser-use.com/cloud/guides/authentication) |
| Live view | `liveUrl` shows the running browser. [Live preview](https://docs.browser-use.com/cloud/browser/live-preview) |
| Recording | Off by default. Turn on with `enable_recording=True` / `enableRecording: true`. [Recording](https://docs.browser-use.com/cloud/browser/live-preview) |
| Timeout | Up to 4 hours (240 minutes) per browser. [Create browser](https://docs.browser-use.com/cloud/api-v4/browsers/create-browser-session) |
| Concurrency | 10 to 1,000 concurrent sessions, rising with the project's lifetime payments. [Concurrency](https://docs.browser-use.com/cloud/guides/concurrency) |
| Signup | One-time $1 credit for eligible Google, GitHub or Microsoft signups. [Pricing](https://browser-use.com/pricing.md) |

Stealth: on [Stealth Bench V2](https://browser-use.com/benchmarks/browsers) (100 bot-protected sites, 2 visits each, September 25, 2026), Browser Use Cloud got through on 90.5% of visits, Anchor 82%, Kernel 80.5%, Browserbase 78.5%. Caveat: the sites were picked because Browser Use Cloud historically got through where stock Chrome with a US proxy did not, so they are hard on purpose and not a balanced sample of the web or of anti-bot vendors.

### Connect with Playwright

Get an API key at [cloud.browser-use.com](https://cloud.browser-use.com/settings?tab=api-keys&new=1), then:

```bash
export BROWSER_USE_API_KEY=your_key
pip install --upgrade browser-use-sdk playwright
```

```python
from browser_use_sdk.v4 import BrowserUse
from playwright.sync_api import sync_playwright

with BrowserUse() as client:
    session = client.browsers.create(proxy_country_code="us")
    try:
        if not session.cdp_url:
            raise RuntimeError("The browser did not return a CDP URL")
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(session.cdp_url)
            context = browser.contexts[0]
            page = context.pages[0] if context.pages else context.new_page()
            page.goto("https://example.com")
            print(page.title())
    finally:
        client.browsers.stop(session.id)
```

Closing Playwright or the CDP connection does not stop the cloud browser. Stop it with `client.browsers.stop(id)` or `PATCH /api/v4/browsers/{id}` with `{"action": "stop"}`. Selenium cannot connect to a remote WebSocket CDP URL; use Playwright or Puppeteer. TypeScript, Puppeteer and curl versions: [Browser quickstart](https://docs.browser-use.com/cloud/browser/quickstart).

## Agents API (V4)

Give a task in plain English and get the result. Each run gets a cloud browser, a session for follow-ups, and a workspace for files.

```python
from browser_use_sdk.v4 import BrowserUse

with BrowserUse() as client:
    run = client.runs.create("Find the top Hacker News story")
    result = client.runs.wait_for_completion(run.id)
    print(result.result)
```

```bash
curl https://api.browser-use.com/api/v4/runs \
  -H "X-Browser-Use-API-Key: $BROWSER_USE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"task":"Find the top Hacker News story"}'
```

The SDK is `browser-use-sdk` on PyPI and npm (`import { BrowserUse } from "browser-use-sdk/v4"`). It is a different API from the open-source `browser-use` library. Docs: [Run a task](https://docs.browser-use.com/cloud/agent/quickstart) · [API V4 reference](https://docs.browser-use.com/cloud/api-v4-overview).

## MCP server

`https://api.browser-use.com/v3/mcp`, authenticated with the `x-browser-use-api-key` header:

```bash
claude mcp add -t http -H "x-browser-use-api-key: YOUR_API_KEY" browser-use https://api.browser-use.com/v3/mcp
```

[MCP server docs](https://docs.browser-use.com/cloud/guides/mcp-server)
