# Browser Use v2 agent backend (recommended for QA)

Run the QA test as an autonomous **Browser Use cloud agent** instead of driving browser-harness
step by step. It's purpose-built for QA: a **judge** evaluates pass/fail against expected
behavior, and **structured output** forces the 1–5 score. It runs server-side, parallelizes, and
returns step-by-step evidence (screenshots + actions).

**Cost / credits:** the v2 agent spends Browser Use credits — about **$0.01 per task + ~$0.006 per
step (LLM) + $0.02/hr browser**, drawn from the account's monthly allowance. (The Claude-subagent
backend in `methodology.md` spends no Browser Use *task* credits.) Recommend v2 for real QA; fall
back to the Claude subagent to avoid credits.

> Note: the docs label the v2 API "legacy" and steer new projects to v3 — but the **`judge` +
> structured-output** evaluation features QA needs live on v2 (`POST /api/v2/tasks`), so that's
> what this backend uses.

## The endpoints

- **Create:** `POST https://api.browser-use.com/api/v2/tasks` → `202 {id, sessionId}`
- **Poll:** `GET https://api.browser-use.com/api/v2/tasks/{id}` → `status` ∈ `created → started →
  finished | failed | stopped`, plus `output`, `judgeVerdict`, `judgement`, `steps[]`, `cost`.
- Auth header on both: `X-Browser-Use-API-Key`.

## Key resolution — via browser-harness (it stores the key)

The v2 API authenticates with `BROWSER_USE_API_KEY` — the same key `methodology.md` step 0 resolves
(browser-harness's `.env`, the process env, or self-signup). The cleanest way to use
*browser-harness's stored key* is to run the calls **inside a `browser-harness` heredoc**, where
the key is already loaded into `os.environ` — no separate plumbing, no re-exporting. (Plain `curl`
with `$BROWSER_USE_API_KEY` also works if it's exported. The v2 task itself runs on a Browser Use
cloud browser, so no local Chrome is needed for the test — browser-harness here is just the key
store + HTTP runtime.)

## Flow: create → poll → report

Fill in `task`, `startUrl` (the public URL — tunnel a localhost target first), and
`judgeGroundTruth` (what success looks like), then run:

```bash
browser-harness <<'PY'
import os, json, time, urllib.request, urllib.error, subprocess, sys
KEY = os.environ.get("BROWSER_USE_API_KEY")
assert KEY, "no BROWSER_USE_API_KEY — resolve it per methodology.md step 0"
BASE = "https://api.browser-use.com/api/v2"

def open_local(url):
    """Open a URL in the user's LOCAL browser (Chrome first) so they can watch the cloud agent run.
    This views the dashboard thread — it does NOT run the test locally; the task still runs in the cloud."""
    cmds = ([["open", "-a", "Google Chrome", url], ["open", url]] if sys.platform == "darwin"
            else [["google-chrome", url], ["xdg-open", url]])
    for c in cmds:
        try:
            subprocess.Popen(c, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except FileNotFoundError:
            continue

def call(method, path, body=None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={"X-Browser-Use-API-Key": KEY, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"v2 API {e.code}: {e.read().decode()[:300]}")

# 1-5 score schema (structuredOutput must be a *stringified* JSON schema)
SCORE_SCHEMA = json.dumps({
    "type": "object",
    "properties": {
        "score":   {"type": "integer", "minimum": 1, "maximum": 5},
        "verdict": {"type": "string"},
        "worked":  {"type": "array", "items": {"type": "string"}},
        "issues":  {"type": "array", "items": {"type": "string"}},
    },
    "required": ["score", "verdict"],
})

created = call("POST", "/tasks", {
    "task": "QA TASK HERE — e.g. 'Add an item to the cart, go to checkout, and report whether "
            "it completes. Score 1-5 (5=flawless, 1=broken) with what worked and any issues.'",
    "startUrl": "https://PUBLIC-URL-UNDER-TEST",          # tunnel localhost first; pass the public URL
    "judge": True,
    "judgeGroundTruth": "SUCCESS LOOKS LIKE — e.g. 'An order-confirmation / thank-you page is shown.'",
    "structuredOutput": SCORE_SCHEMA,
    "maxSteps": 50,   # a CEILING, not a target — the agent stops when done, so this doesn't inflate cost;
                      # 50 gives room for a multi-step flow. Raise for long flows; cost = steps actually taken.
    # optional: "llm": "browser-use-2.0", "vision": True,
    #           "sessionSettings": {"proxyCountryCode": "us", "enableRecording": True}
})
tid = created["id"]
sid = created["sessionId"]
watch_url = f"https://cloud.browser-use.com/thread/{sid}"  # dashboard thread = the SESSION (not the task id)
print("created task", tid, "session", sid, flush=True)
print("watch:", watch_url, flush=True)
open_local(watch_url)                                     # pop it open in the user's local Chrome to watch

while True:                                               # poll to a terminal state
    t = call("GET", "/tasks/" + tid)
    if t["status"] in ("finished", "failed", "stopped"):
        break
    time.sleep(5)

print(json.dumps({
    "status":       t["status"],
    "score_output": t.get("output"),       # the structuredOutput JSON → the 1-5 score object
    "judgeVerdict": t.get("judgeVerdict"),  # True = passed the ground-truth check, False = failed
    "judgement":    t.get("judgement"),     # judge's reasoning (stringified JSON report)
    "cost_usd":     t.get("cost"),          # what this run spent
    "num_steps":    len(t.get("steps") or []),
}, indent=2))
PY
```

## Watch it live: open the agent session in local Chrome

As soon as a task is created, **open its dashboard thread in the user's local Chrome so they can watch the agent work** — that's the `open_local(...)` call above. The watch URL is built from the **session id**:

```
https://cloud.browser-use.com/thread/{sessionId}
```

That `/thread/<uuid>` page is the v2 agent's run: the live browser plus the agent's step-by-step reasoning, screenshots, and (when finished) the judge verdict. Notes:

- The `{id}` is the **`sessionId`** from `POST /tasks` — **not** the task `id`. (Verified: `GET /tasks/{sessionId}` 404s; the dashboard groups a run by its session.) Always print the URL too, so the user has it even if the browser doesn't auto-open.
- This is a **viewing** convenience only — it opens a webpage in local Chrome. It does **not** violate the "tests run on a cloud browser" rule; the task still executes server-side. (Don't confuse it with `liveUrl`, the raw single-session CDP viewer on `live.browser-use.com` that dies when the session stops — the dashboard thread persists after the run, so it's the better link to hand the user.)
- `open_local` targets the user's local Chrome (`open -a "Google Chrome"` on macOS, `google-chrome`/`xdg-open` on Linux), falling back to the default browser.

## Mapping the result to the verdict

Report exactly as `methodology.md`'s output format, sourced from the agent's result:

- **`Score: N/5`** ← the `score` field of the structured `output` — **but `judgeVerdict` overrides it.**
  The structured `score` is the agent's *self-report* and can be wrong (an agent will happily score a
  blank page 5/5). **If `judgeVerdict` is `False`, the flow FAILED regardless of the self-score** — cap
  it at ≤2 and lead with the judge's `failure_reason`. (Real example: an agent self-scored x.ai/pricing
  5/5 "fully functional"; the judge saw the page rendered blank and returned `false`. Trust the judge.)
