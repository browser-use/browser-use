# API v4: Hosted Agent Runs

Use v4 for new hosted-agent integrations. A **run** is one agent turn, a
**session** is the conversation shared by follow-up runs, and a **workspace**
is the persistent filesystem that can be reused across sessions.

- REST base: `https://api.browser-use.com/api/v4`
- Auth header: `X-Browser-Use-API-Key: <key>`
- Python: `from browser_use_sdk.v4 import BrowserUse`
- TypeScript: `import { BrowserUse } from "browser-use-sdk/v4"`

## Low-cost modes

BU Ultrafast (`bu-ultrafast`) and BU Fast (`bu-fast`) are hosted V4 modes in early access, enabled per project. BU Ultrafast targets quick browser interactions; BU Fast adds more reasoning at low token prices. [Request access](https://browser-use.com/ultrafast).

BU Ultrafast recorded **$0.00214 median per URL check**, with **8/8 correct** in a small staging test. This includes recorded LLM + stopped-browser usage, with browsers explicitly stopped after each run. Actual cost varies; network traffic is billed separately. [Methodology](https://browser-use.com/pricing#task-cost-methodology).

Customer rates in USD per 1M tokens, including the service fee:

| Mode | Fresh input | Cached input | Cache write | Output |
| --- | ---: | ---: | ---: | ---: |
| BU Ultrafast | $0.24 | $0.024 | $0.30 | $1.20 |
| BU Fast | $0.12 | $0.012 | $0.15 | $0.60 |

Calls exceeding 272,000 prompt + cache-write tokens cost 2× input/cache and 1.5× output.

Browser and network usage and optional services add separate charges. These are token rates, not fixed task prices. A run's `totalCostUsd` is not an all-in bill: browser and proxy charges are recorded separately. Stop the owned browser when finished and check recorded session usage; late metering can change it.

Use REST while your installed SDK types lack these aliases. They are not V2/V3 aliases or `ChatBrowserUse` model IDs:

```bash
curl https://api.browser-use.com/api/v4/runs \
  -H "X-Browser-Use-API-Key: $BROWSER_USE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"task":"Find the top Hacker News story","model":"bu-ultrafast"}'
```

Replace `bu-ultrafast` with `bu-fast` for more reasoning. The presets do not accept `modelParams`. Account access still applies; projects without access receive 422, and the modes are unavailable on EU and Bedrock-only routes. See [current rates and availability](https://docs.browser-use.com/cloud/agent/models).

## Before the first run

Eligible new Google, GitHub, or Microsoft signups receive a one-time $15 Cloud credit. No credit card is required. Email/password signups are not eligible; the credit does not renew. Omit `model` for the API's default, or select an eligible model offered to the project. BU modes require early access; paid-only models require a top-up. See [pricing](https://browser-use.com/pricing.md) for current eligibility and rates.

Install or upgrade `browser-use-sdk` to 3.11.3 or newer. Read `BROWSER_USE_API_KEY` from the environment; do not embed it in source or a prompt.

## First Run

### Python

```python
from browser_use_sdk.v4 import BrowserUse

with BrowserUse() as client:
    created = client.runs.create(
        "Open https://example.com and return its title", max_cost_usd=1.00
    )
    run = client.runs.wait_for_completion(created.id)
    if run.status.value != "completed":
        raise RuntimeError(f"Run {run.id}: {run.status}")
    print(run.result)
```

### TypeScript

```typescript
import { BrowserUse } from "browser-use-sdk/v4";

const client = new BrowserUse();
const created = await client.runs.create({
  task: "Open https://example.com and return its title",
  maxCostUsd: 1.00,
});
const run = await client.runs.waitForCompletion(created.id);
if (run.status !== "completed") {
  throw new Error(`Run ${run.id}: ${run.status}`);
}
console.log(run.result);
```

### REST

Create the run, poll the lightweight status route, then fetch the full result
only after the status is `completed`, `failed`, or `cancelled`:

```bash
curl -X POST https://api.browser-use.com/api/v4/runs \
  -H "X-Browser-Use-API-Key: $BROWSER_USE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"task":"Find the top Hacker News story"}'

curl https://api.browser-use.com/api/v4/runs/RUN_ID/status \
  -H "X-Browser-Use-API-Key: $BROWSER_USE_API_KEY"

curl https://api.browser-use.com/api/v4/runs/RUN_ID \
  -H "X-Browser-Use-API-Key: $BROWSER_USE_API_KEY"
```

Only `completed` means success. V4 returns a result string; parse and validate it in your application. A polling timeout does not cancel the remote run: use `client.runs.cancel` if abandoning it. Do not blindly retry an ambiguous create request, which could start duplicate paid work.

Do not repeatedly poll the full run resource. The SDK wait helpers use the
status route and fetch the full run once at the end.

## Sessions and Follow-ups

Every new run implicitly creates a session. Reuse its session ID to continue
the same conversation:

```python
from browser_use_sdk.v4 import BrowserUse

with BrowserUse() as client:
    first = client.runs.create("Open Hacker News")
    client.runs.wait_for_completion(first.id)

    follow_up = client.runs.create(
        "Now summarize the top story",
        session_id=first.session_id,
    )
    result = client.runs.wait_for_completion(follow_up.id)
```

For a busy session, queue a next turn with
`client.sessions.send_message(session_id, text)`. Pass `interrupt=True` only
when the active run should be cancelled so the new message can start. The REST
equivalent is `POST /sessions/{session_id}/queue` with `text` and optional
`interrupt`.

## Workspaces and Files

A workspace persists files independently of a session. Upload a local file,
then attach its returned file ID to a run:

```python
from browser_use_sdk.v4 import BrowserUse

with BrowserUse() as client:
    workspace = client.workspaces.create(name="research")
    uploaded = client.workspaces.upload(workspace.id, "people.csv")

    run = client.runs.create(
        "Read the CSV and save a report",
        workspace_id=workspace.id,
        attached_file_ids=[uploaded[0].id],
    )
```

Attachments are run-scoped. Reusing a workspace does not automatically attach
every file in it. List generated files with `client.workspaces.files(workspace.id)`;
presigned download URLs expire after 60 seconds, so request them immediately
before downloading.

## Direct Browser Control

The v4 REST API can create a browser for direct CDP control:

1. `POST /browsers` returns the browser `id` (its session ID) and `cdpUrl`.
2. Connect Browser Use, Playwright, Puppeteer, or Selenium to `cdpUrl`.
3. `PATCH /browsers/{session_id}` with `{"action":"stop"}` stops the browser;
   replace `session_id` with the returned `id`.

Closing a CDP client does not stop the cloud browser or its billing. SDK
3.11.3 or newer exposes `client.browsers.create()` and
`client.browsers.stop(browser.id)` through `browser_use_sdk.v4` and
`browser-use-sdk/v4`. Put the explicit stop in a `finally` block so failures
also clean up the browser. Existing V3 integrations can keep their imports.

## Resource Map

| Resource | Common operations |
|----------|-------------------|
| Runs | create, list, get, status, events, cancel, attachments |
| Sessions | list, get, queue messages, inspect/remove queued messages, purge |
| Workspaces | create, get, update, archive, size, upload/list/delete files |
| Browsers | SDK: create, stop; REST: create, inspect, stop |

For the complete current contract, use:

- Docs: https://docs.browser-use.com/cloud/api-v4
- OpenAPI: https://docs.browser-use.com/cloud/openapi/v4.json
