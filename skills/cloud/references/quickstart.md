# Cloud Quickstart, Pricing & FAQ

> This page keeps the v2 quickstart for existing integrations. For a new
> hosted-agent integration, use [API v4](api-v4.md). V4 is the current API and
> SDK path.

## Table of Contents
- [Overview](#overview)
- [Setup](#setup)
- [First Task](#first-task)
- [Structured Output](#structured-output)
- [Live View](#live-view)
- [Pricing](#pricing)
- [FAQ & Troubleshooting](#faq--troubleshooting)

---

## Overview

Browser Use Cloud is the hosted platform for web automation. Stealth browsers with anti-fingerprinting, CAPTCHA solving, residential proxies in 195+ countries. Usage-based pricing via API keys.

- Web app: https://cloud.browser-use.com/
- API base: `https://api.browser-use.com/api/v2/`
- Auth header: `X-Browser-Use-API-Key: <key>`

## Setup

### Python

```bash
pip install browser-use-sdk
```

```python
from browser_use_sdk import BrowserUse
client = BrowserUse()  # Uses BROWSER_USE_API_KEY env var
```

### TypeScript

```bash
npm install browser-use-sdk
```

```typescript
import BrowserUse from 'browser-use-sdk';
const client = new BrowserUse();  // Uses BROWSER_USE_API_KEY env var
```

### cURL

```bash
export BROWSER_USE_API_KEY=your-key
```

## First Task

### SDK

```python
result = await client.run("Search for top Hacker News post and return title and URL")
print(result.output)
```

### cURL

```bash
curl -X POST https://api.browser-use.com/api/v2/tasks \
     -H "X-Browser-Use-API-Key: $BROWSER_USE_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{"task": "Search for the top Hacker News post and return the title and url."}'
```

Response: `{"id": "<task-id>", "sessionId": "<session-id>"}`

## Structured Output

```python
from pydantic import BaseModel

class HNPost(BaseModel):
    title: str
    url: str
    points: int

result = await client.run(
    "Find top Hacker News post",
    output_schema=HNPost
)
print(result.output)  # HNPost instance
```

## Live View

Every session has a `liveUrl`:

```bash
curl https://api.browser-use.com/api/v2/sessions/<sessionId> \
     -H "X-Browser-Use-API-Key: $BROWSER_USE_API_KEY"
```

Open the `liveUrl` to watch the agent work in real-time.

---

## Pricing

All usage draws from one dollar-denominated credit balance. No subscription.

### AI Agent Tasks
- **V4** (current): token-based per model; see the model table in https://browser-use.com/pricing.md
- **V3**: Browser Use-hosted model at 1.2x provider token rates; BYOK = provider cost + 0.2x orchestration fee
- **V2** (legacy): $0.01/task init + from $0.006/step

### Browser Sessions
- $0.02 per browser-hour, metered per minute, 1-minute minimum (partial minutes round up)
- Credits for the requested timeout are reserved at creation; unused credits are returned when the browser ends

### Skills
- Retired: existing skills still run, new skills can no longer be created. Use rerunnable scripts instead.

### Proxies
- Managed residential proxy: $5/GB
- Direct connection or your own proxy: $0.20/GB

### Plans
- Pay as you go, no subscription. Eligible Google, GitHub or Microsoft signups get a one-time $1 credit.
- Concurrency grows with total paid: 10 at $0, 50 at $100, 250 at $1,000, 500 at $5,000, 1,000 at $25,000.
- Accounts that still hold a legacy subscription can manage or cancel it from the Cloud billing page.
- **Enterprise**: Contact for ZDR, compliance, on-prem

Current prices: https://browser-use.com/pricing.md

---

## FAQ & Troubleshooting

**Slow tasks?**
- Switch models (Browser Use LLM is fastest)
- Set `start_url` to skip navigation
- Use closer proxy country

**Agent failed?**
- Check `liveUrl` to see what happened
- Simplify instructions
- Set `start_url`

**Login issues?**
- Profile sync (easiest): `curl -fsSL https://browser-use.com/profile.sh | sh`
- Secrets (per-domain credentials)
- 1Password (most secure, auto 2FA)

**Blocked by site?**
- Stealth is on by default
- Try different proxy country
- Set `flash_mode=False` (slower but more careful)

**Rate limited?**
- Auto-retry with backoff
- Top up to reach a higher concurrency tier, or contact sales for more

**Stop a session:**
```bash
curl -X PATCH https://api.browser-use.com/api/v2/sessions/<id> \
     -H "X-Browser-Use-API-Key: $BROWSER_USE_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{"action": "stop"}'
```
