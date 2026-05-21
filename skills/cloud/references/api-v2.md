# Cloud API v2 (Stable)

Full-featured REST API for tasks, sessions, browsers, profiles, skills, and marketplace.

## Table of Contents
- [Authentication](#authentication)
- [Common cURL Examples](#common-curl-examples)
- [Tasks](#tasks)
- [Sessions](#sessions)
- [Browsers (CDP)](#browsers-cdp)
- [Files](#files)
- [Profiles](#profiles)
- [Skills](#skills)
- [Marketplace](#marketplace)
- [Billing](#billing)
- [Pagination](#pagination)
- [Enums](#enums)
- [Response Schemas](#response-schemas)

---

## Authentication

- **Header:** `X-Browser-Use-API-Key: <your-key>`
- **Base URL:** `https://api.browser-use.com/api/v2`
- **Get key:** https://cloud.browser-use.com/new-api-key

All endpoints require the `X-Browser-Use-API-Key` header.

## Common cURL Examples

### Create a task

```bash
curl -X POST https://api.browser-use.com/api/v2/tasks \
  -H "X-Browser-Use-API-Key: $BROWSER_USE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"task": "Find the top Hacker News post and return title and URL"}'
```

Response: `{"id": "<task-id>", "sessionId": "<session-id>"}`

### Poll task status

```bash
curl https://api.browser-use.com/api/v2/tasks/<task-id>/status \
  -H "X-Browser-Use-API-Key: $BROWSER_USE_API_KEY"
```

### Get session live URL

```bash
curl https://api.browser-use.com/api/v2/sessions/<session-id> \
  -H "X-Browser-Use-API-Key: $BROWSER_USE_API_KEY"
```

Response includes `liveUrl` — open it to watch the agent work.

### Create a CDP browser

```bash
curl -X POST https://api.browser-use.com/api/v2/browsers \
  -H "X-Browser-Use-API-Key: $BROWSER_USE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"proxyCountryCode": "us", "timeout": 30}'
```

Response includes `cdpUrl` (WebSocket) and `liveUrl`.

### Stop a session

```bash
curl -X PATCH https://api.browser-use.com/api/v2/sessions/<session-id> \
  -H "X-Browser-Use-API-Key: $BROWSER_USE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"action": "stop"}'
```

### Upload a file to a session

```bash
# 1. Get presigned URL
curl -X POST https://api.browser-use.com/api/v2/files/sessions/<session-id>/presigned-url \
  -H "X-Browser-Use-API-Key: $BROWSER_USE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"fileName": "input.pdf", "contentType": "application/pdf", "sizeBytes": 102400}'

# 2. Upload via multipart POST using the returned URL and ALL returned fields (S3-style presigned POST)
# Include every key-value pair from the response's `fields` object as form fields:
curl -X POST "<presigned-url>" \
  -F "key=<fields.key>" \
  -F "policy=<fields.policy>" \
  -F "x-amz-algorithm=<fields.x-amz-algorithm>" \
  -F "x-amz-credential=<fields.x-amz-credential>" \
  -F "x-amz-date=<fields.x-amz-date>" \
  -F "x-amz-signature=<fields.x-amz-signature>" \
  -F "Content-Type=application/pdf" \
  -F "file=@input.pdf"
```

The v2 presigned URL response includes `fields` for a multipart POST form upload (S3-style). **Include all returned fields** as form fields — they contain the signing data. Presigned URLs expire after **120 seconds**. Max file size: **10 MB**.

---

## Tasks

**GET /tasks** — Paginated list with filtering.
Query: `pageSize?`, `pageNumber?`, `sessionId?` (uuid), `filterBy?` (TaskStatus), `after?` (datetime), `before?` (datetime)
Response: `{ items: TaskItemView[], totalItems, pageNumber, pageSize }`

**POST /tasks** — Create and run a task. Auto-creates session or uses existing.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| task | string | **yes** | Task prompt (1-50,000 chars) |
| llm | SupportedLLMs | no | Model (default: browser-use-llm) |
| startUrl | string | no | Initial URL (saves steps) |
| maxSteps | integer | no | Max agent steps (default: 100) |
| structuredOutput | string | no | JSON schema string |
| sessionId | uuid | no | Run in existing session |
| metadata | object | no | Key-value metadata (string values) |
| secrets | object | no | Domain-scoped credentials (string values) |
| allowedDomains | string[] | no | Restrict navigation |
| opVaultId | string | no | 1Password vault ID |
| highlightElements | boolean | no | Highlight interactive elements |
| flashMode | boolean | no | Fast mode (skip evaluation/thinking) |
| thinking | boolean | no | Extended reasoning |
| vision | boolean\|"auto" | no | Screenshot mode |
| systemPromptExtension | string | no | Append to system prompt |
| judge | boolean | no | Enable quality judge |
| skillIds | string[] | no | Skills to use during task |

Response (202): `{ id: uuid, sessionId: uuid }`
Errors: 400 (session busy/stopped), 404 (session not found), 422 (validation), 429 (rate limit)

**GET /tasks/{task_id}** — Detailed task info with steps and output files.
Response: TaskView

**GET /tasks/{task_id}/status** — Poll task status (lighter than full GET).
Response: `{ status: TaskStatus }`

**PATCH /tasks/{task_id}** — Control task execution.
Body: `{ action: TaskUpdateAction }` — `stop`, `pause`, `resume`, or `stop_task_and_session`
Response: TaskView. Errors: 404, 422.

**GET /tasks/{task_id}/logs** — Download URL for execution logs.
Response: `{ downloadUrl: string }`. Errors: 404, 500.

---

## Sessions

**GET /sessions** — Paginated list.
Query: `pageSize?`, `pageNumber?`, `filterBy?` (SessionStatus)

**POST /sessions** — Create a session.
Body: `{ profileId?: uuid, proxyCountryCode?: string, startUrl?: string }`
Response (201): SessionItemView. Errors: 404 (profile not found), 429 (too many concurrent).

**GET /sessions/{id}** — Session details with tasks and share URL.
Response: SessionView

**PATCH /sessions/{id}** — Stop session and all running tasks.
Body: `{ action: "stop" }`. Errors: 404, 422.

**POST /sessions/{id}/purge** — Purge session data.
Response: 200.

**GET /sessions/{id}/public-share** — Get share info.
Response: ShareView. Errors: 404.

**POST /sessions/{id}/public-share** — Create or return existing share.
Response (201): ShareView.

**DELETE /sessions/{id}/public-share** — Remove share.
Response: 204.

---

## Browsers (CDP)

**POST /browsers** — Create a CDP browser session.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| profileId | uuid | no | Browser profile |
| proxyCountryCode | string | no | Residential proxy (195+ countries) |
| timeout | integer | no | Session timeout in minutes (max 240) |
| browserScreenWidth | integer | no | Browser width in pixels |
| browserScreenHeight | integer | no | Browser height in pixels |
| customProxy | object | no | `{ host, port, username?, password? }` (HTTP or SOCKS5) |

**Pricing:** $0.05/hour. Billed upfront, proportional refund on stop. Ceil to nearest minute (min 1 min). Free: 15 min max. Paid: 4 hours max.

Response (201): BrowserSessionItemView (includes `cdpUrl` and `liveUrl`).
Errors: 403 (timeout exceeded for free), 404 (profile not found), 429 (too many concurrent).

**GET /browsers/{id}** — Browser session details.

**PATCH /browsers/{id}** — Stop browser (unused time refunded).
Body: `{ action: "stop" }`

---

## Files

**POST /files/sessions/{id}/presigned-url** — Get upload URL for session files.
Body: `{ fileName: string, contentType: UploadContentType, sizeBytes: integer }`
Response: `{ url: string, method: "POST", fields: {}, fileName: string, expiresIn: integer }`
Errors: 400 (unsupported type), 404, 500.

**POST /files/browsers/{id}/presigned-url** — Same for browser sessions.

**GET /files/tasks/{task_id}/output-files/{file_id}** — Download URL for task output.
Response: `{ id: uuid, fileName: string, downloadUrl: string }`
Errors: 404, 500.

**Upload flow:** Get presigned URL → POST multipart form with returned `fields` + file → URL expires in 120s → Max 10 MB.

---

## Profiles

**GET /profiles** — Paginated list. Query: `pageSize?`, `pageNumber?`

**POST /profiles** — Create profile (persistent cookies/localStorage between tasks).
Body: `{ name?: string }`. Response (201): ProfileView. Error: 402 (subscription needed).

**GET /profiles/{id}** — Profile details.

**DELETE /profiles/{id}** — Permanently delete. Response: 204.

**PATCH /profiles/{id}** — Update name. Body: `{ name?: string }`

---

## Skills

**POST /skills** — Create a skill (turn a website into an API endpoint).
Body: `{ goal: string, agent_prompt: string, ... }`
Response: SkillView.

**GET /skills** — List all skills.

**GET /skills/{id}** — Get skill details.

**POST /skills/{id}/execute** — Execute a skill.
Body: `{ parameters: {} }`

**POST /skills/{id}/refine** — Refine with feedback (free).
Body: `{ feedback: string }`

**POST /skills/{id}/cancel** — Cancel skill training.

**POST /skills/{id}/rollback** — Rollback to previous version.

**GET /skills/{id}/executions** — List skill executions.

**GET /skills/{id}/executions/{eid}/output** — Get execution output.

---

## Marketplace

**GET /marketplace/skills** — Browse community skills.

**GET /marketplace/skills/{slug}** — Get marketplace skill details.

**POST /marketplace/skills/{id}/clone** — Clone skill to your workspace.

**POST /marketplace/skills/{id}/execute** — Execute a marketplace skill.
Body: `{ parameters: {} }`

---

## Billing

**GET /billing/account** — Account info and credits.
Response: `{ name?, monthlyCreditsBalanceUsd, additionalCreditsBalanceUsd, totalCreditsBalanceUsd, rateLimit, planInfo: { planName, subscriptionStatus?, subscriptionId?, subscriptionCurrentPeriodEnd?, subscriptionCanceledAt? }, projectId }`

---

## Pagination

All list endpoints use page-based pagination:

| Param | Type | Description |
|-------|------|-------------|
| pageSize | integer | Items per page |
| pageNumber | integer | Page number (1-based) |

Response includes: `{ items: [...], totalItems, pageNumber, pageSize }`

---

## Enums

| Enum | Values |
|------|--------|
| TaskStatus | `started`, `paused`, `finished`, `stopped` |
| TaskUpdateAction | `stop`, `pause`, `resume`, `stop_task_and_session` |
| SessionStatus | `active`, `stopped` |
| BrowserSessionStatus | `active`, `stopped` |
| ProxyCountryCode | `us`, `uk`, `fr`, `it`, `jp`, `au`, `de`, `fi`, `ca`, `in` (+185 more) |
| SupportedLLMs | `browser-use-llm`, `gpt-4.1`, `gpt-4.1-mini`, `o4-mini`, `o3`, `gemini-2.5-flash`, `gemini-2.5-pro`, `gemini-flash-latest`, `gemini-flash-lite-latest`, `claude-sonnet-4-20250514`, `gpt-4o`, `gpt-4o-mini`, `llama-4-maverick-17b-128e-instruct`, `claude-3-7-sonnet-20250219` |
| UploadContentType | `image/jpg`, `image/jpeg`, `image/png`, `image/gif`, `image/webp`, `image/svg+xml`, `application/pdf`, `application/msword`, `application/vnd.openxmlformats-officedocument.wordprocessingml.document`, `application/vnd.ms-excel`, `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`, `text/plain`, `text/csv`, `text/markdown` |

## Response Schemas

**TaskItemView:** id, sessionId, llm, task, status, startedAt, finishedAt?, metadata?, output?, browserUseVersion?, isSuccess?

**TaskView:** extends TaskItemView + steps: TaskStepView[], outputFiles: FileView[]

**TaskStepView:** number, memory, evaluationPreviousGoal, nextGoal, url, screenshotUrl?, actions: string[]

**FileView:** id, fileName

**SessionItemView:** id, status, liveUrl?, startedAt, finishedAt?

**SessionView:** extends SessionItemView + tasks: TaskItemView[], publicShareUrl?

**BrowserSessionItemView:** id, status, liveUrl?, cdpUrl?, timeoutAt, startedAt, finishedAt?

**ProfileView:** id, name?, lastUsedAt?, createdAt, updatedAt, cookieDomains?: string[]

**ShareView:** shareToken, shareUrl, viewCount, lastViewedAt?

**AccountView:** name?, monthlyCreditsBalanceUsd, additionalCreditsBalanceUsd, totalCreditsBalanceUsd, rateLimit, planInfo, projectId
