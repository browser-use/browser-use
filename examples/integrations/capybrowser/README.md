# Baizhi Cloud Browser + Browser Use

Run a Browser Use Agent against a short-lived [Baizhi Cloud Browser](https://capybrowser.app.baizhi.cloud/) Session. The Agent reads the heading and explanatory sentence at `https://www.w3.org/Provider/Style/dummy.html`. Browser Use handles page actions over CDP; Baizhi Cloud Browser creates and ends the temporary Session. See the [installation contract](https://capybrowser.app.baizhi.cloud/docs/installation.md) and [Session API](https://capybrowser.app.baizhi.cloud/docs/browser-session-openapi.yaml).

## Prerequisites

- Python 3.11+, `uv`, and the reviewed browser-use `0.13.13` checkout (`129853546ff9cc169977d38b6038f9c4a4e734db`). This example checks that version before creating a Session because its single-use connection adapter depends on that version's lifecycle. The small durable-state lock uses `fcntl`, so run on macOS or Linux (Windows users can use WSL).
- A Baizhi Cloud Browser API key and sufficient balance/capacity. This example uses the public HTTPS service; TLS verification stays enabled.
- A model credential: `BROWSER_USE_API_KEY` for the default `ChatBrowserUse()`, or `CAPY_MODEL_CONFIG` pointing to a mode-0600 JSON file containing `base_url`, `model`, and `api_key` for a compatible OpenAI-style gateway. The model gateway and browser Session are billed separately.
- Supply keys through your shell's secure environment or secret manager. This example does not load `.env` files or accept keys on the command line. Never put keys or CDP control URLs in prompts, logs, issues, or source control.

From the repository root:

```bash
uv sync --no-default-groups
# Securely export CAPYBROWSER_API_KEY and either BROWSER_USE_API_KEY or CAPY_MODEL_CONFIG before continuing.
mkdir -p .capy-runs
chmod 700 .capy-runs
uv run --no-sync examples/integrations/capybrowser/main.py run --state .capy-runs/example-001
```

The final directory (`example-001`) must not already exist. Store `.capy-runs` outside version control; add it to your local `.git/info/exclude`, or choose a private absolute path outside the checkout. Its parent must already exist. Keep each run directory until release and billing have been checked.

For the optional gateway path, make `CAPY_MODEL_CONFIG` an absolute path to a private mode-0600 JSON file such as `{"base_url":"https://gateway.example/api/openai","model":"your-model-id","api_key":"your-key"}`. The base URL ends **before** `/chat/completions`; the SDK appends that route. Keep this file outside the checkout. The gateway must accept `response_format={"type":"json_object"}` and return an OpenAI-compatible chat completion with an un-fenced JSON object for structured Agent steps. An incompatible gateway fails the bounded task and still triggers explicit browser Session cleanup.

The example saves a private creation intent before sending one idempotent create request (`purpose=agent`, `max_seconds=180`, no Profile). It waits up to 45 seconds for readiness, obtains a single-use WSS control URL, and passes it privately to a separate Browser Use process. Browser connection, Agent execution and local disconnect have 20/120/5-second limits; the parent enforces a 140-second total worker deadline, shortened to stop before the Session's reported expiration. HTTP calls have a 10-second limit and cleanup has a separate 30-second limit.

The worker uses real `Agent.run(max_steps=7)` with `ChatBrowserUse()` by default or the configured gateway, a domain restriction and reduced tools for this reading task. The gateway adapter appends the Agent schema to the first system message, requests `json_object`, validates the response with Pydantic, allows up to ten model calls, and gives each reply up to 4096 output tokens. It passes text-only page context and disables the extra judge/planning/compaction calls. `extract` still uses the same configured model and counts toward the call bound. The private run directory retains `model-usage.json` (roles, message sizes, action names and token counts) and `agent-trace.json` (action names and result flags), never raw prompts, model replies or CDP URLs. These records do not establish model monetary cost; reconcile that through the gateway's own billing records. Raw library logs, tracing environment credentials, telemetry and cloud history sync are disabled to avoid exposing the control grant. Only the sanitized answer and lifecycle facts are printed. These tool restrictions are appropriate for this fixed example, not a general security sandbox for arbitrary tasks.

## Ending and interpreting the result

`Browser.stop()` disconnects the client. **Only the explicit Baizhi Cloud Browser Session end and subsequent management observations establish the browser Session cleanup facts.** The parent performs that cleanup after success, connection failure, timeout, SIGINT or SIGTERM. A force kill, power loss or unavailable service can still prevent cleanup; use the saved intent to recover.

The JSON result separates:

- `delete_outcome`: the last saved DELETE attempt's result: `accepted` for HTTP 202, `already_terminal` for HTTP 200, `unknown` after an attempted request with no validated response, or `not_requested`. `delete_http_status` preserves 200/202, otherwise `null`. A recovery that makes no DELETE retains that saved outcome; it is not a new response.
- `delete_accepted`: whether any HTTP 202 acceptance has been confirmed in this run's current-schema history. It becomes true only on 202 and remains true after a later 200 or unknown attempt. For example, `delete_accepted=true` together with `delete_outcome=already_terminal` and `delete_http_status=200` means an earlier 202 was confirmed, then the latest DELETE found the Session already terminal. A first 200 leaves `delete_accepted=false`. Acceptance is not release.
- `released`: whether the last fresh observation says `released`; `null` when no fresh observation was obtained. A `failed` or `ending_review_required` Session is not reported as released. `resource_outcome=startup_failed` preserves the terminal startup-failure fact separately.
- `billing_status`: the server's observed value, including `settled`, `waived`, `settling`, or `review_required`; `unknown` if unavailable. Pending billing is not treated as zero cost or proof of continuing usage charges.
- `actual_charge_centipoints`: only reported from final `settled`/`waived` billing; otherwise `null`. `charge_stop_at` is reported only when supplied by the server, never inferred from DELETE or a local clock.

`complete` means cleanup is resolved: either `released` with final billing, or terminal `failed` with final billing. A known `failed` Session still receives an idempotent DELETE (the API returns 200). `failed + waived` then stops polling with `released=false`, `resource_outcome=startup_failed`, and unchanged waived billing; no further recovery is requested. Failed Sessions with pending/review billing remain unresolved. A final billing amount or charge-stop timestamp is never invented when absent.

Exit codes: `0` means the requested command succeeded and cleanup is resolved; `1` means task/setup/API failure (inspect cleanup separately); `2` means cleanup remains unresolved; `130` means cancellation. A startup failure still returns `1` even if its cleanup is complete; a later recovery of that terminal Session can return `0` without rerunning the task. A model-reported success is not independent verification of its answer.

## Recovery

Use the **same** state directory and original browser-service credential:

```bash
uv run --no-sync examples/integrations/capybrowser/main.py recover --state .capy-runs/example-001
```

Recovery needs no model key and never runs the Agent. With a known Session ID it reads that Session, requests its end if needed, and checks release/billing again. If create returned no usable ID, recovery replays the exact saved idempotency key and body to resolve it, then ends the resulting Session. If the original request never reached the service, this replay can create the one intended Session and incur its start charge. Do not delete/edit the state, rotate the credential, or choose a new directory to work around an unknown creation result.

Schema-1 state from the earlier example did not distinguish DELETE 200 from 202. Recovery upgrades it to schema 2 while retaining its Session ID, idempotency key and request body. Its ambiguous acceptance flag is cleared, and an earlier attempt is reported as `unknown` until new evidence is obtained. It is not promoted to confirmed 202 history. This migration makes no API call and never creates a replacement intent.

Only one process can own a run directory at a time. If another instance is active, wait for it; do not remove its lock. If the API stays unavailable or reports review required, preserve the directory and use the Baizhi Cloud Browser console or support team to inspect that Session or original creation intent. Do not share the file publicly. The service's lifetime limit is a fallback; expiry alone is not a local confirmation of resource release or final billing.

This example does not reconnect or replay the Agent task. browser-use 0.13.13 has no public reconnect switch, so a narrowly scoped Session subclass replaces its private socket-drop callback for this example only. It observes the transport during initial setup as well as task execution, rejects a second connection attempt, and exits the worker immediately on unexpected socket loss. The parent reaps it and begins bounded Session cleanup. Normal `stop()` suppresses the loss callback. The adapter fails closed on an unsupported version or missing transport-monitoring seam; it does not modify the library class globally. A new task should use a new directory only after the previous run's outcome has been resolved. There is no Profile, login persistence, human takeover or challenge-bypass claim.

## Local fault tests

No API keys, cloud Session or model call are used:

```bash
uv run --no-sync python -m unittest discover -s examples/integrations/capybrowser -v
```

The tests exercise unknown creation and same-intent recovery, readiness failures, connection/task errors and cancellation, drop-callback races, terminal failure versus pending billing, response identity checks, and a later settlement check. Two additional real local Chrome disconnect tests are opt-in:

```bash
CAPY_LOCAL_CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  uv run --no-sync python -m unittest discover -s examples/integrations/capybrowser -k RealDisconnectTests -v
```

On Linux, set the executable path accordingly. The tests use a temporary profile and a loopback CDP fault relay, without disabling Chromium's sandbox or TLS verification. They drop the real browser-use connection during startup and during navigation, count connection attempts, and time the parent reaching a mock management DELETE. They use no cloud Session or model. Mock API tests and local browser tests do not establish a successful cloud Agent task or real cloud cleanup.
