# BU Agent API (v3 — Experimental)

Next-generation agent API. Session-based, token-based billing, workspaces, message history.

## Table of Contents
- [Authentication](#authentication)
- [SDK Setup](#sdk-setup)
- [run() — Execute a Task](#run--execute-a-task)
- [REST Endpoints](#rest-endpoints)
- [Sessions](#sessions)
- [Messages](#messages)
- [Files](#files)
- [Workspaces](#workspaces)
- [Polling & Terminal Statuses](#polling--terminal-statuses)
- [Error Handling](#error-handling)
- [Session Statuses & Enums](#session-statuses--enums)
- [Response Schemas](#response-schemas)

---

## Authentication

- **Header:** `X-Browser-Use-API-Key: <your-key>`
- **Base URL:** `https://api.browser-use.com/api/v3`
- **Get key:** https://cloud.browser-use.com/new-api-key

Same package as v2, different import path:

## SDK Setup

```python
# Python (async — recommended)
from browser_use_sdk.v3 import AsyncBrowserUse
client = AsyncBrowserUse()  # Uses BROWSER_USE_API_KEY env var

# Python (sync)
from browser_use_sdk.v3 import BrowserUse
client = BrowserUse()
```

```typescript
// TypeScript
import { BrowserUse } from "browser-use-sdk/v3";
const client = new BrowserUse();
```

Constructor: `api_key`, `base_url`, `timeout` (HTTP request timeout, not polling).

## run() — Execute a Task

```python
result = await client.run("Find the top HN post")
print(result.output)    # str
print(result.id)        # session UUID
print(result.status)    # e.g. "idle"
print(result.total_cost_usd)  # cost breakdown
```

### Parameters

| Param | Type | Description |
|-------|------|-------------|
| task | string | **Required.** What to do. |
| model | string | `"bu-mini"` (default, faster/cheaper) or `"bu-max"` (more capable) |
| output_schema | Pydantic/Zod | Structured output schema |
| session_id | string | Reuse existing session |
| keep_alive | boolean | Keep session idle after task (default: false) |
| max_cost_usd | float | Cost cap in USD; agent stops if exceeded |
| profile_id | string | Browser profile UUID |
| proxy_country_code | string | Residential proxy country (195+ countries) |
| workspace_id | string | Attach workspace for file I/O |

### Structured Output

```python
from pydantic import BaseModel

class Product(BaseModel):
    name: str
    price: float

result = await client.run("Get product info", output_schema=Product)
print(result.output)  # Product instance
```

### SessionResult Fields

| Field | Type | Description |
|-------|------|-------------|
| output | str / BaseModel | Task result (typed if schema provided) |
| id | uuid | Session ID |
| status | string | Session status |
| model | string | bu-mini or bu-max |
| title | string? | Auto-generated title |
| live_url | string | Real-time browser monitoring URL |
| profile_id | string? | Echo of request |
| proxy_country_code | string? | Echo of request |
| max_cost_usd | float? | Echo of request |
| total_input_tokens | int | Input tokens used |
| total_output_tokens | int | Output tokens used |
| llm_cost_usd | string | LLM cost |
| proxy_cost_usd | string | Proxy cost |
| proxy_used_mb | string | Proxy data used |
| total_cost_usd | string | Total cost |
| created_at | datetime | Session creation time |
| updated_at | datetime | Last update time |

---

## REST Endpoints

All 16 endpoints in the v3 API:

### Sessions

**POST /sessions** — Create session and/or dispatch task.
Body: `{ task?, model?, session_id?, keep_alive?, max_cost_usd?, profile_id?, proxy_country_code?, output_schema? (JSON Schema dict) }`
Response: SessionView

**GET /sessions** — List sessions.
Query: `page?` (int), `page_size?` (int)
Response: `{ sessions: SessionView[], total, page, page_size }`

**GET /sessions/{id}** — Get session details (includes cost breakdown).
Response: SessionView

**DELETE /sessions/{id}** — Delete session.
Response: 204

**POST /sessions/{id}/stop** — Stop session or task.
Query: `strategy?` — `"session"` (default, destroy sandbox) or `"task"` (stop task only, keep session alive)
Response: 200

### Messages

**GET /sessions/{id}/messages** — Cursor-paginated message history.

| Param | Type | Description |
|-------|------|-------------|
| limit | int | Max messages per page (default 50, max 100) |
| after | string | Cursor for forward pagination |
| before | string | Cursor for backward pagination |

Response: `{ messages: [{ id, role: "user"|"assistant", data: string, timestamp }], next_cursor?, has_more: boolean }`

### Files

**GET /sessions/{id}/files** — List files in session workspace.

| Param | Type | Description |
|-------|------|-------------|
| include_urls | boolean | Include presigned download URLs (60s expiry) |
| prefix | string | Filter by path prefix (e.g. `"outputs/"`) |
| limit | int | Max per page (default 50, max 100) |
| cursor | string | Pagination cursor |

Response: `{ files: [{ path, size, last_modified, url? }], next_cursor?, has_more }`

**POST /sessions/{id}/files/upload** — Get presigned upload URLs.
Body: `{ files: [{ name: string, content_type: string }] }`
Response: `{ files: [{ name, upload_url, path }] }`

Upload via **PUT** to `upload_url` with matching `Content-Type` header. Max **10 files** per batch. Presigned URLs expire in **120 seconds**. Max file size: **10 MB**.

### Workspaces

**POST /workspaces** — Create persistent workspace.
Body: `{ name?: string, metadata?: object }`
Response: WorkspaceView

**GET /workspaces** — List workspaces.
Query: `page?`, `page_size?`
Response: `{ items: WorkspaceView[], total, page, page_size }`

**GET /workspaces/{id}** — Get workspace details.

**PATCH /workspaces/{id}** — Update workspace.
Body: `{ name?: string, metadata?: object }`

**DELETE /workspaces/{id}** — Delete workspace and all files (irreversible).

**GET /workspaces/{id}/files** — List workspace files.
Query: `include_urls?`, `prefix?`, `limit?`, `cursor?`
Response: same format as session files

**GET /workspaces/{id}/size** — Storage usage.
Response: `{ size_bytes: int, quota_bytes: int }`

**POST /workspaces/{id}/files/upload** — Upload files to workspace.
Same format as session file upload.

---

## Polling & Terminal Statuses

`run()` polls automatically:
- **Interval:** 2 seconds
- **Timeout:** 300 seconds (5 minutes) — raises `TimeoutError` if exceeded
- **Terminal statuses:** `idle`, `stopped`, `timed_out`, `error`

### Stop Strategies

| Strategy | Behavior |
|----------|----------|
| `"session"` (default) | Destroy sandbox completely |
| `"task"` | Stop current task, keep session alive for follow-ups |

```python
await client.sessions.stop(session_id, strategy="task")   # keep session
await client.sessions.stop(session_id, strategy="session") # destroy
```

---

## Error Handling

```python
from browser_use_sdk.v3 import AsyncBrowserUse, BrowserUseError

try:
    result = await client.run("Do something")
except TimeoutError:
    print("Polling timed out (5 min default)")
except BrowserUseError as e:
    print(f"API error: {e}")
```

---

## Session Statuses & Enums

| Status | Description |
|--------|-------------|
| `created` | Session created, not yet running |
| `idle` | Task completed, session still alive (keep_alive=True) |
| `running` | Task in progress |
| `stopped` | Manually stopped |
| `timed_out` | Session timed out |
| `error` | Session errored |

**Models:** `bu-mini` (default, faster/cheaper), `bu-max` (more capable)

## Response Schemas

**SessionView (v3):** id, status, model, title?, live_url, output?, profile_id?, proxy_country_code?, max_cost_usd?, total_input_tokens, total_output_tokens, llm_cost_usd, proxy_cost_usd, proxy_used_mb, total_cost_usd, created_at, updated_at

**MessageView:** id, role ("user"|"assistant"), data (string), timestamp

**FileInfo:** path, size, last_modified, url?

**WorkspaceView:** id, name?, metadata?, created_at, updated_at, size_bytes?

**Key concepts:**
- **Autonomous execution** — agent decides how many steps (no max_steps param)
- **Cost control** — `max_cost_usd` caps spending; check `total_cost_usd` on result
- **Integrations** — agent auto-discovers third-party services (email, Slack, calendars)
- **File I/O** — upload before task, download from workspace after. Max 10 files per batch, download URLs expire in 60s
