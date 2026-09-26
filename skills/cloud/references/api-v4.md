# API v4: Hosted Agent Runs

Use v4 for new hosted-agent integrations. A **run** is one agent turn, a
**session** is the conversation shared by follow-up runs, and a **workspace**
is the persistent filesystem that can be reused across sessions.

- REST base: `https://api.browser-use.com/api/v4`
- Auth header: `X-Browser-Use-API-Key: <key>`
- Python: `from browser_use_sdk.v4 import BrowserUse`
- TypeScript: `import { BrowserUse } from "browser-use-sdk/v4"`

## Choosing the product surface and model

Choose the execution model first; an API version and an LLM model are separate choices.

| What you need | Start here |
| --- | --- |
| Send a task and receive a result; Browser Use runs the agent | V4 hosted runs in this guide |
| Keep your existing agent and model provider; rent the browser | V4 `browsers` or [direct CDP access](browser-api.md) |
| Write and run a Python agent yourself | The open-source `browser-use` library, optionally with `Browser(use_cloud=True)` |
| Maintain an existing V2 or V3 integration | Its versioned reference until you have checked feature parity and tested migration |

**BYOK and custom endpoints are different capabilities.** BYOK supplies credentials for a supported provider. It does not by itself mean that a hosted run supports an arbitrary base URL, Azure deployment, or OpenAI-compatible endpoint. When your own agent controls model calls, configure the provider in that agent's model client; Browser Use supplies the remote browser. Check the hosted API's documented options before promising the same configuration for a V4 run.

Copy the exact model identifier from the selected surface. Cloud UI aliases, `ChatBrowserUse` model names, and provider model identifiers are not interchangeable. For a first V4 run, use the documented default (`gpt-5.6-luna`).

**Before migrating:** check structured-output requirements, custom tools/provider options, profiles, session reuse, downloads, and terminal status handling against the destination API. V4 returns a result string: a prompt requesting JSON does not enforce a JSON schema. Parse and validate the result in your application, and decide how validation failure should be handled before replacing an integration that relies on server-enforced schemas.

Compare a small representative task set using the same inputs and success criteria. Record the SDK version, API surface, exact model, browser/profile mode, elapsed time, cost, and terminal result. Changing API versions alone does not establish that a blocked site will become reachable.

## Before the first run

Eligible new Google, GitHub, or Microsoft signups receive a one-time $15 Cloud credit. No credit card is required. Email/password signups are not eligible; the credit does not renew. Start with the default V4 model (`gpt-5.6-luna`); paid-only models require a top-up. See [pricing](https://browser-use.com/pricing.md) for current eligibility and rates.

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