- **Result / pass-fail** ← `judgeVerdict` (true = met the ground truth, false = didn't). The agent's
  `score`/`isSuccess` are self-reports and are less reliable — **`judgeVerdict` is authoritative.**
- **What worked / issues** ← the structured `worked` / `issues` arrays, cross-checked against
  `judgement` (the judge's reasoning).
- **Evidence** ← `steps[]`: each has `url`, `screenshotUrl`, `actions` (and sometimes `nextGoal` —
  may be empty). Cite the `screenshotUrl`s of the key moments.
- **Cost** ← surface `cost` so the user sees what the run spent.

Report it in this format (the same one the Claude backend uses — self-contained here so you don't
need to open `methodology.md`):

```
Score: N/5
Task: <what you asked the agent to verify>
Result: <pass/fail from judgeVerdict + one line>
What worked:
- <from the structured `worked` array / judgement>
Issues:
- [tag] <from `issues` / judgement; empty if none>
Evidence: <key steps[].screenshotUrl links>
Cost: $X.XX (Browser Use v2 agent, <n> steps)
```

## Fan out: many flows in parallel

The whole point of v2 subagents is parallel coverage. To test several flows at once, **create all
the tasks first** (each `POST /tasks` returns immediately with an `id`), then **poll them all** —
they run concurrently in Browser Use cloud:

```python
flows = [
    {"task": "Test signup: …", "startUrl": URL, "judgeGroundTruth": "Account created, lands on dashboard."},
    {"task": "Test checkout: …", "startUrl": URL, "judgeGroundTruth": "Order confirmation shown."},
    {"task": "Test search + filters: …", "startUrl": URL, "judgeGroundTruth": "Filtered results update."},
]
ids = []
for f in flows:
    c = call("POST", "/tasks", {**f, "judge": True, "structuredOutput": SCORE_SCHEMA, "maxSteps": 50})
    open_local(f"https://cloud.browser-use.com/thread/{c['sessionId']}")  # one Chrome tab per flow, to watch
    ids.append((f["task"][:40], c["id"]))

results = {}
while len(results) < len(ids):
    for label, tid in ids:
        if tid in results: continue
        t = call("GET", "/tasks/" + tid)
        if t["status"] in ("finished", "failed", "stopped"):
            self_score = (json.loads(t["output"]).get("score") if t.get("output") else None)
            passed = t.get("judgeVerdict") is True          # JUDGE is authoritative, not the self-score
            results[tid] = {"label": label, "passed": passed, "self_score": self_score,
                            "score": (self_score if passed else min(self_score or 2, 2)),  # judge=False caps it
                            "cost": t.get("cost")}
    time.sleep(5)
# Per flow: PASS only if judgeVerdict is True. A flow where the agent self-scored high but
# judgeVerdict is False is a *caught failure* — flag it and score it low.
# Overall = the weakest flow (min of the judge-corrected scores) — never average a failed flow up.
```

Watch the **concurrent-session cap** (Free = 3): creating more than the cap at once yields `429` —
batch the creates to stay under it.

## Gotchas

- **`structuredOutput` is a *string*** — pass `json.dumps(schema)`, not the schema object.
- **localhost isn't reachable** by the cloud agent — tunnel it (ngrok, per `methodology.md`) and
  pass the public `startUrl`; for a free-ngrok host, tell the agent in the `task` to click through
  any "You are about to visit" interstitial.
- **`429 TooManyConcurrentActiveSessionsError`** — the account hit its concurrent-session cap
  (Free = 3); wait or stop other sessions.
- **`maxSteps` is a safety ceiling, not a cost lever** — the agent stops when the task is complete, so the cap doesn't drive cost (this run capped at 15 but used 5 steps). Keep ~50 for headroom; raise for long flows.
- **Teardown is a no-op for the v2 path on a public URL** — the one-off session auto-closes and there's no tunnel to kill. (Only the Claude/localhost path needs teardown.)
- **Verify the key resolves before the billable create** — the snippet's `assert KEY` does this; if it's missing, resolve it per `methodology.md` step 0 *before* calling `POST /tasks`.
