# Cloud Patterns & Tutorials

## Table of Contents
- [Parallel Execution](#parallel-execution)
- [Streaming Steps](#streaming-steps)
- [Geo-Scraping](#geo-scraping)
- [File Downloads](#file-downloads)
- [Structured Output](#structured-output)
- [Tutorials](#tutorials)

---

## Parallel Execution

### Concurrent Extraction

Each `run()` auto-creates its own session — no manual management:

```python
import asyncio

async def extract(query: str):
    return await client.run(f"Search for '{query}' and extract top 3 results")

results = await asyncio.gather(
    extract("AI startups"),
    extract("climate tech"),
    extract("quantum computing"),
)
```

### Shared Config (Same Profile + Proxy)

For authenticated concurrent tasks:

```python
sessions = [
    await client.sessions.create(profile_id="uuid", proxy_country_code="us")
    for _ in range(3)
]

tasks = [
    client.run(f"Task {i}", session_id=s.id)
    for i, s in enumerate(sessions)
]
results = await asyncio.gather(*tasks)

for s in sessions:
    await client.sessions.stop(s.id)
```

**Warning:** Concurrent sessions read profile state from snapshot at start — they won't see each other's changes. Works for read-heavy tasks, not state-modifying.

---

## Streaming Steps

Stream agent progress in real-time:

```python
async for step in client.run("Find top HN post", stream=True):
    print(f"Step {step.number}: {step.next_goal} (URL: {step.url})")
```

Returns step number, next goal, and current URL per step.

---

## Geo-Scraping

Location-dependent content via residential proxies:

```python
from pydantic import BaseModel

class Pricing(BaseModel):
    product: str
    price: str
    currency: str

# Japan pricing
result = await client.run(
    "Get iPhone 16 Pro price from Apple Japan",
    output_schema=Pricing,
    session_settings={"proxy_country_code": "jp"},
)
print(result.output)  # Pricing(product="iPhone 16 Pro", price="159,800", currency="JPY")
```

195+ countries available. Combine with structured output for typed comparison.

---

## File Downloads

Retrieve files downloaded during tasks:

```python
# Run task that downloads files
result = await client.run("Download the Q4 report PDF from example.com")

# Get task details with output files
task = await client.tasks.get(result.id)

for file in task.output_files:
    output = await client.files.task_output(task.id, file.id)
    # output.download_url — presigned URL, download promptly (expires quickly)
```

For uploads: use presigned URLs (10 MB max, 120s expiry):

```python
url_info = await client.files.session_url(
    session_id,
    file_name="input.pdf",
    content_type="application/pdf",
    size_bytes=1024,
)
# Upload to url_info.url with url_info.fields
```

---

## Structured Output

Extract typed data with Pydantic (Python) or Zod (TypeScript):

```python
from pydantic import BaseModel

class Company(BaseModel):
    name: str
    founded: int
    ceo: str
    revenue: str

result = await client.run(
    "Find information about OpenAI",
    output_schema=Company,
)
print(result.output)  # Company instance
```

**Tips:**
- Keep schemas flat — nesting adds complexity
- Typical task: 8-12 steps with Browser Use 2.0

---

## Tutorials

### Chat UI (Next.js)

Full-stack chat interface with real-time session monitoring. Uses v3 + v2 SDKs.
- Source: [github.com/browser-use/chat-ui-example](https://github.com/browser-use/chat-ui-example)
- Pattern: Create idle session → navigate → fire-and-forget task → poll messages → embed liveUrl

### n8n Integration

HTTP Request nodes (no custom nodes needed):
1. POST `/api/v2/tasks` to create task
2. Poll GET `/api/v2/tasks/{id}` until done
3. Or use webhooks for event-driven workflows

Works with Make, Zapier, Pipedream, and custom orchestrators.

### OpenClaw (WhatsApp/Telegram/Discord)

Self-hosted AI gateway. Two options:
1. **Cloud browser via CDP**: Configure `cdpUrl` with query params in openclaw.json
2. **CLI as skill**: `npx skills add` — agents learn CLI commands

### Playwright Integration

Connect Playwright to cloud stealth browser:
```python
browser = await client.browsers.create(proxy_country_code="us")
pw_browser = await playwright.chromium.connect_over_cdp(browser.cdp_url)
# Normal Playwright code on stealth infrastructure
```

See `references/cloud/browser-api.md` for full examples.
