# Browser API (Direct CDP Access)

Connect directly to Browser Use stealth browsers via Chrome DevTools Protocol.

## Table of Contents
- [WebSocket Connection](#websocket-connection)
- [SDK Approach](#sdk-approach)
- [Playwright Integration](#playwright-integration)
- [Puppeteer Integration](#puppeteer-integration)
- [Selenium Integration](#selenium-integration)

---

## WebSocket Connection

Single URL with all config as query params. Browser **auto-starts on connect** and **auto-stops on disconnect** — no REST calls needed to start or stop.

```
wss://connect.browser-use.com?apiKey=YOUR_KEY&proxyCountryCode=us&timeout=30
```

CDP discovery is also available over HTTPS (for tools that use HTTP auto-discovery):
```
https://connect.browser-use.com/json/version?apiKey=YOUR_API_KEY
```

### Query Parameters

| Param | Required | Description |
|-------|----------|-------------|
| `apiKey` | **yes** | API key |
| `proxyCountryCode` | no | Residential proxy country (195+ countries) |
| `profileId` | no | Browser profile UUID |
| `timeout` | no | Session timeout in minutes (max 240) |
| `browserScreenWidth` | no | Browser width in pixels |
| `browserScreenHeight` | no | Browser height in pixels |
| `customProxy.host` | no | Custom proxy host |
| `customProxy.port` | no | Custom proxy port |
| `customProxy.username` | no | Custom proxy username |
| `customProxy.password` | no | Custom proxy password |

## SDK Approach

```python
# Create browser
browser = await client.browsers.create(
    profile_id="uuid",
    proxy_country_code="us",
    timeout=60,
)

print(browser.cdp_url)   # wss://... for CDP connection
print(browser.live_url)  # View in browser

# Stop (unused time refunded)
await client.browsers.stop(browser.id)
```

## Playwright Integration

```python
from playwright.async_api import async_playwright

# Create cloud browser
browser_session = await client.browsers.create(proxy_country_code="us")

# Connect Playwright
pw = await async_playwright().start()
browser = await pw.chromium.connect_over_cdp(browser_session.cdp_url)
page = browser.contexts[0].pages[0]

# Normal Playwright code
await page.goto("https://example.com")
await page.fill("#email", "user@example.com")
await page.click("button[type=submit]")
content = await page.content()

# Cleanup
await pw.stop()
await client.browsers.stop(browser_session.id)
```

## Puppeteer Integration

```javascript
const puppeteer = require('puppeteer-core');

const browser = await client.browsers.create({ proxyCountryCode: 'us' });
const puppeteerBrowser = await puppeteer.connect({ browserWSEndpoint: browser.cdpUrl });
const page = (await puppeteerBrowser.pages())[0];

await page.goto('https://example.com');
// ... normal Puppeteer code

await puppeteerBrowser.close();
await client.browsers.stop(browser.id);
```

## Selenium Integration

```python
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

browser_session = await client.browsers.create(proxy_country_code="us")

options = Options()
options.debugger_address = browser_session.cdp_url.replace("wss://", "").replace("ws://", "").replace("/devtools/browser/", "")
driver = webdriver.Chrome(options=options)

driver.get("https://example.com")
# ... normal Selenium code

driver.quit()
await client.browsers.stop(browser_session.id)
```

### Session Limits

- Free: 15 minutes max
- Paid: 4 hours max
- Pricing: $0.05/hour, billed upfront, proportional refund on early stop, min 1 minute
