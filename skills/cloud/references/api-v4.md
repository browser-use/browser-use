# API v4: Hosted Agent Runs

Use v4 for new hosted-agent integrations. A **run** is one agent turn, a
**session** is the conversation shared by follow-up runs, and a **workspace**
is the persistent filesystem that can be reused across sessions.

- REST base: `https://api.browser-use.com/api/v4`
- Auth header: `X-Browser-Use-API-Key: <key>`
- Python: `from browser_use_sdk.v4 import BrowserUse`
- TypeScript: `import { BrowserUse } from "browser-use-sdk/v4"`

## First Run

### Python

```python
from browser_use_sdk.v4 import BrowserUse

with BrowserUse() as client:
    created = client.runs.create("Find the top Hacker News story")
    run = client.runs.wait_for_completion(created.id)
    print(run.result)
```

### TypeScript

```typescript
import { BrowserUse } from "browser-use-sdk/v4";

const client = new BrowserUse();
const created = await client.runs.create({
  task: "Find the top Hacker News story",
});
const run = await client.runs.waitForCompletion(created.id);
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

Closing a CDP client does not stop the cloud browser or its billing. The
browser-management SDK wrapper currently uses the explicit v3 namespace; use
`browser_use_sdk.v3` or `browser-use-sdk/v3` for that resource, or call the v4
REST endpoint directly.

## Resource Map

| Resource | Common operations |
|----------|-------------------|
| Runs | create, list, get, status, events, cancel, attachments |
| Sessions | list, get, queue messages, inspect/remove queued messages, purge |
| Workspaces | create, get, update, archive, size, upload/list/delete files |
| Browsers (REST) | create, inspect, stop |

For the complete current contract, use:

- Docs: https://docs.browser-use.com/cloud/api-v4
- OpenAPI: https://docs.browser-use.com/cloud/openapi/v4.json
