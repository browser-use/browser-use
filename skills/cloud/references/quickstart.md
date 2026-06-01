# Cloud Quickstart, Pricing & FAQ

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

### AI Agent Tasks
$0.01 init + per-step (varies by model):

| Model | Per Step |
|-------|---------|
| Browser Use LLM | $0.002 |
| Browser Use 2.0 | $0.006 |
| Gemini Flash Lite | $0.005 |
| GPT-4.1 Mini | $0.004 |
| O3 | $0.03 |
| Claude Sonnet 4.6 | $0.05 |

Typical task: 10 steps = ~$0.03 (with Browser Use LLM)

### V3 API (Token-Based)
| Model | Input/1M | Output/1M |
|-------|---------|----------|
| BU Mini (Gemini 3 Flash) | ~$0.72 | ~$4.20 |
| BU Max (Claude Sonnet 4.6) | ~$3.60 | ~$18.00 |

### Browser Sessions
- PAYG: $0.06/hour
- Business: $0.03/hour
- Billed upfront, proportional refund on stop. Min 1 minute.

### Skills
- Creation: $2 (PAYG), $1 (Business). Refinements free.
- Execution: $0.02 (PAYG), $0.01 (Business)

### Proxies
- PAYG: $10/GB, Business: $5/GB, Scaleup: $4/GB

### Tiers
- **Business**: 25% off per-step, 50% off sessions/skills/proxy
- **Scaleup**: 50% off per-step, 60% off proxy
- **Enterprise**: Contact for ZDR, compliance, on-prem

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
- Upgrade plan if consistent

**Stop a session:**
```bash
curl -X PATCH https://api.browser-use.com/api/v2/sessions/<id> \
     -H "X-Browser-Use-API-Key: $BROWSER_USE_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{"action": "stop"}'
```
