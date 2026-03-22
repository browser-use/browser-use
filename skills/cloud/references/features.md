# Cloud Features

## Table of Contents
- [Proxies & Stealth](#proxies--stealth)
- [Webhooks](#webhooks)
- [Workspaces](#workspaces)
- [Skills](#skills)
- [MCP Server](#mcp-server)
- [Live View](#live-view)

---

## Proxies & Stealth

Stealth is on by default — anti-fingerprinting, CAPTCHA solving, ad/cookie blocking, Cloudflare bypass.

### Residential Proxies (195+ Countries)

Default: US residential proxy always active.

```python
# Common countries
session = await client.sessions.create(proxy_country_code="us")  # or gb, de, fr, jp, au, br, in, kr, ca, es, it, nl, se, sg...
```

### Custom Proxy (HTTP or SOCKS5)

```python
from browser_use_sdk import CustomProxy

session = await client.sessions.create(
    custom_proxy=CustomProxy(
        url="http://proxy-host:8080",
        username="user",
        password="pass",
    )
)
```

### Disable Proxy (Not Recommended)

```python
session = await client.sessions.create(proxy_country_code=None)
```

---

## Webhooks

Real-time notifications when tasks complete.

### Events

| Event | Description |
|-------|-------------|
| `agent.task.status_update` | Task status changed (started/finished/stopped) |
| `test` | Test webhook delivery |

### Payload

```json
{
  "type": "agent.task.status_update",
  "timestamp": "2025-01-15T10:30:00Z",
  "payload": {
    "task_id": "task_abc123",
    "session_id": "session_xyz",
    "status": "finished",
    "metadata": {}
  }
}
```

### Signature Verification (HMAC-SHA256)

Headers: `X-Browser-Use-Signature`, `X-Browser-Use-Timestamp`

The signature is computed over `{timestamp}.{body}` where body is JSON with sorted keys and no extra whitespace. Reject requests older than 5 minutes to prevent replay attacks.

```python
import hmac, hashlib, json, time

def verify_webhook(body: bytes, signature: str, timestamp: str, secret: str) -> bool:
    # Reject requests older than 5 minutes
    try:
        ts = int(timestamp)
    except (ValueError, TypeError):
        return False
    if abs(time.time() - ts) > 300:
        return False
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return False
    message = f"{timestamp}.{json.dumps(payload, separators=(',', ':'), sort_keys=True)}"
    expected = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
```

---

## Workspaces

Persistent file storage across sessions (v3 API). Max 10 files per upload.

```python
from browser_use_sdk.v3 import AsyncBrowserUse
client = AsyncBrowserUse()

# Create workspace
workspace = await client.workspaces.create(name="my-data")

# Create a session
session = await client.sessions.create()

# Upload files before task
await client.sessions.upload_files(
    session.id,
    workspace_id=workspace.id,
    files=[open("input.pdf", "rb")]
)

# Download files after task
files = await client.sessions.files(session.id)
for f in files:
    url = f.download_url  # Presigned URL (60s expiry)

# Manage workspaces
workspaces = await client.workspaces.list()
await client.workspaces.delete(workspace.id)
```

---

## Skills

Turn website interactions into reusable, deterministic API endpoints.

### Anatomy

- **Goal**: Full spec with parameters and return data
- **Demonstration**: agent_prompt showing how to perform the task once

### Create & Execute

```python
# Create (~30s, $2 PAYG)
skill = await client.skills.create(
    goal="Extract product price from Amazon",
    demonstration="Navigate to product page, find price element..."
)

# Execute ($0.02 PAYG)
result = await client.skills.execute(skill.id, params={"url": "https://amazon.com/dp/..."})

# Refine (free)
await client.skills.refine(skill.id, feedback="Also extract the rating")
```

### Marketplace

```python
skills = await client.marketplace.list()
cloned = await client.marketplace.clone(skill_id)
result = await client.marketplace.execute(skill_id, params={})
```

Browse at [cloud.browser-use.com/skills](https://cloud.browser-use.com/skills).

### Load Skills in Local Agent

```python
agent = Agent(
    task="...",
    skills=['skill-uuid-1', 'skill-uuid-2'],  # or ['*'] for all
    llm=ChatBrowserUse()
)
```

---

## MCP Server

HTTP-based MCP at `https://api.browser-use.com/mcp`

| Tool | Cost | Description |
|------|------|-------------|
| `browser_task` | $0.01 + per-step | Run automation task |
| `execute_skill` | $0.02 | Execute skill |
| `list_skills` | Free | List skills |
| `get_cookies` | Free | Get cookies |
| `list_browser_profiles` | Free | List profiles |
| `monitor_task` | Free | Check task progress |

Setup: See `references/open-source/integrations.md` for Claude/Cursor/Windsurf config.

---

## Live View

### Human Takeover

Pause agent, let human take over via `liveUrl`:

```python
session = await client.sessions.create(keep_alive=True)  # v3
await client.run("Navigate to checkout", session_id=session.id)
# Agent pauses at checkout

print(session.live_url)  # Human opens this, enters payment details

await client.run("Confirm the order", session_id=session.id)
await client.sessions.stop(session.id)
```

`liveUrl` gives full mouse/keyboard control.

### Iframe Embed

Embed live view in your app — no X-Frame-Options or CSP restrictions:

```html
<iframe
  src="{session.live_url}"
  width="1280"
  height="720"
  style="border: none;"
></iframe>
```

No polling needed — updates in real-time.
